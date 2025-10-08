# app/db/models/pickup_photo.py
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, LargeBinary, UniqueConstraint
from sqlmodel import Field, SQLModel


class PickupPhoto(SQLModel, table=True):
    """
    Child photo entity for a pickup (1..4 photos per pickup).
    - We keep an idx (1..4) to preserve order and enforce max 4.
    - Binary data is stored in DB for simplicity; could be S3 later.
    """

    __tablename__ = "PP_pickup_photo"
    __table_args__ = (
        UniqueConstraint("pickup_id", "idx", name="uq_pickup_photo_pickup_idx"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    pickup_id: int = Field(index=True, foreign_key="PP_pickup.id")
    idx: int = Field(index=True)  # 1..4

    image_bytes: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary))
    image_content_type: Optional[str] = None
    image_filename: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
