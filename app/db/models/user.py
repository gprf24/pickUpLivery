# app/db/models/user.py
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class UserRole(str, Enum):
    """Simple role enum used across the app."""

    admin = "admin"
    driver = "driver"


class User(SQLModel, table=True):
    """System users (admin/driver)."""

    __tablename__ = "PP_user"

    id: Optional[int] = Field(default=None, primary_key=True)
    login: str = Field(index=True)  # consider unique at app-level
    password_hash: str
    role: UserRole = Field(default=UserRole.driver, index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
