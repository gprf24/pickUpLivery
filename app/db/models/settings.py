# app/db/models/settings.py
from __future__ import annotations

from typing import Optional

from sqlmodel import Field, SQLModel


class AppSettings(SQLModel, table=True):
    """
    Global application-level settings that can be changed from the admin UI.

    We intentionally use a single row with a fixed primary key (id=1),
    so we can always load it via SELECT WHERE id=1.
    """

    __tablename__ = "app_settings"

    id: Optional[int] = Field(default=1, primary_key=True)

    # 1) Max allowed pickups per day (global limit)
    allowed_pickups_per_day: int = Field(default=100)

    # 2) Global default: require pickup GPS location
    # Per-driver override lives on the User model.
    require_pickup_location_global: bool = Field(default=True)

    # 6) Minimal number of required photos per pickup
    min_required_photos: int = Field(default=1)

    # 7) Photo source mode:
    #   "camera_only"        → add capture="environment" on mobile
    #   "camera_or_upload"   → allow upload from device as well
    photo_source_mode: str = Field(default="camera_or_upload", max_length=50)
