# app/api/v1/admin.py
"""
Admin endpoints:

- User management (create, toggle active, change password, per-user GPS flag).
- Region management (create, toggle active).
- Pharmacy management (create, toggle active, assign drivers).
- Diagnostics (duplicate name preview).
- Global AppSettings edit (pickup limits, GPS behaviour, photo rules).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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

    # ---------- Counts (через sa_select + func.count) ----------
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

    # ---------- Списки сущностей (через sm_select → ORM-модели) ----------
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
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_create_user(
    login: str = Form(...),
    password: str = Form(...),
    role: str = Form("driver"),
    require_pickup_location: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Create a new user (admin-only).

    Accepts login/password/role and an optional per-user GPS requirement flag.
    """
    require_admin(current)

    exists = session.exec(select(User).where(User.login == login)).first()
    if exists:
        raise HTTPException(status_code=400, detail="Login already exists")

    try:
        user_role = UserRole(role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role")

    gps_flag: Optional[bool]
    if require_pickup_location == "inherit":
        gps_flag = None
    elif require_pickup_location == "require":
        gps_flag = True
    elif require_pickup_location == "no":
        gps_flag = False
    else:
        gps_flag = None

    user = User(
        login=login,
        password_hash=hash_password(password),
        role=user_role,
        is_active=True,
        require_pickup_location=gps_flag,
    )
    session.add(user)
    session.commit()

    return RedirectResponse(url="/admin", status_code=303)


@router.post(
    "/admin/users/toggle-active",
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_toggle_user_active(
    user_id: int = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Toggle user.is_active flag (admin-only).
    """
    require_admin(current)
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    u.is_active = not u.is_active
    session.add(u)
    session.commit()

    return RedirectResponse(url="/admin", status_code=303)


@router.post(
    "/admin/users/change-password",
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_change_user_password(
    user_id: int = Form(...),
    new_password: str = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Change password for a given user (admin-only).
    """
    require_admin(current)
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    u.password_hash = hash_password(new_password)
    session.add(u)
    session.commit()

    return RedirectResponse(url="/admin", status_code=303)


@router.post(
    "/admin/users/set-gps",
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_set_user_gps_mode(
    user_id: int = Form(...),
    gps_mode: str = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Update per-user GPS requirement flag.

    gps_mode can be:
      - "inherit" -> require_pickup_location = None
      - "require" -> require_pickup_location = True
      - "no"      -> require_pickup_location = False
    """
    require_admin(current)
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    if gps_mode == "inherit":
        u.require_pickup_location = None
    elif gps_mode == "require":
        u.require_pickup_location = True
    elif gps_mode == "no":
        u.require_pickup_location = False
    else:
        raise HTTPException(status_code=400, detail="Invalid GPS mode")

    session.add(u)
    session.commit()

    return RedirectResponse(url="/admin", status_code=303)


# ------------------------------ Regions ------------------------------


@router.post(
    "/admin/regions/create",
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_create_region(
    name: str = Form(...),
    is_active: bool = Form(True),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Create a new region (admin-only).
    """
    require_admin(current)

    existing = session.exec(select(Region).where(Region.name == name)).first()
    if existing:
        raise HTTPException(
            status_code=400, detail="Region with this name already exists"
        )

    region = Region(name=name, is_active=is_active)
    session.add(region)
    session.commit()

    return RedirectResponse(url="/admin", status_code=303)


@router.post(
    "/admin/regions/toggle-active",
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_toggle_region_active(
    region_id: int = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Toggle region.is_active (admin-only).
    """
    require_admin(current)
    region = session.get(Region, region_id)
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")

    region.is_active = not region.is_active
    session.add(region)
    session.commit()

    return RedirectResponse(url="/admin", status_code=303)


# ------------------------------ Pharmacies ------------------------------


@router.post(
    "/admin/pharmacies/create",
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_create_pharmacy(
    name: str = Form(...),
    region_id: int = Form(...),
    address: str = Form(""),
    is_active: bool = Form(True),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Create a new pharmacy (admin-only).
    """
    require_admin(current)

    region = session.get(Region, region_id)
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")

    existing = session.exec(
        select(Pharmacy).where(Pharmacy.name == name, Pharmacy.region_id == region_id)
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Pharmacy with this name already exists in this region",
        )

    pharmacy = Pharmacy(
        name=name, region_id=region_id, address=address, is_active=is_active
    )
    session.add(pharmacy)
    session.commit()

    return RedirectResponse(url="/admin", status_code=303)


@router.post(
    "/admin/pharmacies/toggle-active",
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_toggle_pharmacy_active(
    pharmacy_id: int = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Toggle pharmacy.is_active (admin-only).
    """
    require_admin(current)
    pharmacy = session.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    pharmacy.is_active = not pharmacy.is_active
    session.add(pharmacy)
    session.commit()

    return RedirectResponse(url="/admin", status_code=303)


@router.post(
    "/admin/pharmacies/assign-driver",
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_assign_driver_to_pharmacy(
    user_id: int = Form(...),
    pharmacy_id: int = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Assign a driver to a pharmacy (admin-only).
    """
    require_admin(current)

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    pharmacy = session.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    existing = session.exec(
        select(UserPharmacyLink).where(
            UserPharmacyLink.user_id == user.id,
            UserPharmacyLink.pharmacy_id == pharmacy.id,
        )
    ).first()
    if existing:
        # Already assigned -> no-op
        return RedirectResponse(url="/admin", status_code=303)

    link = UserPharmacyLink(user_id=user.id, pharmacy_id=pharmacy.id)
    session.add(link)
    session.commit()

    return RedirectResponse(url="/admin", status_code=303)


@router.post(
    "/admin/pharmacies/{pharmacy_id}/assign",
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_assign_driver_to_pharmacy_path(
    pharmacy_id: int,
    user_id: int = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Assign a user to a pharmacy (matches form: /admin/pharmacies/{id}/assign).
    """
    require_admin(current)

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    pharmacy = session.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    existing = session.exec(
        select(UserPharmacyLink).where(
            UserPharmacyLink.user_id == user.id,
            UserPharmacyLink.pharmacy_id == pharmacy.id,
        )
    ).first()
    if existing:
        # Already assigned -> no-op
        return RedirectResponse(url="/admin", status_code=303)

    link = UserPharmacyLink(user_id=user.id, pharmacy_id=pharmacy.id)
    session.add(link)
    session.commit()

    return RedirectResponse(url="/admin", status_code=303)


@router.post(
    "/admin/pharmacies/{pharmacy_id}/unassign",
    response_class=RedirectResponse,
    include_in_schema=INCLUDE_IN_SCHEMA,
)
def admin_unassign_driver_from_pharmacy(
    pharmacy_id: int,
    user_id: int = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Unassign a user from a pharmacy (matches form: /admin/pharmacies/{id}/unassign).
    """
    require_admin(current)

    pharmacy = session.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    link = session.exec(
        select(UserPharmacyLink).where(
            UserPharmacyLink.user_id == user_id,
            UserPharmacyLink.pharmacy_id == pharmacy_id,
        )
    ).first()

    if link:
        session.delete(link)
        session.commit()

    # Even if nothing was deleted, just go back to admin
    return RedirectResponse(url="/admin", status_code=303)


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
    # FIX: always treat missing as False and always update
    show_history_to_drivers: bool = Form(False),
    min_required_photos: int = Form(...),
    photo_source_mode: str = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Update global application settings from the admin form.
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
