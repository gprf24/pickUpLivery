"""
Frontend page routes for PickUp Livery.
Renders templates: tasks, pickup form, history, admin dashboard, etc.

History page:
- Groups rows by day.
- Counts photos and (NEW) provides actual photo idx list per pickup
  to avoid 404 when slots are non-sequential (e.g., only 1 and 3).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import func, outerjoin
from sqlalchemy import select as sa_select
from sqlalchemy import text
from sqlmodel import Session
from sqlmodel import select as sm_select

# Core deps & Jinja templates
from app.core.deps import (
    get_app_settings,
    get_current_user,
    get_current_user_optional,
    get_session,
    require_admin,
    templates,
)

# DB models
from app.db.models.links import UserPharmacyLink
from app.db.models.pharmacy import Pharmacy
from app.db.models.pickup import Pickup
from app.db.models.pickup_photo import PickupPhoto
from app.db.models.region import Region
from app.db.models.settings import AppSettings
from app.db.models.user import User, UserRole

router = APIRouter()


# ----------------------------- Helpers -----------------------------
def _as_start_dt(d: date) -> datetime:
    """Convert date → start of day (00:00:00)."""
    return datetime.combine(d, time.min)


def _as_end_dt(d: date) -> datetime:
    """Convert date → end of day (23:59:59.999...)."""
    return datetime.combine(d, time.max)


# Timezone used for displaying pickup times in Germany
TZ_DE = ZoneInfo("Europe/Berlin")


def _utc_to_de(dt: datetime) -> datetime:
    """Convert a UTC datetime (naive or aware) to Europe/Berlin."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_DE)


def _parse_int(val: Optional[str]) -> Optional[int]:
    """Return int(val) or None if val is None/empty/invalid."""
    if not val:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _parse_date(val: Optional[str]) -> Optional[date]:
    """Return date.fromisoformat(val) or None if empty/invalid (YYYY-MM-DD)."""
    if not val:
        return None
    try:
        return date.fromisoformat(val)
    except (TypeError, ValueError):
        return None


def _user_label(u: User) -> str:
    """Safe label for user: prefer full_name if model has it, otherwise login."""
    return getattr(u, "full_name", None) or u.login


def _compute_quick_range(
    quick_range: Optional[str],
) -> tuple[Optional[date], Optional[date]]:
    """
    Map a quick_range string (today / yesterday / this_week / last_week / tomorrow)
    to a (date_from, date_to) pair. Returns (None, None) if unknown.
    """
    if not quick_range:
        return None, None

    today = date.today()

    if quick_range == "today":
        return today, today

    if quick_range == "tomorrow":
        t = today + timedelta(days=1)
        return t, t

    if quick_range == "yesterday":
        y = today - timedelta(days=1)
        return y, y

    if quick_range == "this_week":
        # Monday as first day of week
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end

    if quick_range == "last_week":
        # Last week (Mon-Sun) relative to current week
        this_monday = today - timedelta(days=today.weekday())
        end = this_monday - timedelta(days=1)
        start = end - timedelta(days=6)
        return start, end

    # Fallback: unknown preset
    return None, None


# ------------------------------ Root redirect ------------------------------
@router.get("/", include_in_schema=False)
def root_redirect(
    request: Request,
    session: Session = Depends(get_session),
    user: Optional[User] = Depends(get_current_user_optional),
):
    # Not logged in → go to login
    if user is None:
        return RedirectResponse("/login", status_code=303)

    # Admin → history
    if user.role == "admin":
        return RedirectResponse("/history", status_code=303)

    # Driver → tasks
    return RedirectResponse("/tasks", status_code=303)


# ------------------------------ Tasks page ------------------------------
@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: AppSettings = Depends(get_app_settings),
):
    """
    Render tasks page: list of pharmacies assigned to the current user.

    Both drivers and admins see only pharmacies they are explicitly assigned to
    via UserPharmacyLink.
    """
    # Join UserPharmacyLink → Pharmacy and filter by current user
    stmt = (
        sm_select(Pharmacy)
        .join(UserPharmacyLink, UserPharmacyLink.pharmacy_id == Pharmacy.id)
        .where(
            UserPharmacyLink.user_id == user.id,
            Pharmacy.is_active == True,  # noqa: E712
        )
        .order_by(Pharmacy.name)
    )
    pharmacies = session.exec(stmt).all()

    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            "user": user,
            "settings": settings,
            "pharmacies": pharmacies,
        },
    )


# -------------------------- Success redirect page --------------------------
@router.get("/success/{pharmacy_id}", response_class=HTMLResponse)
def success_page(
    request: Request,
    pharmacy_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: AppSettings = Depends(get_app_settings),
):
    """Confirmation page variant that shows the selected pharmacy."""
    pharmacy = session.get(Pharmacy, pharmacy_id)
    return templates.TemplateResponse(
        "success.html",
        {
            "request": request,
            "user": user,
            "settings": settings,
            "pharmacy": pharmacy,
        },
    )


# -------------------------- HISTORY PAGE (grouped by day + photos) ----------------------------
@router.get("/history", response_class=HTMLResponse)
def history_page(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: AppSettings = Depends(get_app_settings),
    # Accept raw strings so empty strings won't cause 422
    region_id: Optional[str] = Query(None),
    pharmacy_id: Optional[str] = Query(None),
    driver_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    quick_range: Optional[str] = Query(None),  # <--- quick presets
):
    """
    Render pickup history.

    - Tolerant filters (all query params are optional and parsed manually).
    - Rows grouped by day for visual separators.
    - Photos: we now use per-pickup lists of photo public_ids (secure URLs)
      instead of predictable /pickup/{pickup_id}/photos/{idx} paths.
    - Access control:
        * Admins see all pickups (with filters).
        * Drivers see history only if settings.show_history_to_drivers is True;
          otherwise a 403-style page is shown.
    - New: quick_range presets (today / yesterday / this_week / last_week / tomorrow).
      If quick_range is set and no manual dates are given, it will define date_from/date_to.
    """

    # If history is disabled for drivers → render a dedicated 403 page
    if user.role == UserRole.driver and not settings.show_history_to_drivers:
        return templates.TemplateResponse(
            "history_forbidden.html",
            {
                "request": request,
                "user": user,
                "settings": settings,
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # 1) Parse filters from raw query strings
    rid = _parse_int(region_id)
    pid = _parse_int(pharmacy_id)
    did = _parse_int(driver_id)
    dfrom = _parse_date(date_from)
    dto = _parse_date(date_to)

    # Apply quick_range if dates not manually set
    if quick_range and not (dfrom or dto):
        q_from, q_to = _compute_quick_range(quick_range)
        dfrom = dfrom or q_from
        dto = dto or q_to

    is_admin = user.role == UserRole.admin

    # 2) Additional warnings for inconsistent filters (optional)
    warnings: List[str] = []

    # Validate region / pharmacy / driver combinations
    selected_region = session.get(Region, rid) if rid else None
    selected_pharmacy = session.get(Pharmacy, pid) if pid else None
    selected_driver = session.get(User, did) if did else None

    if selected_pharmacy and selected_region:
        if selected_pharmacy.region_id != selected_region.id:
            warnings.append(
                f"Pharmacy “{selected_pharmacy.name}” does not belong to region “{selected_region.name}”."
            )

    # Driver + pharmacy inconsistency
    if selected_driver and selected_pharmacy:
        link_exists = (
            session.exec(
                sm_select(UserPharmacyLink).where(
                    UserPharmacyLink.user_id == selected_driver.id,
                    UserPharmacyLink.pharmacy_id == selected_pharmacy.id,
                )
            ).first()
            is not None
        )
        if not link_exists:
            warnings.append(
                f"Driver “{_user_label(selected_driver)}” is not assigned to pharmacy “{selected_pharmacy.name}”."
            )

    # Driver + region but no specific pharmacy: check if driver has any pharmacy in this region
    if selected_driver and selected_region and not selected_pharmacy:
        driver_pharmacy_ids = session.exec(
            sm_select(UserPharmacyLink.pharmacy_id).where(
                UserPharmacyLink.user_id == selected_driver.id
            )
        ).all()
        any_in_region = False
        if driver_pharmacy_ids:
            any_in_region = (
                session.exec(
                    sm_select(Pharmacy).where(
                        Pharmacy.id.in_(driver_pharmacy_ids),  # type: ignore[arg-type]
                        Pharmacy.region_id == selected_region.id,
                    )
                ).first()
                is not None
            )
        if not any_in_region:
            warnings.append(
                f"Driver “{_user_label(selected_driver)}” has no pharmacies in region “{selected_region.name}”."
            )

    # 3) Base query: Pickup → Pharmacy → Region → User
    join_expr = outerjoin(
        outerjoin(
            outerjoin(Pickup, Pharmacy, Pharmacy.id == Pickup.pharmacy_id),
            Region,
            Region.id == Pharmacy.region_id,
        ),
        User,
        User.id == Pickup.user_id,
    )

    stmt = (
        sa_select(Pickup, Pharmacy, Region, User)
        .select_from(join_expr)
        .order_by(Pickup.created_at.desc())
    )

    # 4) Apply filters to the query
    if rid:
        stmt = stmt.where(Region.id == rid)
    if pid:
        stmt = stmt.where(Pharmacy.id == pid)
    # driver_id filter only makes sense for admins; for non-admins did is always None
    if did and is_admin:
        stmt = stmt.where(User.id == did)
    if dfrom:
        stmt = stmt.where(Pickup.created_at >= _as_start_dt(dfrom))
    if dto:
        stmt = stmt.where(Pickup.created_at <= _as_end_dt(dto))

    if not is_admin:
        # Non-admins only see their own pickups (but only if history is enabled for them)
        stmt = stmt.where(Pickup.user_id == user.id)

    raw_rows = session.exec(stmt).all()

    # 5) Convert to (Pickup, Pharmacy, User) tuples and collect pickup_ids
    rows: List[Tuple[Pickup, Optional[Pharmacy], Optional[User]]] = []
    pickup_ids: List[int] = []
    for tup in raw_rows:
        pickup = tup[0] if len(tup) > 0 else None
        pharmacy = tup[1] if len(tup) > 1 else None
        user_row = tup[3] if len(tup) > 3 else None
        if pickup is None:
            continue
        rows.append((pickup, pharmacy, user_row))
        pickup_ids.append(pickup.id)

    # 6) Photo public_ids per pickup (for secure non-guessable URLs)
    photo_public_ids: Dict[int, List[str]] = {}

    if pickup_ids:
        photo_stmt = (
            sa_select(PickupPhoto.pickup_id, PickupPhoto.public_id)
            .where(PickupPhoto.pickup_id.in_(pickup_ids))  # type: ignore[arg-type]
            .order_by(PickupPhoto.pickup_id, PickupPhoto.idx)
        )
        for pickup_id, public_id in session.exec(photo_stmt).all():
            photo_public_ids.setdefault(pickup_id, []).append(public_id)

    # 7) Group by day (date portion of created_at in DE time)
    groups: Dict[str, List[Tuple[Pickup, Optional[Pharmacy], Optional[User]]]] = {}
    for pickup, pharmacy, user_row in rows:
        # Convert UTC->DE for grouping purposes
        created_at_utc = pickup.created_at
        if created_at_utc.tzinfo is None:
            created_at_utc = created_at_utc.replace(tzinfo=timezone.utc)
        created_at_de = created_at_utc.astimezone(TZ_DE)
        day_key = created_at_de.date().isoformat()
        groups.setdefault(day_key, []).append((pickup, pharmacy, user_row))

    # 8) Reference lists for filters
    regions = session.exec(sm_select(Region).order_by(Region.name)).all()
    pharmacies = session.exec(sm_select(Pharmacy).order_by(Pharmacy.name)).all()
    users = session.exec(sm_select(User).order_by(User.login)).all()

    # 9) Prepare normalized strings for template
    active_filters = {
        "region_id": str(rid) if rid is not None else "",
        "pharmacy_id": str(pid) if pid is not None else "",
        "driver_id": str(did) if (did is not None and is_admin) else "",
        "date_from": dfrom.isoformat() if dfrom else "",
        "date_to": dto.isoformat() if dto else "",
        "quick_range": quick_range or "",
    }

    # 10) Render template
    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "user": user,
            "settings": settings,
            "groups": groups,  # grouped rows by day
            "photo_public_ids": photo_public_ids,  # pickup_id -> [public_id1, public_id2, ...]
            "regions": regions,
            "pharmacies": pharmacies,
            "users": users,
            "warnings": warnings,
            "active_filters": active_filters,
        },
    )


@router.get("/history/export")
def history_export(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    # Accept same filter params as /history so export matches UI
    region_id: Optional[str] = Query(None),
    pharmacy_id: Optional[str] = Query(None),
    driver_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    quick_range: Optional[str] = Query(None),
    format: str = Query("csv"),
):
    """
    Export pickup history for admins as CSV or Excel.

    Columns:
      - region
      - pharmacy
      - driver
      - pickup_time_de     (pickup timestamp converted to Europe/Berlin)
      - timing_status      (on_time / late / no_cutoff)
      - cutoff_time_utc    (snapshot of pharmacy cutoff for that day, time-of-day in UTC)
      - photo_count        (number of stored photos)
      - geolocation        (lat,lon if coordinates are present)
      - comment            (optional driver comment)
    """
    require_admin(user)

    # 1) Parse filters
    rid = _parse_int(region_id)
    pid = _parse_int(pharmacy_id)
    did = _parse_int(driver_id)
    dfrom = _parse_date(date_from)
    dto = _parse_date(date_to)

    # Apply quick_range if dates are not set
    if quick_range and not (dfrom or dto):
        q_from, q_to = _compute_quick_range(quick_range)
        dfrom = dfrom or q_from
        dto = dto or q_to

    # 2) Base query: same joins as history_page
    join_expr = outerjoin(
        outerjoin(
            outerjoin(Pickup, Pharmacy, Pharmacy.id == Pickup.pharmacy_id),
            Region,
            Region.id == Pharmacy.region_id,
        ),
        User,
        User.id == Pickup.user_id,
    )

    stmt = (
        sa_select(Pickup, Pharmacy, Region, User)
        .select_from(join_expr)
        .order_by(Pickup.created_at.desc())
    )

    # 3) Apply filters (admins can filter by any combination)
    if rid:
        stmt = stmt.where(Region.id == rid)
    if pid:
        stmt = stmt.where(Pharmacy.id == pid)
    if did:
        stmt = stmt.where(User.id == did)
    if dfrom:
        stmt = stmt.where(Pickup.created_at >= _as_start_dt(dfrom))
    if dto:
        stmt = stmt.where(Pickup.created_at <= _as_end_dt(dto))

    raw_rows = session.exec(stmt).all()

    # 4) Build list of typed tuples and pickup IDs
    rows: list[tuple[Pickup, Optional[Pharmacy], Optional[Region], Optional[User]]] = []
    pickup_ids: list[int] = []

    for tup in raw_rows:
        pickup = tup[0] if len(tup) > 0 else None
        pharmacy = tup[1] if len(tup) > 1 else None
        region = tup[2] if len(tup) > 2 else None
        user_row = tup[3] if len(tup) > 3 else None

        if pickup is None:
            continue

        rows.append((pickup, pharmacy, region, user_row))
        pickup_ids.append(pickup.id)

    # 5) Photo counts per pickup (using a lightweight query)
    photo_count_by_pickup: dict[int, int] = {}
    if pickup_ids:
        photo_stmt = sa_select(PickupPhoto.pickup_id).where(
            PickupPhoto.pickup_id.in_(pickup_ids)  # type: ignore[arg-type]
        )
        for (pid_row,) in session.exec(photo_stmt).all():
            photo_count_by_pickup[pid_row] = photo_count_by_pickup.get(pid_row, 0) + 1

    # 6) Build export rows
    data_rows: list[dict[str, str]] = []
    for pickup, pharmacy, region, user_row in rows:
        region_name = region.name if region else ""
        pharmacy_name = pharmacy.name if pharmacy else ""
        driver_name = ""
        if user_row is not None:
            driver_name = getattr(user_row, "full_name", None) or user_row.login

        pickup_time_de = _utc_to_de(pickup.created_at)
        pickup_time_str = pickup_time_de.strftime("%Y-%m-%d %H:%M:%S")

        photo_count = photo_count_by_pickup.get(pickup.id, 0)

        if pickup.latitude is not None and pickup.longitude is not None:
            geolocation = f"{pickup.latitude:.6f},{pickup.longitude:.6f}"
        else:
            geolocation = ""

        # NEW: timing status and cutoff snapshot based on cutoff_at_utc
        timing_status = pickup.timing_status or ""

        if pickup.cutoff_at_utc:
            cutoff_utc = pickup.cutoff_at_utc
            if cutoff_utc.tzinfo is None:
                cutoff_utc = cutoff_utc.replace(tzinfo=timezone.utc)
            cutoff_time_utc_str = cutoff_utc.time().strftime("%H:%M:%S")
        else:
            cutoff_time_utc_str = ""

        data_rows.append(
            {
                "region": region_name,
                "pharmacy": pharmacy_name,
                "driver": driver_name,
                "pickup_time_de": pickup_time_str,
                "timing_status": timing_status,
                "cutoff_time_utc": cutoff_time_utc_str,
                "photo_count": str(photo_count),
                "geolocation": geolocation,
                "comment": pickup.comment or "",
            }
        )

    # 7) Export in requested format
    headers = [
        "region",
        "pharmacy",
        "driver",
        "pickup_time_de",
        "timing_status",
        "cutoff_time_utc",
        "photo_count",
        "geolocation",
        "comment",
    ]

    fmt = (format or "csv").lower()
    if fmt not in {"csv", "xlsx"}:
        raise HTTPException(
            status_code=400, detail="Invalid export format, expected csv or xlsx."
        )

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(data_rows)
        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="pickups_history.csv"'
            },
        )

    # Excel export via openpyxl
    try:
        from openpyxl import Workbook  # type: ignore[import]
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise HTTPException(
            status_code=500,
            detail=f"Excel export is not available: {exc}",
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "History"

    ws.append(headers)
    for row in data_rows:
        ws.append([row[h] for h in headers])

    binary_output = io.BytesIO()
    wb.save(binary_output)
    binary_output.seek(0)

    return StreamingResponse(
        binary_output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="pickups_history.xlsx"'},
    )


# ------------------------- Admin stats (example) -------------------------
@router.get("/admin/stats", response_class=HTMLResponse)
def admin_stats_page(
    request: Request,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
    settings: AppSettings = Depends(get_app_settings),
):
    """
    Example admin stats page.

    Currently shows simple counts; can be extended later.
    """
    require_admin(current)

    counts = {
        "users": session.exec(sm_select(func.count(User.id))).one(),
        "regions": session.exec(sm_select(func.count(Region.id))).one(),
        "pharmacies": session.exec(sm_select(func.count(Pharmacy.id))).one(),
    }

    users = session.exec(sm_select(User).order_by(User.login)).all()
    regions = session.exec(sm_select(Region).order_by(Region.name)).all()
    pharmacies = session.exec(sm_select(Pharmacy).order_by(Pharmacy.name)).all()

    user_by_id = {u.id: u for u in users}
    region_by_id = {r.id: r for r in regions}

    links = session.exec(sm_select(UserPharmacyLink)).all()
    assignments: Dict[int, List[int]] = {}
    for ln in links:
        assignments.setdefault(ln.pharmacy_id, []).append(ln.user_id)

    context = {
        "request": request,
        "user": current,
        "settings": settings,
        "stats": {"counts": counts},
        "users": users,
        "regions": regions,
        "pharmacies": pharmacies,
        "user_by_id": user_by_id,
        "region_by_id": region_by_id,
        "assignments": assignments,
    }

    return templates.TemplateResponse("admin/stats.html", context)
