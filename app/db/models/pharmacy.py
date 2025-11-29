from __future__ import annotations

from datetime import datetime, timezone
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
