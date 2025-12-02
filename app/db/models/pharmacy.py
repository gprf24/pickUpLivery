from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


def generate_public_id() -> str:
    """Generate a non-guessable public identifier for pharmacy URLs."""
    return uuid4().hex


class Pharmacy(SQLModel, table=True):
    """
    Pharmacy entity.

    Notes:
    - Uses a non-guessable `public_id` for URLs (instead of integer PK).
    - `region_id` is a nullable FK to `regions.id`.
    - Weekly cutoff times are stored as local times (e.g. Europe/Berlin)
      for each weekday. When creating a pickup, the backend will:
        * convert pickup creation time to local time,
        * select the cutoff field for that weekday,
        * build a concrete cutoff datetime and convert it to UTC.
    """

    __tablename__ = "pharmacies"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Non-guessable public identifier
    public_id: str = Field(
        default_factory=generate_public_id,
        index=True,
        nullable=False,
    )

    name: str = Field(index=True)

    region_id: Optional[int] = Field(
        default=None,
        foreign_key="regions.id",
        description="Foreign key referencing regions table.",
    )

    address: Optional[str] = None

    is_active: bool = Field(default=True)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ------------------------------------------------------------------
    # Weekly cutoff schedule (LOCAL time, e.g. Europe/Berlin)
    # ------------------------------------------------------------------
    # For each weekday, this stores the latest allowed pickup time as a
    # time-of-day in the pharmacy's local timezone.
    #
    # NULL means "no cutoff for that day" → pickups will get timing_status
    # = "no_cutoff".
    #
    # Mapping of Python weekday() to columns:
    #   Monday    => cutoff_mon_local
    #   Tuesday   => cutoff_tue_local
    #   Wednesday => cutoff_wed_local
    #   Thursday  => cutoff_thu_local
    #   Friday    => cutoff_fri_local
    #   Saturday  => cutoff_sat_local
    #   Sunday    => cutoff_sun_local
    #
    # A future extension could introduce a `timezone` field per pharmacy.
    cutoff_mon_local: Optional[time] = Field(
        default=None,
        description="Latest allowed pickup time on Monday (local time).",
    )
    cutoff_tue_local: Optional[time] = Field(
        default=None,
        description="Latest allowed pickup time on Tuesday (local time).",
    )
    cutoff_wed_local: Optional[time] = Field(
        default=None,
        description="Latest allowed pickup time on Wednesday (local time).",
    )
    cutoff_thu_local: Optional[time] = Field(
        default=None,
        description="Latest allowed pickup time on Thursday (local time).",
    )
    cutoff_fri_local: Optional[time] = Field(
        default=None,
        description="Latest allowed pickup time on Friday (local time).",
    )
    cutoff_sat_local: Optional[time] = Field(
        default=None,
        description="Latest allowed pickup time on Saturday (local time).",
    )
    cutoff_sun_local: Optional[time] = Field(
        default=None,
        description="Latest allowed pickup time on Sunday (local time).",
    )
