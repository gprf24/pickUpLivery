"""
Admin endpoints:

- User management (create, toggle active, change password, per-user GPS flag).
- Region management (create, toggle active).
- Pharmacy management (create, toggle active, assign drivers, cutoff time config).
- Diagnostics (duplicate name preview).
- Global AppSettings edit (pickup limits, GPS behaviour, photo rules).
"""

from __future__ import annotations

from datetime import time
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlmodel import Session
from sqlmodel import select
from sqlmodel import select as sm_select

from app.core.deps import (
    get_app_settings,
    get_current_user,
    get_session,
    require_admin,
    templates,
)
from app.core.security import hash_password
from app.db.models.links import UserPharmacyLink
from app.db.models.pharmacy import Pharmacy
from app.db.models.pickup import Pickup
from app.db.models.pickup_photo import PickupPhoto
from app.db.models.region import Region
from app.db.models.settings import AppSettings
from app.db.models.user import User, UserRole

router = APIRouter()

# Global flag controlling visibility in Swagger docs
INCLUDE_IN_SCHEMA: bool = False


# ----------------------------- Helpers -----------------------------


def _user_label(u: User) -> str:
    """Helper string for labels: full_name or login."""
    return getattr(u, "full_name", None) or u.login


def _get_app_settings(session: Session) -> AppSettings:
    """Wrapper around core deps helper for easier unit testing."""
    return get_app_settings(session)


def _parse_local_hhmm(value: Optional[str]) -> Optional[time]:
    """
    Parse a local time string "HH:MM" into a `time` object.

    Returns:
        - None if the string is empty/whitespace.
        - time(hour, minute) if parsing is successful.

    Raises:
        ValueError if the format is invalid.
    """
    if value is None:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        hh_str, mm_str = value.split(":", 1)
        hh = int(hh_str)
        mm = int(mm_str)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
        return time(hour=hh, minute=mm)
    except Exception:
        raise ValueError(f"Invalid time format '{value}', expected HH:MM")


def _is_ajax(request: Request) -> bool:
    """Detect if request came from frontend fetch (AJAX)."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


# --------------------------- Admin dashboard ---------------------------


@router.get("/admin", response_class=HTMLResponse, include_in_schema=INCLUDE_IN_SCHEMA)
def admin_dashboard(
    request: Request,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Render main admin dashboard: quick stats, users, regions, pharmacies.
    """
    require_admin(current)

    # ---------- Counts ----------
    users_count = session.exec(sa_select(func.count(User.id))).one()[0]
    regions_count = session.exec(sa_select(func.count(Region.id))).one()[0]
    pharmacies_count = session.exec(sa_select(func.count(Pharmacy.id))).one()[0]
    pickups_count = session.exec(sa_select(func.count(Pickup.id))).one()[0]
    photos_count = session.exec(sa_select(func.count(PickupPhoto.id))).one()[0]
    app_settings_count = session.exec(sa_select(func.count(AppSettings.id))).one()[0]
    links_count = session.exec(
        sa_select(func.count()).select_from(UserPharmacyLink)
    ).one()[0]

    counts = {
        "users": users_count,
        "regions": regions_count,
        "pharmacies": pharmacies_count,
        "pickups": pickups_count,
        "user_pharmacy_links": links_count,
        "pickup_photos": photos_count,
        "app_settings": app_settings_count,
    }

    users = session.exec(sm_select(User).order_by(User.login)).all()
    regions = session.exec(sm_select(Region).order_by(Region.name)).all()
    pharmacies = session.exec(sm_select(Pharmacy).order_by(Pharmacy.name)).all()

    user_by_id = {u.id: u for u in users}
    region_by_id = {r.id: r for r in regions}

    links = session.exec(sm_select(UserPharmacyLink)).all()
    assignments: dict[int, list[int]] = {}
    for ln in links:
        assignments.setdefault(ln.pharmacy_id, []).append(ln.user_id)

    settings_obj = _get_app_settings(session)

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
        "settings": settings_obj,
    }

    return templates.TemplateResponse("admin/home.html", context)


# ------------------------------ Users ------------------------------


@router.post(
    "/admin/users/create",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_create_user(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    role: str = Form("driver"),
    require_pickup_location: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Create a new user (admin-only).

    - If normal form submit (no AJAX) -> redirect back to /admin.
    - If AJAX (X-Requested-With: XMLHttpRequest) -> JSON with new user payload.
    """
    require_admin(current)

    exists = session.exec(select(User).where(User.login == login)).first()
    if exists:
        if _is_ajax(request):
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "Login already exists"},
            )
        raise HTTPException(status_code=400, detail="Login already exists")

    try:
        user_role = UserRole(role)
    except ValueError:
        if _is_ajax(request):
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "Invalid role"},
            )
        raise HTTPException(status_code=400, detail="Invalid role")

    # Checkbox sends some string (e.g. "1") if checked, or nothing (None) if unchecked.
    if require_pickup_location is not None:
        gps_flag: Optional[bool] = True
    else:
        gps_flag = None  # inherit global GPS setting

    user = User(
        login=login,
        password_hash=hash_password(password),
        role=user_role,
        is_active=True,
        require_pickup_location=gps_flag,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    if not _is_ajax(request):
        return RedirectResponse(url="/admin", status_code=303)

    if gps_flag is None:
        gps_mode = "inherit"
    elif gps_flag:
        gps_mode = "require"
    else:
        gps_mode = "no"

    return JSONResponse(
        {
            "ok": True,
            "user": {
                "id": user.id,
                "login": user.login,
                "role": user.role.value,
                "is_active": user.is_active,
                "gps_mode": gps_mode,
            },
        }
    )


@router.post(
    "/admin/users/{user_id}/gps",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_set_user_gps_mode(
    user_id: int,
    gps_mode: str = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Update per-user GPS requirement flag (AJAX).

    gps_mode can be:
      - "inherit" -> require_pickup_location = None
      - "require" -> require_pickup_location = True
      - "no"      -> require_pickup_location = False
    """
    require_admin(current)

    u = session.get(User, user_id)
    if not u:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "User not found"}
        )

    if gps_mode == "inherit":
        u.require_pickup_location = None
    elif gps_mode == "require":
        u.require_pickup_location = True
    elif gps_mode == "no":
        u.require_pickup_location = False
    else:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Invalid GPS mode"},
        )

    session.add(u)
    session.commit()

    return JSONResponse({"ok": True, "gps_mode": gps_mode})


@router.post(
    "/admin/users/{user_id}/password",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_change_user_password_path(
    user_id: int,
    new_password: str = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Change password for a given user (AJAX, matches /admin/users/{id}/password).
    """
    require_admin(current)

    u = session.get(User, user_id)
    if not u:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "User not found"}
        )

    if len(new_password) < 6:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Password must be at least 6 characters"},
        )

    u.password_hash = hash_password(new_password)
    session.add(u)
    session.commit()

    return JSONResponse({"ok": True})


@router.post(
    "/admin/users/{user_id}/toggle-active",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_toggle_user_active_path(
    user_id: int,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Toggle user.is_active flag (AJAX, matches /admin/users/{id}/toggle-active).
    """
    require_admin(current)

    u = session.get(User, user_id)
    if not u:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "User not found"}
        )

    # Safety: do not allow the currently logged-in admin to toggle themselves,
    # to avoid accidentally deactivating their own account.
    if u.id == current.id:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "You cannot deactivate yourself"},
        )

    u.is_active = not u.is_active
    session.add(u)
    session.commit()

    return JSONResponse({"ok": True, "is_active": u.is_active})


@router.post(
    "/admin/users/{user_id}/delete",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_delete_user(
    user_id: int,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Hard-delete a user (admin-only, AJAX).

    Safety rules:
    - You cannot delete yourself.
    - You cannot delete a user that has pickups or pharmacy assignments.
    """
    require_admin(current)

    user = session.get(User, user_id)
    if not user:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "User not found"}
        )

    # Do not allow deleting yourself
    if user.id == current.id:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "You cannot delete yourself"},
        )

    # Check for related pickups
    pickups_count = session.exec(
        sa_select(func.count(Pickup.id)).where(Pickup.user_id == user_id)
    ).one()[0]

    # Check for user-pharmacy links
    links_count = session.exec(
        sa_select(func.count())
        .select_from(UserPharmacyLink)
        .where(UserPharmacyLink.user_id == user_id)
    ).one()[0]

    if pickups_count > 0 or links_count > 0:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "Cannot delete user with pickups or pharmacy assignments",
            },
        )

    session.delete(user)
    session.commit()

    return JSONResponse({"ok": True})


# ------------------------------ Regions ------------------------------


@router.post(
    "/admin/regions/create",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_create_region(
    request: Request,
    name: str = Form(...),
    is_active: bool = Form(True),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Create a new region (admin-only).

    - Non-AJAX -> redirect.
    - AJAX     -> JSON with new region payload.
    """
    require_admin(current)

    existing = session.exec(select(Region).where(Region.name == name)).first()
    if existing:
        if _is_ajax(request):
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "Region with this name already exists"},
            )
        raise HTTPException(
            status_code=400, detail="Region with this name already exists"
        )

    region = Region(name=name, is_active=is_active)
    session.add(region)
    session.commit()
    session.refresh(region)

    if not _is_ajax(request):
        return RedirectResponse(url="/admin", status_code=303)

    return JSONResponse(
        {
            "ok": True,
            "region": {
                "id": region.id,
                "name": region.name,
                "is_active": region.is_active,
            },
        }
    )


@router.post(
    "/admin/regions/{region_id}/toggle",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_toggle_region_active_path(
    region_id: int,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Toggle region.is_active (AJAX, matches /admin/regions/{id}/toggle).
    """
    require_admin(current)

    region = session.get(Region, region_id)
    if not region:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "Region not found"}
        )

    region.is_active = not region.is_active
    session.add(region)
    session.commit()

    return JSONResponse({"ok": True, "is_active": region.is_active})


@router.post(
    "/admin/regions/{region_id}/delete",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_delete_region(
    region_id: int,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Hard-delete a region (admin-only, AJAX).

    Safety rules:
    - You cannot delete a region that still has pharmacies.
    """
    require_admin(current)

    region = session.get(Region, region_id)
    if not region:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "Region not found"}
        )

    # Check if region has pharmacies
    pharmacies_count = session.exec(
        sa_select(func.count(Pharmacy.id)).where(Pharmacy.region_id == region_id)
    ).one()[0]

    if pharmacies_count > 0:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "Cannot delete region with existing pharmacies",
            },
        )

    session.delete(region)
    session.commit()

    return JSONResponse({"ok": True})


# ------------------------------ Pharmacies ------------------------------


@router.post(
    "/admin/pharmacies/create",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_create_pharmacy(
    request: Request,
    name: str = Form(...),
    region_id: int = Form(...),
    address: str = Form(""),
    # If checkbox exists in form, can stay as is
    is_active: bool = Form(True),
    # Optional default Mon–Fri cutoff time from the form, e.g. "12:23"
    default_weekday_cutoff_local: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Create a new pharmacy (admin-only).

    If `default_weekday_cutoff_local` is provided as "HH:MM",
    it will be applied as Mon–Fri local cutoff time.
    Later you can still fine-tune all days via the weekly cutoff editor.
    """
    require_admin(current)

    region = session.get(Region, region_id)
    if not region:
        if _is_ajax(request):
            return JSONResponse(
                status_code=404,
                content={"ok": False, "error": "Region not found"},
            )
        raise HTTPException(status_code=404, detail="Region not found")

    existing = session.exec(
        select(Pharmacy).where(Pharmacy.name == name, Pharmacy.region_id == region_id)
    ).first()
    if existing:
        if _is_ajax(request):
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "error": "Pharmacy with this name already exists in this region",
                },
            )
        raise HTTPException(
            status_code=400,
            detail="Pharmacy with this name already exists in this region",
        )

    weekday_cutoff_time: Optional[time] = None
    if default_weekday_cutoff_local:
        try:
            weekday_cutoff_time = _parse_local_hhmm(default_weekday_cutoff_local)
        except ValueError as exc:
            if _is_ajax(request):
                return JSONResponse(
                    status_code=400,
                    content={"ok": False, "error": str(exc)},
                )
            raise HTTPException(status_code=400, detail=str(exc))

    pharmacy = Pharmacy(
        name=name,
        region_id=region_id,
        address=address,
        is_active=is_active,
        cutoff_mon_local=weekday_cutoff_time,
        cutoff_tue_local=weekday_cutoff_time,
        cutoff_wed_local=weekday_cutoff_time,
        cutoff_thu_local=weekday_cutoff_time,
        cutoff_fri_local=weekday_cutoff_time,
    )
    session.add(pharmacy)
    session.commit()
    session.refresh(pharmacy)

    if not _is_ajax(request):
        return RedirectResponse(url="/admin", status_code=303)

    def _fmt(val: Optional[time]) -> Optional[str]:
        return val.strftime("%H:%M") if val else None

    return JSONResponse(
        {
            "ok": True,
            "pharmacy": {
                "id": pharmacy.id,
                "name": pharmacy.name,
                "region_id": pharmacy.region_id,
                "region_name": region.name,
                "address": pharmacy.address or "",
                "is_active": pharmacy.is_active,
                "cutoffs": {
                    "mon": _fmt(pharmacy.cutoff_mon_local),
                    "tue": _fmt(pharmacy.cutoff_tue_local),
                    "wed": _fmt(pharmacy.cutoff_wed_local),
                    "thu": _fmt(pharmacy.cutoff_thu_local),
                    "fri": _fmt(pharmacy.cutoff_fri_local),
                    "sat": _fmt(pharmacy.cutoff_sat_local),
                    "sun": _fmt(pharmacy.cutoff_sun_local),
                },
            },
        }
    )


@router.post(
    "/admin/pharmacies/{pharmacy_id}/toggle",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_toggle_pharmacy_active_path(
    pharmacy_id: int,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Toggle pharmacy.is_active (AJAX, matches /admin/pharmacies/{id}/toggle).
    """
    require_admin(current)

    pharmacy = session.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "Pharmacy not found"}
        )

    pharmacy.is_active = not pharmacy.is_active
    session.add(pharmacy)
    session.commit()

    return JSONResponse({"ok": True, "is_active": pharmacy.is_active})


@router.post(
    "/admin/pharmacies/{pharmacy_id}/assign",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_assign_driver_to_pharmacy_path(
    pharmacy_id: int,
    user_id: int = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Assign a user to a pharmacy (AJAX, matches /admin/pharmacies/{id}/assign).
    """
    require_admin(current)

    user = session.get(User, user_id)
    if not user:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "User not found"}
        )

    pharmacy = session.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "Pharmacy not found"}
        )

    existing = session.exec(
        select(UserPharmacyLink).where(
            UserPharmacyLink.user_id == user.id,
            UserPharmacyLink.pharmacy_id == pharmacy.id,
        )
    ).first()
    if existing:
        # Already assigned -> idempotent success
        return JSONResponse({"ok": True, "already_assigned": True})

    link = UserPharmacyLink(user_id=user.id, pharmacy_id=pharmacy.id)
    session.add(link)
    session.commit()

    return JSONResponse({"ok": True})


@router.post(
    "/admin/pharmacies/{pharmacy_id}/unassign",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_unassign_driver_from_pharmacy(
    pharmacy_id: int,
    user_id: int = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Unassign a user from a pharmacy (AJAX, matches /admin/pharmacies/{id}/unassign).
    """
    require_admin(current)

    pharmacy = session.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "Pharmacy not found"}
        )

    link = session.exec(
        select(UserPharmacyLink).where(
            UserPharmacyLink.user_id == user_id,
            UserPharmacyLink.pharmacy_id == pharmacy_id,
        )
    ).first()

    if link:
        session.delete(link)
        session.commit()

    # Even if nothing was deleted, treat as success (idempotent)
    return JSONResponse({"ok": True})


@router.post(
    "/admin/pharmacies/{pharmacy_id}/delete",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_delete_pharmacy(
    pharmacy_id: int,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Hard-delete a pharmacy (admin-only, AJAX).

    Safety rules:
    - You cannot delete a pharmacy that has pickups or user assignments.
    """
    require_admin(current)

    pharmacy = session.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "Pharmacy not found"}
        )

    # Check for related pickups
    pickups_count = session.exec(
        sa_select(func.count(Pickup.id)).where(Pickup.pharmacy_id == pharmacy_id)
    ).one()[0]

    # Check for user-pharmacy links
    links_count = session.exec(
        sa_select(func.count())
        .select_from(UserPharmacyLink)
        .where(UserPharmacyLink.pharmacy_id == pharmacy_id)
    ).one()[0]

    if pickups_count > 0 or links_count > 0:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "Cannot delete pharmacy with pickups or user assignments",
            },
        )

    session.delete(pharmacy)
    session.commit()

    return JSONResponse({"ok": True})


@router.post(
    "/admin/pharmacies/{pharmacy_id}/cutoffs",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_update_pharmacy_cutoffs(
    pharmacy_id: int,
    mon: str = Form(""),
    tue: str = Form(""),
    wed: str = Form(""),
    thu: str = Form(""),
    fri: str = Form(""),
    sat: str = Form(""),
    sun: str = Form(""),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Update weekly cutoff times for a pharmacy via AJAX.
    """
    require_admin(current)

    pharmacy = session.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "Pharmacy not found"},
        )

    # Parse incoming values; if any is invalid, return 400 JSON.
    try:
        mon_t = _parse_local_hhmm(mon)
        tue_t = _parse_local_hhmm(tue)
        wed_t = _parse_local_hhmm(wed)
        thu_t = _parse_local_hhmm(thu)
        fri_t = _parse_local_hhmm(fri)
        sat_t = _parse_local_hhmm(sat)
        sun_t = _parse_local_hhmm(sun)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": str(exc)},
        )

    # Persist to DB
    pharmacy.cutoff_mon_local = mon_t
    pharmacy.cutoff_tue_local = tue_t
    pharmacy.cutoff_wed_local = wed_t
    pharmacy.cutoff_thu_local = thu_t
    pharmacy.cutoff_fri_local = fri_t
    pharmacy.cutoff_sat_local = sat_t
    pharmacy.cutoff_sun_local = sun_t

    session.add(pharmacy)
    session.commit()

    def _fmt(val: Optional[time]) -> Optional[str]:
        return val.strftime("%H:%M") if val else None

    return JSONResponse(
        {
            "ok": True,
            "cutoffs": {
                "mon": _fmt(pharmacy.cutoff_mon_local),
                "tue": _fmt(pharmacy.cutoff_tue_local),
                "wed": _fmt(pharmacy.cutoff_wed_local),
                "thu": _fmt(pharmacy.cutoff_thu_local),
                "fri": _fmt(pharmacy.cutoff_fri_local),
                "sat": _fmt(pharmacy.cutoff_sat_local),
                "sun": _fmt(pharmacy.cutoff_sun_local),
            },
        }
    )


# -------------------------- Global settings --------------------------


@router.get("/admin/settings", include_in_schema=INCLUDE_IN_SCHEMA)
def admin_get_settings(
    request: Request,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Render admin settings page with global configuration.
    """
    require_admin(current)
    settings_obj = get_app_settings(session)

    return templates.TemplateResponse(
        "admin/settings.html",
        {
            "request": request,
            "user": current,
            "settings": settings_obj,
        },
    )


@router.post(
    "/admin/settings",
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_update_settings(
    allowed_pickups_per_day: int = Form(...),
    require_pickup_location_global: bool = Form(False),
    # Always treat missing as False and always update
    show_history_to_drivers: bool = Form(False),
    min_required_photos: int = Form(...),
    photo_source_mode: str = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Update global application settings from the admin form (non-AJAX).
    """
    require_admin(current)
    settings_obj = get_app_settings(session)

    settings_obj.allowed_pickups_per_day = max(1, allowed_pickups_per_day)
    settings_obj.require_pickup_location_global = bool(require_pickup_location_global)

    # Always update: unchecked checkbox -> False, checked -> True
    settings_obj.show_history_to_drivers = bool(show_history_to_drivers)

    settings_obj.min_required_photos = max(0, min_required_photos)

    if photo_source_mode not in ("camera_only", "camera_or_upload"):
        photo_source_mode = "camera_or_upload"
    settings_obj.photo_source_mode = photo_source_mode

    session.add(settings_obj)
    session.commit()

    return RedirectResponse(url="/admin/settings", status_code=303)
