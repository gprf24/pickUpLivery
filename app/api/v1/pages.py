# app/api/v1/pages.py
"""
Frontend page routes for PickUp Livery.
Renders templates: tasks, pickup form, history, admin dashboard, etc.

History page:
- Groups rows by day.
- Counts photos and (NEW) provides actual photo idx list per pickup
  to avoid 404 when slots are non-sequential (e.g., only 1 and 3).
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, outerjoin
from sqlalchemy import select as sa_select
from sqlalchemy import text
from sqlmodel import Session
from sqlmodel import select as sm_select

# Core deps & Jinja templates
from app.core.deps import get_current_user, get_session, require_admin, templates

# DB models
from app.db.models.links import UserPharmacyLink
from app.db.models.pharmacy import Pharmacy
from app.db.models.pickup import Pickup
from app.db.models.pickup_photo import PickupPhoto
from app.db.models.region import Region
from app.db.models.user import User, UserRole

router = APIRouter()


# ----------------------------- Helpers -----------------------------
def _as_start_dt(d: date) -> datetime:
    """Convert date → start of day (00:00:00)."""
    return datetime.combine(d, time.min)


def _as_end_dt(d: date) -> datetime:
    """Convert date → end of day (23:59:59.999...)."""
    return datetime.combine(d, time.max)


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


# ------------------------------ Root redirect ------------------------------
@router.get("/", include_in_schema=False)
def root_redirect(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Default landing page by role:
      - admin  → /history
      - driver → /tasks

    Note: if user is not authenticated, get_current_user will raise 401.
    Your global exception handler should redirect 401 to /login.
    """
    # if user.role == UserRole.admin:
    #     return RedirectResponse(url="/history", status_code=303)
    return RedirectResponse(url="/tasks", status_code=303)


# -------------------------- TASKS PAGE ------------------------------
@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Driver landing page.
    Loads pharmacies assigned to the current user (via PP_user_pharmacy_link)
    and exposes them under 'pharmacies' (what tasks.html expects).
    """
    links = session.exec(
        sm_select(UserPharmacyLink.pharmacy_id).where(
            UserPharmacyLink.user_id == user.id
        )
    ).all()
    assigned_ids = list(links)  # already ints

    pharmacies: List[Pharmacy] = []
    region_by_id: Dict[int, Region] = {}
    regions: List[Region] = []

    if assigned_ids:
        pharmacies = session.exec(
            sm_select(Pharmacy)
            .where(Pharmacy.id.in_(assigned_ids))  # type: ignore[arg-type]
            .order_by(Pharmacy.name)
        ).all()

        region_ids = sorted(
            {p.region_id for p in pharmacies if p.region_id is not None}
        )
        if region_ids:
            regions = session.exec(
                sm_select(Region).where(Region.id.in_(region_ids))  # type: ignore[arg-type]
            ).all()
            region_by_id = {r.id: r for r in regions}

    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            "user": user,
            "pharmacies": pharmacies,
            "region_by_id": region_by_id,
            "regions": regions,
            "assigned_ids": assigned_ids,
        },
    )


# -------------------------- PICKUP FORM (generic) -----------------------------
@router.get("/pickup", response_class=HTMLResponse)
def pickup_form(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Generic pickup creation form (with pharmacy dropdown).
    Note: you also have /pickup/{pharmacy_id} in app/api/v1/pickups.py.
    """
    pharmacies: List[Pharmacy] = session.exec(
        sm_select(Pharmacy).order_by(Pharmacy.name)
    ).all()
    return templates.TemplateResponse(
        "pickup.html",
        {"request": request, "user": user, "pharmacies": pharmacies},
    )


# -------------------------- SUCCESS PAGE ----------------------------
@router.get("/success", response_class=HTMLResponse)
def success_page(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Simple confirmation page after creating a pickup."""
    return templates.TemplateResponse(
        "success.html", {"request": request, "user": user}
    )


@router.get("/success/{pharmacy_id}", response_class=HTMLResponse)
def pickup_success(
    request: Request,
    pharmacy_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Confirmation page variant that shows the selected pharmacy."""
    pharmacy = session.get(Pharmacy, pharmacy_id)
    return templates.TemplateResponse(
        "success.html",
        {"request": request, "user": user, "pharmacy": pharmacy},
    )


# -------------------------- HISTORY PAGE (grouped by day + photos) ----------------------------
@router.get("/history", response_class=HTMLResponse)
def history_page(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    # Accept raw strings so empty strings won't cause 422
    region_id: Optional[str] = Query(None),
    pharmacy_id: Optional[str] = Query(None),
    driver_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """
    Render pickup history.

    - Tolerant filters (all query params are optional and parsed manually).
    - Rows grouped by day for visual separators.
    - Photos: we now use per-pickup lists of photo public_ids (secure URLs)
      instead of predictable /pickup/{pickup_id}/photos/{idx} paths.
    """

    # 1) Parse filters from raw query strings
    rid = _parse_int(region_id)
    pid = _parse_int(pharmacy_id)
    did = _parse_int(driver_id)
    dfrom = _parse_date(date_from)
    dto = _parse_date(date_to)

    # If user accidentally swapped dates, normalize them (from <= to)
    if dfrom and dto and dfrom > dto:
        dfrom, dto = dto, dfrom

    # 2) Load selected objects for consistency warnings (region/pharmacy/driver mapping)
    selected_region: Optional[Region] = session.get(Region, rid) if rid else None
    selected_pharmacy: Optional[Pharmacy] = session.get(Pharmacy, pid) if pid else None
    selected_driver: Optional[User] = session.get(User, did) if did else None

    warnings: List[str] = []

    # Region and pharmacy must be consistent
    if selected_region and selected_pharmacy:
        if selected_pharmacy.region_id != selected_region.id:
            warnings.append(
                f"Pharmacy “{selected_pharmacy.name}” does not belong to region “{selected_region.name}”."
            )

    # Driver must be linked to pharmacy (via UserPharmacyLink)
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
        driver_pharmacy_ids = list(driver_pharmacy_ids)
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

    # 4) Apply filters if they were parsed successfully
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

    # 5) Convert to (Pickup, Pharmacy, User) tuples and collect pickup_ids
    rows: List[Tuple[Pickup, Pharmacy, User]] = []
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
            sa_select(PickupPhoto.pickup_id, PickupPhoto.public_id).where(
                PickupPhoto.pickup_id.in_(pickup_ids)
            )
            # Order by idx so thumbnails stay in "slot" order (1..4)
            .order_by(PickupPhoto.pickup_id, PickupPhoto.idx)
        )
        for pid_val, public_id in session.exec(photo_stmt):
            pid_int = int(pid_val)
            photo_public_ids.setdefault(pid_int, []).append(public_id)

    # 7) Group rows by day for the UI
    groups: List[Dict[str, object]] = []
    last_day_key: Optional[date] = None
    for pickup, ph, u in rows:
        day_key = pickup.created_at.date() if pickup.created_at else date.min
        if last_day_key != day_key:
            groups.append({"day": day_key, "items": []})
            last_day_key = day_key
        groups[-1]["items"].append((pickup, ph, u))

    # 8) Dropdown datasets for filters
    regions = session.exec(sm_select(Region).order_by(Region.name)).all()
    pharmacies = session.exec(sm_select(Pharmacy).order_by(Pharmacy.name)).all()
    users = session.exec(sm_select(User).order_by(User.login)).all()

    # 9) Render template
    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "user": user,
            "groups": groups,  # grouped rows by day
            "photo_public_ids": photo_public_ids,  # pickup_id -> [public_id1, public_id2, ...]
            "regions": regions,
            "pharmacies": pharmacies,
            "users": users,
            "warnings": warnings,
            "active_filters": {
                "region_id": region_id or "",
                "pharmacy_id": pharmacy_id or "",
                "driver_id": driver_id or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
        },
    )


# -------------------------- ADMIN DASHBOARD -------------------------
@router.get("/admin", response_class=HTMLResponse)
def admin_home(
    request: Request,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Admin dashboard:
    - User management (create, toggle active)
    - Region management (create, toggle active)
    - Pharmacy management (create, toggle active)
    - User ↔ Pharmacy assignments
    - Basic statistics
    """
    require_admin(current)

    # --- Quick table counts ---
    tables = [
        "PP_user",
        "PP_region",
        "PP_pharmacy",
        "PP_pickup",
        "PP_user_pharmacy_link",
    ]
    counts: Dict[str, Optional[int]] = {}
    for tbl in tables:
        try:
            counts[tbl] = session.exec(text(f'SELECT COUNT(*) FROM "{tbl}"')).one()[0]
        except Exception:
            counts[tbl] = None

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
        "stats": {"counts": counts},
        "users": users,
        "regions": regions,
        "pharmacies": pharmacies,
        "user_by_id": user_by_id,
        "region_by_id": region_by_id,
        "assignments": assignments,
        "user_list": users,
        "region_list": regions,
        "regions_all": regions,
    }

    return templates.TemplateResponse("admin/home.html", context)
