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

    pickup = Pickup(
        user_id=user.id,
        pharmacy_id=pharmacy_id,
        latitude=latitude,
        longitude=longitude,
        status="done",
    )
    session.add(pickup)
    session.flush()  # pickup.id ready

    # Save only non-empty files
    for idx, uf in provided:
        data = await uf.read()
        if not data:
            continue  # skip zero-byte (some phones send empty placeholder)
        session.add(
            PickupPhoto(
                pickup_id=pickup.id,
                idx=idx,
                image_bytes=data,
                image_content_type=getattr(uf, "content_type", None),
                image_filename=uf.filename,
            )
        )

    session.commit()

    return templates.TemplateResponse(
        "pickup.html",
        {
            "request": request,
            "pharmacy": pharmacy,
            "user": user,
            "message": f"Pickup saved with {len(provided)} photo(s).",
        },
    )


@router.get("/pickup/{pickup_id}/photos/{idx}")
def get_pickup_photo(
    pickup_id: int,
    idx: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    photo = session.exec(
        select(PickupPhoto).where(
            PickupPhoto.pickup_id == pickup_id,
            PickupPhoto.idx == idx,
        )
    ).first()
    if not photo or not photo.image_bytes:
        raise HTTPException(status_code=404, detail="Photo not found")
    return Response(
        content=photo.image_bytes,
        media_type=photo.image_content_type or "image/jpeg",
    )
