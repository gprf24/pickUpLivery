# app/api/v1/pickups.py
"""
Pickup routes for up to 4 distinct photo slots (image1..image4).

Key features:
- Robust against empty uploads, supports partial slots.
- Enforces access control for pharmacies and photos.
- Limits daily pickups per (driver, pharmacy) using AppSettings.
- Enforces GPS requirement based on global + per-user settings.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlmodel import Session, select

from app.core.deps import get_app_settings, get_current_user, get_session, templates
from app.core.image_utils import compress_image
from app.db.models.links import UserPharmacyLink
from app.db.models.pharmacy import Pharmacy
from app.db.models.pickup import Pickup
from app.db.models.pickup_photo import PickupPhoto
from app.db.models.settings import AppSettings
from app.db.models.user import User

router = APIRouter()


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _parse_float_or_none(s: Optional[str]) -> Optional[float]:
    """Convert string to float or None."""
    if s in (None, "", "null", "undefined"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _ensure_user_can_access_pharmacy(
    session: Session,
    user: User,
    pharmacy: Pharmacy,
) -> None:
    """
    Ensure that the given user is allowed to access this pharmacy.

    - Admins can access all pharmacies.
    - Drivers must be linked via UserPharmacyLink.
    """
    if getattr(user, "role", None) == "admin":
        return

    link_exists = (
        session.exec(
            select(UserPharmacyLink).where(
                UserPharmacyLink.user_id == user.id,
                UserPharmacyLink.pharmacy_id == pharmacy.id,
            )
        ).first()
        is not None
    )
    if not link_exists:
        # You could also return 404 to hide pharmacy existence.
        raise HTTPException(
            status_code=403,
            detail="Not allowed to access this pharmacy.",
        )


def _get_utc_today_bounds() -> Tuple[datetime, datetime]:
    """
    Return the UTC datetime range [start_of_today, end_of_today].

    This is used to enforce the "N pickups per (driver, pharmacy) per day" limit.
    """
    today_utc = datetime.now(timezone.utc).date()
    start = datetime.combine(today_utc, time.min, tzinfo=timezone.utc)
    end = datetime.combine(today_utc, time.max, tzinfo=timezone.utc)
    return start, end


def _resolve_require_location(user: User, settings: AppSettings) -> bool:
    """
    Combine per-user and global GPS requirement:

    - If user.require_pickup_location is not None → use it.
    - Otherwise → fall back to settings.require_pickup_location_global.
    """
    if user.require_pickup_location is not None:
        return bool(user.require_pickup_location)
    return bool(settings.require_pickup_location_global)


# ---------------------------------------------------------------------
# GET: pickup form
# ---------------------------------------------------------------------
@router.get("/pickup/{pharmacy_pid}", response_class=HTMLResponse)
def pickup_form(
    request: Request,
    pharmacy_pid: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: AppSettings = Depends(get_app_settings),
):
    """
    Render the pickup form for a single pharmacy.

    Access is restricted:
      - Admin: any pharmacy.
      - Driver: only pharmacies assigned to this user.
    """
    pharmacy = session.exec(
        select(Pharmacy).where(Pharmacy.public_id == pharmacy_pid)
    ).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    _ensure_user_can_access_pharmacy(session, user, pharmacy)

    require_location = _resolve_require_location(user, settings)

    return templates.TemplateResponse(
        "pickup.html",
        {
            "request": request,
            "pharmacy": pharmacy,
            "user": user,
            "error": None,
            "require_location": require_location,
            "photo_source_mode": settings.photo_source_mode,
            "min_required_photos": settings.min_required_photos,
        },
    )


# ---------------------------------------------------------------------
# POST: create pickup
# ---------------------------------------------------------------------
@router.post("/pickup/{pharmacy_pid}", response_class=HTMLResponse)
async def create_pickup(
    request: Request,
    pharmacy_pid: str,
    image1: Optional[UploadFile] = File(None),
    image2: Optional[UploadFile] = File(None),
    image3: Optional[UploadFile] = File(None),
    image4: Optional[UploadFile] = File(None),
    lat: Optional[str] = Form(None),
    lon: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: AppSettings = Depends(get_app_settings),
):
    """
    Create a pickup entry and attach up to 4 photos.

    Behaviour:
    - Only non-empty files are processed.
    - Enforces minimal number of photos via AppSettings.min_required_photos.
    - Enforces GPS requirement via per-user + global settings.
    - Enforces daily pickup limit via AppSettings.allowed_pickups_per_day
      per (driver, pharmacy).
    """
    # Resolve pharmacy by public_id early (for re-render)
    pharmacy = session.exec(
        select(Pharmacy).where(Pharmacy.public_id == pharmacy_pid)
    ).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    _ensure_user_can_access_pharmacy(session, user, pharmacy)

    require_location = _resolve_require_location(user, settings)

    # Collect only files that actually have content (filename not empty)
    provided: List[tuple[int, UploadFile]] = []
    for idx, uf in enumerate((image1, image2, image3, image4), start=1):
        if uf and uf.filename:
            provided.append((idx, uf))

    # Enforce minimal number of photos
    min_photos = max(0, settings.min_required_photos or 0)
    if len(provided) < max(1, min_photos):
        # Render form again with a user-friendly error
        return templates.TemplateResponse(
            "pickup.html",
            {
                "request": request,
                "pharmacy": pharmacy,
                "user": user,
                "error": f"At least {max(1, min_photos)} photo(s) are required.",
                "require_location": require_location,
                "photo_source_mode": settings.photo_source_mode,
                "min_required_photos": settings.min_required_photos,
            },
            status_code=422,
        )

    latitude = _parse_float_or_none(lat)
    longitude = _parse_float_or_none(lon)

    # Enforce location requirement if flag is enabled
    if require_location and (latitude is None or longitude is None):
        return templates.TemplateResponse(
            "pickup.html",
            {
                "request": request,
                "pharmacy": pharmacy,
                "user": user,
                "error": "Location (latitude and longitude) is required for this pickup.",
                "require_location": require_location,
                "photo_source_mode": settings.photo_source_mode,
                "min_required_photos": settings.min_required_photos,
            },
            status_code=422,
        )

    # Enforce daily pickup limit per (driver, pharmacy)
    limit = max(1, settings.allowed_pickups_per_day or 1)
    start_utc, end_utc = _get_utc_today_bounds()

    count_stmt = sa_select(func.count(Pickup.id)).where(
        Pickup.pharmacy_id == pharmacy.id,
        Pickup.user_id == user.id,
        Pickup.created_at >= start_utc,
        Pickup.created_at <= end_utc,
    )
    existing_count = session.exec(count_stmt).scalar_one() or 0

    if existing_count >= limit:
        raise HTTPException(
            status_code=429,
            detail=(
                "Daily pickup limit reached for this pharmacy and driver. "
                f"Maximum {limit} pickups per day for this combination."
            ),
        )

    # Create the pickup entry first (note: internal pharmacy.id is used here)
    pickup = Pickup(
        user_id=user.id,
        pharmacy_id=pharmacy.id,
        latitude=latitude,
        longitude=longitude,
        status="done",
    )
    session.add(pickup)
    session.flush()  # pickup.id is now available

    saved_count = 0

    # Save only non-empty files, compressed via Pillow
    for idx, uf in provided:
        # Ensure the underlying file pointer is at the beginning
        uf.file.seek(0, 2)  # move to end of file
        size = uf.file.tell()
        uf.file.seek(0)  # reset back to start

        if size == 0:
            # Some devices may send an empty placeholder file — skip those.
            continue

        try:
            image_bytes, content_type = compress_image(uf)
        except Exception:
            # If compression fails, skip this file instead of breaking the whole pickup.
            continue

        session.add(
            PickupPhoto(
                pickup_id=pickup.id,
                idx=idx,
                image_bytes=image_bytes,
                image_content_type=content_type,
                image_filename=uf.filename,
            )
        )
        saved_count += 1

    if saved_count == 0:
        session.rollback()
        return templates.TemplateResponse(
            "pickup.html",
            {
                "request": request,
                "pharmacy": pharmacy,
                "user": user,
                "error": "All uploaded photos were empty or invalid.",
                "require_location": require_location,
                "photo_source_mode": settings.photo_source_mode,
                "min_required_photos": settings.min_required_photos,
            },
            status_code=422,
        )

    session.commit()

    return templates.TemplateResponse(
        "pickup.html",
        {
            "request": request,
            "pharmacy": pharmacy,
            "user": user,
            "message": (
                f"Pickup saved with {saved_count} photo(s). "
                f"Used {existing_count + 1}/{limit} pickups for today "
                "for this pharmacy & driver."
            ),
            "require_location": require_location,
            "photo_source_mode": settings.photo_source_mode,
            "min_required_photos": settings.min_required_photos,
        },
    )


# ---------------------------------------------------------------------
# GET: photo by public_id
# ---------------------------------------------------------------------
@router.get("/photos/{photo_id}")
def get_pickup_photo(
    photo_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Return a single pickup photo by its public_id.

    Security layers:
      - URL is non-guessable (public_id, not sequential).
      - We additionally enforce that the current user is allowed to access
        the pharmacy associated with this pickup.
    """
    photo = session.exec(
        select(PickupPhoto).where(PickupPhoto.public_id == photo_id)
    ).first()

    if not photo or not photo.image_bytes:
        raise HTTPException(status_code=404, detail="Photo not found")

    pickup = session.get(Pickup, photo.pickup_id)
    if not pickup:
        raise HTTPException(status_code=404, detail="Pickup not found for this photo")

    pharmacy = session.get(Pharmacy, pickup.pharmacy_id)
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found for this photo")

    _ensure_user_can_access_pharmacy(session, user, pharmacy)

    return Response(
        content=photo.image_bytes,
        media_type=photo.image_content_type or "image/jpeg",
    )
