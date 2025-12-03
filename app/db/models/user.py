from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class UserRole(str, Enum):
    """Simple role enum used across the app."""

    admin = "admin"
    driver = "driver"
    history = "history"


class User(SQLModel, table=True):
    """
    System users (admin/driver).

    Notes:
    - Table name no longer uses the old `PP_` prefix.
    - `require_pickup_location` can override the global setting:
        * True  → this user must always send GPS location.
        * False → this user is exempt from location requirement.
        * None  → fall back to global AppSettings.require_pickup_location_global.
    """

    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    login: str = Field(index=True)  # unique at app-level
    password_hash: str
    role: UserRole = Field(default=UserRole.driver, index=True)
    is_active: bool = Field(default=True)

    # Per-user override for GPS requirement
    require_pickup_location: Optional[bool] = Field(
        default=None,
        description=(
            "If set, overrides the global GPS requirement for this user. "
            "If None, fall back to global settings."
        ),
    )

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
