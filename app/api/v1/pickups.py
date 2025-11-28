# app/api/v1/pickups.py
"""
Pickup routes for 4 distinct photo slots (image1..image4).
Now robust against empty uploads, supports partial slots,
enforces access control for pharmacies and photos, and limits
daily pickups per (driver, pharmacy) to mitigate abuse.
"""

from __future__ import annotations

import os
from datetime import datetime, time, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlmodel import Session, select

from app.core.deps import get_current_user, get_session, templates
from app.core.image_utils import compress_image
from app.db.models.links import UserPharmacyLink
from app.db.models.pharmacy import Pharmacy
from app.db.models.pickup import Pickup
from app.db.models.pickup_photo import PickupPhoto
from app.db.models.user import User

router = APIRouter()


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
    # Admins have full access
    if getattr(user, "role", None) == "admin":
        return

    # For non-admins, require an explicit user-pharmacy link
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
        # You can also return 404 if you want to hide the existence of this pharmacy.
        raise HTTPException(
            status_code=403, detail="Not allowed to access this pharmacy."
        )


def _get_utc_today_bounds() -> tuple[datetime, datetime]:
    """
    Return the UTC datetime range [start_of_today, end_of_today].

    This is used to enforce the "N pickups per (driver, pharmacy) per day" limit.
    """
    today_utc = datetime.now(timezone.utc).date()
    start = datetime.combine(today_utc, time.min, tzinfo=timezone.utc)
    end = datetime.combine(today_utc, time.max, tzinfo=timezone.utc)
    return start, end


def _get_daily_pickup_limit() -> int:
    """
    Read the daily pickup limit from environment.

    Env var: PICKUP_DAILY_LIMIT_PER_DRIVER_PHARMACY
    - defaults to 3 if unset or invalid
    - minimum enforced value is 1
    """
    raw = os.getenv("PICKUP_DAILY_LIMIT_PER_DRIVER_PHARMACY", "3")
    try:
        value = int(raw)
    except ValueError:
        value = 3
    if value < 1:
        value = 1
    return value


@router.get("/pickup/{pharmacy_pid}", response_class=HTMLResponse)
def pickup_form(
    request: Request,
    pharmacy_pid: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Render the pickup form for a single pharmacy.

    Access is restricted:
      - Admin: any pharmacy.
      - Driver: only pharmacies assigned to this user.

    The pharmacy is resolved by its public_id (pharmacy_pid), not by
    the internal numeric primary key.
    """
    pharmacy = session.exec(
        select(Pharmacy).where(Pharmacy.public_id == pharmacy_pid)
    ).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    # Enforce access control for this pharmacy
    _ensure_user_can_access_pharmacy(session, user, pharmacy)

    return templates.TemplateResponse(
        "pickup.html",
        {"request": request, "pharmacy": pharmacy, "user": user, "error": None},
    )


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
):
    """
    Create a pickup entry and attach up to 4 photos.

    - Only non-empty files are processed.
    - At least one valid (non-empty) photo is required.
    - Access to the pharmacy is enforced (admin or user-pharmacy link).
    - A daily pickup limit per (driver, pharmacy) is enforced to mitigate abuse.
    """
    # Collect only files that actually have content (filename not empty)
    provided: List[tuple[int, UploadFile]] = []
    for idx, uf in enumerate((image1, image2, image3, image4), start=1):
        if uf and uf.filename:
            provided.append((idx, uf))

    if len(provided) == 0:
        raise HTTPException(status_code=422, detail="At least one photo is required.")

    latitude = _parse_float_or_none(lat)
    longitude = _parse_float_or_none(lon)

    # Resolve pharmacy by public_id
    pharmacy = session.exec(
        select(Pharmacy).where(Pharmacy.public_id == pharmacy_pid)
    ).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    # Enforce access control for this pharmacy
    _ensure_user_can_access_pharmacy(session, user, pharmacy)

    # Enforce daily pickup limit per (driver, pharmacy)
    limit = _get_daily_pickup_limit()
    start_utc, end_utc = _get_utc_today_bounds()

    # Count how many pickups already exist for this driver+pharmacy today
    count_stmt = sa_select(func.count(Pickup.id)).where(
        Pickup.pharmacy_id == pharmacy.id,
        Pickup.user_id == user.id,
        Pickup.created_at >= start_utc,
        Pickup.created_at <= end_utc,
    )
    existing_count = session.exec(count_stmt).scalar_one() or 0

    if existing_count >= limit:
        # Too many pickups already recorded today for this driver+pharmacy pair.
        # 429 Too Many Requests is semantically appropriate here.
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
        # and check if the file has any data at all.
        uf.file.seek(0, 2)  # move to end of file
        size = uf.file.tell()
        uf.file.seek(0)  # reset back to start

        if size == 0:
            # Some devices may send an empty placeholder file — skip those.
            continue

        try:
            # Compress the image regardless of original format
            image_bytes, content_type = compress_image(uf)
        except Exception:
            # If compression fails, we skip this file instead of breaking the whole pickup.
            # You could also log the error or return 400 if you want stricter behavior.
            continue

        session.add(
            PickupPhoto(
                pickup_id=pickup.id,
                idx=idx,
                image_bytes=image_bytes,
                image_content_type=content_type,
                image_filename=uf.filename,
                # public_id is generated automatically in the model (default_factory)
            )
        )
        saved_count += 1

    if saved_count == 0:
        # If all files were empty/invalid, rollback the pickup and report an error.
        session.rollback()
        raise HTTPException(
            status_code=422, detail="All uploaded photos were empty or invalid."
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
                f"Used {existing_count + 1}/{limit} pickups for today for this pharmacy & driver."
            ),
        },
    )


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

    # Resolve the pickup and its pharmacy to enforce access control
    pickup = session.get(Pickup, photo.pickup_id)
    if not pickup:
        raise HTTPException(status_code=404, detail="Pickup not found for this photo")

    pharmacy = session.get(Pharmacy, pickup.pharmacy_id)
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found for this photo")

    # Enforce that the current user can access this pharmacy
    _ensure_user_can_access_pharmacy(session, user, pharmacy)

    return Response(
        content=photo.image_bytes,
        media_type=photo.image_content_type or "image/jpeg",
    )
