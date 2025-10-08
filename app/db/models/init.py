# app/db/models/__init__.py
"""
Import all model modules so SQLModel registers their tables
when init_db() calls SQLModel.metadata.create_all(engine).
"""

from .links import UserPharmacyLink  # noqa: F401
from .pharmacy import Pharmacy  # noqa: F401
from .pickup import Pickup  # noqa: F401
from .region import Region  # noqa: F401

# Keep explicit imports to ensure side-effects (table registration)
from .user import User  # noqa: F401

__all__ = [
    "User",
    "Region",
    "Pharmacy",
    "Pickup",
    "UserPharmacyLink",
]
