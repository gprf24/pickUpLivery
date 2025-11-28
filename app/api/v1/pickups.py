# app/api/v1/pickups.py
"""
Pickup routes for 4 distinct photo slots (image1..image4).
Now robust against empty uploads and supports partial slots.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlmodel import Session, select

from app.core.deps import get_current_user, get_session, templates
from app.core.image_utils import compress_image  # <-- NEW: image compression helper
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


@router.get("/pickup/{pharmacy_id}", response_class=HTMLResponse)
def pickup_form(
    request: Request,
    pharmacy_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    pharmacy = session.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    return templates.TemplateResponse(
        "pickup.html",
        {"request": request, "pharmacy": pharmacy, "user": user, "error": None},
    )


@router.post("/pickup/{pharmacy_id}", response_class=HTMLResponse)
async def create_pickup(
    request: Request,
    pharmacy_id: int,
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
    Accept up to 4 separate image slots. Only non-empty files are processed.
    Require at least one valid file.
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

    pharmacy = session.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    # Create the pickup entry first
    pickup = Pickup(
        user_id=user.id,
        pharmacy_id=pharmacy_id,
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
        except Exception as exc:
            # If compression fails, we skip this file instead of breaking the whole pickup
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
            "message": f"Pickup saved with {saved_count} photo(s).",
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

    This avoids exposing predictable /pickup/{pickup_id}/photos/{idx} URLs
    that could be brute-forced across regions/pharmacies.
    """
    photo = session.exec(
        select(PickupPhoto).where(PickupPhoto.public_id == photo_id)
    ).first()

    if not photo or not photo.image_bytes:
        raise HTTPException(status_code=404, detail="Photo not found")

    # TODO: Optionally enforce that the current user is allowed to see
    #       this pickup (e.g., same region / same pharmacy group).

    return Response(
        content=photo.image_bytes,
        media_type=photo.image_content_type or "image/jpeg",
    )
