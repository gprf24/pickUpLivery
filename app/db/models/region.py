from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Region(SQLModel, table=True):
    """
    Geographical region.

    Notes:
    - Table name no longer uses the old `PP_` prefix.
    - Name is indexed; uniqueness can be enforced at app level.
    """

    __tablename__ = "regions"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
