# app/db/models/pickup.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class Pickup(SQLModel, table=True):
    """
    Pickup entry stored in DB.

    Notes:
    - Photos are stored in the separate `pickup_photos` table.
      Legacy inline image columns have been removed.
    - Coordinates are optional.
    - Simple 'status' string is used for now ("done" by default).
    - `cutoff_at_utc` and `timing_status` are used for tracking whether
      the pickup was created on time or with delay relative to the
      pharmacy cutoff time for that specific day.
    """

    __tablename__ = "pickups"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(index=True, foreign_key="users.id")
    pharmacy_id: int = Field(index=True, foreign_key="pharmacies.id")

    # Coordinates (nullable)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Optional free-text comment from driver
    comment: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Optional driver comment for this pickup.",
    )

    # Status (simple text state)
    status: str = Field(
        default="done",
        index=True,
        description="Generic status for the pickup (e.g. 'done').",
    )

    # ------------------------------------------------------------------
    # Timing tracking relative to pharmacy cutoff
    # ------------------------------------------------------------------
    cutoff_at_utc: Optional[datetime] = Field(
        default=None,
        description=(
            "Concrete UTC timestamp of the cutoff used for this pickup "
            "(built from pharmacy weekly schedule + local date). "
            "Can be NULL if there was no cutoff for that day."
        ),
    )

    timing_status: Optional[str] = Field(
        default=None,
        max_length=20,
        description=(
            "Timing status relative to cutoff_at_utc. "
            "Expected values: 'on_time', 'late', or 'no_cutoff'. "
            "Should be computed once at creation and never changed later."
        ),
    )

    # Timestamp stored in UTC (naive in DB, but we treat it as UTC)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        index=True,
        description="UTC timestamp when the pickup was created.",
    )
