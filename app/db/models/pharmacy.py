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
    - The public_id allows exposing pharmacies in URLs without leaking sequential IDs.
    - No ORM relationships are defined here to keep the model lightweight.
    - region_id kept as an optional FK to avoid strict coupling on insert.
    """

    __tablename__ = "PP_pharmacy"

    id: Optional[int] = Field(default=None, primary_key=True)

    # NEW: non-guessable public identifier
    public_id: str = Field(
        default_factory=generate_public_id,
        index=True,
        nullable=False,
    )

    name: str = Field(index=True)

    region_id: Optional[int] = Field(
        default=None,
        foreign_key="PP_region.id",
        description="Foreign key referencing PP_region table.",
    )

    address: Optional[str] = None

    is_active: bool = Field(default=True)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
