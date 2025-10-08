# app/db/models/region.py
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Region(SQLModel, table=True):
    """
    Geographical region.
    - Keep name indexed; uniqueness can be enforced at app-level for now.
    """

    __tablename__ = "PP_region"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    is_active: bool = Field(default=True)  # <-- added
    created_at: datetime = Field(default_factory=datetime.utcnow)
