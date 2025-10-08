# app/db/models/pharmacy.py
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Pharmacy(SQLModel, table=True):
    """
    Pharmacy entity.
    - No ORM relationships.
    - region_id kept as a simple FK; optional to avoid strict coupling at insert time.
    """

    __tablename__ = "PP_pharmacy"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    region_id: Optional[int] = Field(default=None, foreign_key="PP_region.id")
    address: Optional[str] = None
    is_active: bool = Field(default=True)  # <-- added
    created_at: datetime = Field(default_factory=datetime.utcnow)
