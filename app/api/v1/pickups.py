"""
Pickup routes for up to 4 distinct photo slots (image1..image4).

Key features:
- Robust against empty uploads, supports partial slots.
- Enforces access control for pharmacies and photos.
- Limits daily pickups per (driver, pharmacy) using AppSettings.
- Enforces GPS requirement based on global + per-user settings.
- NEW: Tracks timing relative to pharmacy weekly cutoff (on_time / late / no_cutoff),
  storing a per-pickup UTC cutoff snapshot (cutoff_at_utc).
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

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
from app.db.models.user import User, UserRole

router = APIRouter()

# Local timezone used for weekly cutoff configuration
TZ_DE = ZoneInfo("Europe/Berlin")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _ensure_user_can_access_pharmacy(
    session: Session,
    user: User,
    pharmacy: Pharmacy,
) -> None:
    """
    Raise HTTP 403 if the given user is not allowed to access the given pharmacy.

    Rules:
      - Admins can access all pharmacies.
      - Drivers must have a UserPharmacyLink entry for this pharmacy.

    NOTE:
      History-only users are *not* handled here on purpose.
      For read-only access (e.g., photo viewing from history),
      they are allowed explicitly in the corresponding route.
    """
    # Admins: full access
    if user.role == UserRole.admin:
        return

    # All non-admins that reach here (drivers, etc.) must be linked.
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
    Return (start_utc, end_utc) for the current day in UTC.

    Used to enforce "N pickups per (driver, pharmacy) per day" limit.
    """
    now_utc = datetime.now(timezone.utc)
    start = datetime.combine(now_utc.date(), time.min).replace(tzinfo=timezone.utc)
    end = datetime.combine(now_utc.date(), time.max).replace(tzinfo=timezone.utc)
    return start, end


def _parse_float_or_none(val: Optional[str]) -> Optional[float]:
    """Convert string to float or return None on empty/invalid."""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _resolve_gps_requirement(user: User, settings: AppSettings) -> bool:
    """
    Decide whether a pickup must include GPS coordinates.

    Logic:
    - If user.require_pickup_location is not None → use it.
    - Otherwise → fall back to settings.require_pickup_location_global.
    """
    if user.require_pickup_location is not None:
        return bool(user.require_pickup_location)
    return bool(settings.require_pickup_location_global)


def _get_cutoff_for_pickup(
    pharmacy: Pharmacy,
    now_utc: datetime,
) -> Optional[datetime]:
    """
    For a given pharmacy and current UTC time, compute the *timestamp*
    of today's cutoff in UTC, based on weekly local cutoff config.

    Steps:
      - Convert now_utc to local DE time.
      - Take weekday (0 = Monday ... 6 = Sunday).
      - Read the corresponding cutoff_*_local from Pharmacy.
      - If None → no cutoff for today.
      - Else → build local datetime for today + that time, then convert to UTC.
    """
    # Convert current UTC timestamp to local DE time
    now_local = now_utc.astimezone(TZ_DE)
    weekday = now_local.weekday()  # 0 = Monday ... 6 = Sunday

    # Map weekday → pharmacy cutoff field
    cutoff_map = {
        0: pharmacy.cutoff_mon_local,
        1: pharmacy.cutoff_tue_local,
        2: pharmacy.cutoff_wed_local,
        3: pharmacy.cutoff_thu_local,
        4: pharmacy.cutoff_fri_local,
        5: pharmacy.cutoff_sat_local,
        6: pharmacy.cutoff_sun_local,
    }
    cutoff_local_time = cutoff_map.get(weekday)

    if cutoff_local_time is None:
        # No cutoff configured for this weekday
        return None

    # Build local datetime "today at cutoff time"
    cutoff_local_dt = now_local.replace(
        hour=cutoff_local_time.hour,
        minute=cutoff_local_time.minute,
        second=cutoff_local_time.second,
        microsecond=0,
    )

    # Convert local cutoff datetime back to UTC
    cutoff_utc = cutoff_local_dt.astimezone(timezone.utc)
    return cutoff_utc


def _compute_timing_status(
    now_utc: datetime,
    cutoff_at_utc: Optional[datetime],
) -> str:
    """
    Compute timing_status given a UTC timestamp and an optional cutoff timestamp.

    Returns:
        - "no_cutoff" if cutoff_at_utc is None
        - "late" if now_utc is strictly after cutoff_at_utc
        - "on_time" otherwise
    """
    if cutoff_at_utc is None:
        return "no_cutoff"

    if now_utc > cutoff_at_utc:
        return "late"
    return "on_time"


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

    History-only users do not normally reach this route (no Tasks UI),
    but if they try to open it manually, _ensure_user_can_access_pharmacy
    will still enforce driver/admin rules (no special access).
    """
    pharmacy = session.exec(
        select(Pharmacy).where(Pharmacy.public_id == pharmacy_pid)
    ).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    _ensure_user_can_access_pharmacy(session, user, pharmacy)

    require_location = _resolve_gps_requirement(user, settings)

    return templates.TemplateResponse(
        "pickup.html",
        {
            "request": request,
            "pharmacy": pharmacy,
            "user": user,
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
    comment: Optional[str] = Form(None),
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
    - NEW: Stores weekly-based cutoff snapshot (cutoff_at_utc) and timing_status
      (on_time / no_cutoff / late) for each pickup.
    """
    # Resolve pharmacy by public_id early (for re-render)
    pharmacy = session.exec(
        select(Pharmacy).where(Pharmacy.public_id == pharmacy_pid)
    ).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    _ensure_user_can_access_pharmacy(session, user, pharmacy)

    require_location = _resolve_gps_requirement(user, settings)

    # Collect provided files into a list for easier processing
    provided: List[Tuple[int, UploadFile]] = []
    if image1 is not None:
        provided.append((1, image1))
    if image2 is not None:
        provided.append((2, image2))
    if image3 is not None:
        provided.append((3, image3))
    if image4 is not None:
        provided.append((4, image4))

    # Filter out "empty" filenames (browsers may send empty file objects)
    provided = [(idx, uf) for idx, uf in provided if uf.filename]

    # Enforce minimal number of photos
    min_photos = max(0, settings.min_required_photos or 0)
    if len(provided) < min_photos:
        return templates.TemplateResponse(
            "pickup.html",
            {
                "request": request,
                "pharmacy": pharmacy,
                "user": user,
                "error": f"At least {min_photos} photo(s) are required.",
                "require_location": require_location,
                "photo_source_mode": settings.photo_source_mode,
                "min_required_photos": settings.min_required_photos,
            },
            status_code=422,
        )

    latitude = _parse_float_or_none(lat)
    longitude = _parse_float_or_none(lon)
    comment_clean = comment.strip() if comment else None

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
        Pickup.user_id == user.id,
        Pickup.pharmacy_id == pharmacy.id,
        Pickup.created_at >= start_utc,
        Pickup.created_at <= end_utc,
    )

    # Get scalar integer instead of Row/tuple
    current_count = session.exec(count_stmt).scalar_one()

    if current_count >= limit:
        return templates.TemplateResponse(
            "pickup.html",
            {
                "request": request,
                "pharmacy": pharmacy,
                "user": user,
                "error": (
                    "Daily pickup limit reached for this pharmacy and driver. "
                    f"Maximum {limit} pickups per day for this combination."
                ),
                "require_location": require_location,
                "photo_source_mode": settings.photo_source_mode,
                "min_required_photos": settings.min_required_photos,
            },
            status_code=429,
        )

    # ------------------------------------------------------------------
    # NEW: compute timing info relative to *today's* cutoff timestamp
    #      based on weekly local config in pharmacy.
    # ------------------------------------------------------------------
    now_utc = datetime.now(timezone.utc)

    # Snapshot of *today's* cutoff timestamp in UTC for this pickup
    cutoff_at_utc = _get_cutoff_for_pickup(pharmacy, now_utc)
    timing_status = _compute_timing_status(now_utc, cutoff_at_utc)

    # Create the pickup entry (internal pharmacy.id is used here)
    pickup = Pickup(
        user_id=user.id,
        pharmacy_id=pharmacy.id,
        latitude=latitude,
        longitude=longitude,
        comment=comment_clean,
        status="done",
        created_at=now_utc,
        cutoff_at_utc=cutoff_at_utc,
        timing_status=timing_status,
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

        photo = PickupPhoto(
            pickup_id=pickup.id,
            idx=idx,
            image_bytes=image_bytes,
            image_content_type=content_type,
            image_filename=uf.filename,
        )
        session.add(photo)
        saved_count += 1

    if saved_count == 0 and min_photos > 0:
        # No valid photos were saved but some were required
        session.rollback()
        return templates.TemplateResponse(
            "pickup.html",
            {
                "request": request,
                "pharmacy": pharmacy,
                "user": user,
                "error": "None of the uploaded photos could be processed.",
                "require_location": require_location,
                "photo_source_mode": settings.photo_source_mode,
                "min_required_photos": settings.min_required_photos,
            },
            status_code=422,
        )

    session.commit()

    # Re-render the same template with a success message
    return templates.TemplateResponse(
        "pickup.html",
        {
            "request": request,
            "pharmacy": pharmacy,
            "user": user,
            "message": (
                f"Pickup saved with {saved_count} photo(s). "
                f"Used {current_count + 1}/{limit} pickups for today "
                f"for pharmacy “{pharmacy.name}”. "
                f"Timing status: {timing_status}."
            ),
            "require_location": require_location,
            "photo_source_mode": settings.photo_source_mode,
            "min_required_photos": settings.min_required_photos,
        },
    )


# ---------------------------------------------------------------------
# GET: individual photo by public_id (secure URL)
# ---------------------------------------------------------------------
@router.get("/pickup/photos/{photo_id}")
def get_pickup_photo(
    photo_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Return a single pickup photo by its public_id.

    Security layers:
      - URL is non-guessable (public_id, not sequential).
      - Access rules:
          * Admins: may view any photo.
          * History-only users: may view any photo (read-only reporting role).
          * Drivers: must be linked to the pharmacy via UserPharmacyLink.
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

    # Access control:
    # - Admin: always allowed
    # - History-only: always allowed (read-only reporting role)
    # - Drivers/others: must satisfy _ensure_user_can_access_pharmacy
    if user.role not in {UserRole.admin, UserRole.history}:
        _ensure_user_can_access_pharmacy(session, user, pharmacy)

    return Response(
        content=photo.image_bytes,
        media_type=photo.image_content_type or "image/jpeg",
    )
