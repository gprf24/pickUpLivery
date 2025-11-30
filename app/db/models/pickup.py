# app/db/models/pickup.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, LargeBinary, Text
from sqlmodel import Field, SQLModel


class Pickup(SQLModel, table=True):
    """
    Pickup entry stored in DB.

    Notes:
    - Photos are now primarily stored in the separate `pickup_photos` table,
      but legacy columns (image_bytes, image_content_type, image_filename)
      are kept for backwards compatibility.
    - Coordinates are optional.
    - Simple 'status' string is used for now ("done" by default).
    """

    __tablename__ = "pickups"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(index=True, foreign_key="users.id")
    pharmacy_id: int = Field(index=True, foreign_key="pharmacies.id")

    # Legacy single-photo storage (can be removed later if unused)
    image_bytes: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary))
    image_content_type: Optional[str] = None
    image_filename: Optional[str] = None

    # Coordinates (nullable)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Optional free-text comment from driver
    comment: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Optional driver comment for this pickup",
    )

    # Status (simple text state)
    status: str = Field(default="done", index=True)

    # Timestamp stored in UTC
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
