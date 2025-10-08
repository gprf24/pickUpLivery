# app/api/v1/admin.py
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlmodel import Session, select

from app.core.deps import get_current_user, get_session, require_admin
from app.core.security import hash_password
from app.db.models.links import UserPharmacyLink
from app.db.models.pharmacy import Pharmacy
from app.db.models.region import Region
from app.db.models.user import User, UserRole

router = APIRouter()

# ---------------------------- USERS ----------------------------


@router.post("/admin/users/create", response_class=RedirectResponse)
def admin_create_user(
    login: str = Form(...),
    password: str = Form(...),
    role: Optional[str] = Form("driver"),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Create a new user (admin-only).
    Accepts login/password/role; role defaults to 'driver' if missing/invalid.
    """
    require_admin(current)

    exists = session.exec(select(User).where(User.login == login)).first()
    if exists:
        raise HTTPException(status_code=400, detail="Login already exists")

    try:
        user_role = UserRole(role)
    except Exception:
        user_role = UserRole.driver

    u = User(login=login.strip(), password_hash=hash_password(password), role=user_role)
    session.add(u)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/users/{user_id}/password", response_class=RedirectResponse)
def admin_change_user_password(
    user_id: int,
    new_password: str = Form(..., min_length=6),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Admin sets a new password for a user.
    """
    require_admin(current)
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.password_hash = hash_password(new_password)
    session.add(u)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/users/{user_id}/toggle", response_class=RedirectResponse)
def admin_toggle_user_active(
    user_id: int,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Toggle user's active flag.
    """
    require_admin(current)
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.is_active = not u.is_active
    session.add(u)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


# ---------------------------- REGIONS ----------------------------


@router.post("/admin/regions/create", response_class=RedirectResponse)
def admin_create_region(
    name: str = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Create a region; unique by name (case-insensitive check at app level).
    """
    require_admin(current)
    exists = session.exec(select(Region).where(Region.name.ilike(name))).first()
    if exists:
        raise HTTPException(status_code=400, detail="Region already exists")
    r = Region(name=name.strip())
    session.add(r)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/regions/{region_id}/toggle", response_class=RedirectResponse)
def admin_toggle_region(
    region_id: int,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Toggle region active flag.
    """
    require_admin(current)
    r = session.get(Region, region_id)
    if not r:
        raise HTTPException(status_code=404, detail="Region not found")
    # Ensure column exists (we added it via migrations)
    if not hasattr(r, "is_active"):
        raise HTTPException(status_code=500, detail="Region.is_active column missing")
    r.is_active = not r.is_active
    session.add(r)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


# ---------------------------- PHARMACIES ----------------------------


@router.post("/admin/pharmacies/create", response_class=RedirectResponse)
def admin_create_pharmacy(
    name: str = Form(...),
    region_id: int = Form(...),
    address: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Create a pharmacy; unique per (region_id, name).
    """
    require_admin(current)

    exists = session.exec(
        select(Pharmacy).where(
            Pharmacy.region_id == region_id, Pharmacy.name.ilike(name)
        )
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Pharmacy already exists in region")

    p = Pharmacy(name=name.strip(), region_id=region_id, address=address)
    session.add(p)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/pharmacies/{pharmacy_id}/toggle", response_class=RedirectResponse)
def admin_toggle_pharmacy(
    pharmacy_id: int,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Toggle pharmacy active flag.
    """
    require_admin(current)
    p = session.get(Pharmacy, pharmacy_id)
    if not p:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    if not hasattr(p, "is_active"):
        raise HTTPException(status_code=500, detail="Pharmacy.is_active column missing")
    p.is_active = not p.is_active
    session.add(p)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


# ----------------------- PHARMACY <-> USER LINKS -----------------------


@router.post("/admin/pharmacies/{pharmacy_id}/assign", response_class=RedirectResponse)
def admin_assign_user_to_pharmacy(
    pharmacy_id: int,
    user_id: int = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Assign a user to a pharmacy (idempotent).
    """
    require_admin(current)

    if not session.get(Pharmacy, pharmacy_id):
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    if not session.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")

    link = session.get(UserPharmacyLink, (user_id, pharmacy_id))
    if not link:
        link = UserPharmacyLink(user_id=user_id, pharmacy_id=pharmacy_id)
        session.add(link)
        session.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post(
    "/admin/pharmacies/{pharmacy_id}/unassign", response_class=RedirectResponse
)
def admin_unassign_user_from_pharmacy(
    pharmacy_id: int,
    user_id: int = Form(...),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Remove user from pharmacy assignments (idempotent).
    """
    require_admin(current)
    link = session.get(UserPharmacyLink, (user_id, pharmacy_id))
    if link:
        session.delete(link)
        session.commit()
    return RedirectResponse(url="/admin", status_code=303)


# ----------------------------- Diagnostics -----------------------------


@router.get("/admin/dedup-preview")
def admin_dedup_preview(
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """
    Preview duplicate regions & pharmacies (read-only).
    """
    require_admin(current)

    dup_regions = session.exec(
        text(
            """
            SELECT LOWER(TRIM(name)) AS normalized_name, COUNT(*) AS count
            FROM "PP_region"
            GROUP BY LOWER(TRIM(name))
            HAVING COUNT(*) > 1
            ORDER BY count DESC
        """
        )
    ).all()
    dup_pharmacies = session.exec(
        text(
            """
            SELECT region_id, LOWER(TRIM(name)) AS normalized_name, COUNT(*) AS count
            FROM "PP_pharmacy"
            GROUP BY region_id, LOWER(TRIM(name))
            HAVING COUNT(*) > 1
            ORDER BY count DESC
        """
        )
    ).all()

    return {
        "dup_regions": [{"name": r[0], "count": r[1]} for r in dup_regions],
        "dup_pharmacies": [
            {"region_id": r[0], "name": r[1], "count": r[2]} for r in dup_pharmacies
        ],
        "note": "Preview only. No changes are made to the database.",
    }


# -------------------test
# @router.get("/admin/my-links")
# def admin_my_links(
#     session: Session = Depends(get_session),
#     current: User = Depends(get_current_user),
# ):
#     """
#     Debug: which pharmacy_ids are assigned to the *current* user.
#     """
#     rows = session.exec(
#         sm_select(UserPharmacyLink.pharmacy_id).where(
#             UserPharmacyLink.user_id == current.id
#         )
#     ).all()
#     return {"user_id": current.id, "pharmacy_ids": [pid for (pid,) in rows]}
