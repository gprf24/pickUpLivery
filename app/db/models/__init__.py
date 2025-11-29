# app/db/models/__init__.py
"""
Import all model modules so SQLModel registers their tables
when init_db() calls SQLModel.metadata.create_all(engine).
"""

from .links import UserPharmacyLink  # noqa: F401
from .pharmacy import Pharmacy  # noqa: F401
from .pickup import Pickup  # noqa: F401
from .pickup_photo import PickupPhoto  # noqa: F401
from .region import Region  # noqa: F401
from .settings import AppSettings  # noqa: F401
from .user import User, UserRole  # noqa: F401

__all__ = [
    "User",
    "UserRole",
    "Region",
    "Pharmacy",
    "Pickup",
    "PickupPhoto",
    "UserPharmacyLink",
    "AppSettings",
]
