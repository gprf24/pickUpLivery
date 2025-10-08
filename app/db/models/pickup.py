# app/db/models/pickup.py
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, LargeBinary
from sqlmodel import Field, SQLModel


class Pickup(SQLModel, table=True):
    """
    Pickup entry stored in DB:
    - Photo bytes are stored directly in the DB (image_bytes).
    - We keep content-type and original filename as metadata.
    - Coordinates are optional.
    - Simple 'status' string is used for now ("done" by default).
    """

    __tablename__ = "PP_pickup"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(index=True, foreign_key="PP_user.id")
    pharmacy_id: int = Field(index=True, foreign_key="PP_pharmacy.id")

    # Photo stored directly in DB
    image_bytes: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary))
    image_content_type: Optional[str] = None
    image_filename: Optional[str] = None

    # Coordinates (nullable)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Status (simple text state)
    status: str = Field(default="done", index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
