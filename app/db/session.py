# app/db/session.py
"""
Database engine and session helpers.

- Uses PG_CONN_STR from environment (see app/core/config.py).
- Provides a shared SQLModel engine.
- Provides `get_session()` dependency for FastAPI routes.
"""

from __future__ import annotations

from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import (
    AppSettings,
    Pharmacy,
    Region,
    User,
    UserPharmacyLink,
    UserRole,
)

# ---------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------

_settings = get_settings()
PG_CONN_STR = _settings.PG_CONN_STR

# echo=False → no SQL logging by default
engine = create_engine(PG_CONN_STR, echo=False, pool_pre_ping=True)


def get_engine():
    """Return the shared SQLModel engine instance."""
    return engine


# ---------------------------------------------------------------------
# Session dependency
# ---------------------------------------------------------------------
def get_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency — yields a scoped DB session.

    Usage:
        def endpoint(session: Session = Depends(get_session)):
            ...
    """
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------
# Schema initialization (non-destructive)
# ---------------------------------------------------------------------
def init_db() -> None:
    """
    Create all tables if they don't exist.

    This is non-destructive: it will NOT drop existing tables.
    For a full reset + seed in development, see a separate reset script.
    """
    # Import models so that SQLModel sees all table definitions
    from app.db import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        # -------------------- Global settings --------------------
        settings = AppSettings(
            id=1,
            allowed_pickups_per_day=3,
            require_pickup_location_global=True,
            min_required_photos=1,
            photo_source_mode="camera_or_upload",
        )
        session.add(settings)

        # -------------------- Regions --------------------
        region_a = Region(name="Test Region A", is_active=True)
        region_b = Region(name="Test Region B", is_active=True)
        session.add(region_a)
        session.add(region_b)
        # -------------------- Regions --------------------
        # Source list of region names (cleaned: without short codes in brackets).
        region_names = [
            "Aachen",
            "Berlin",
            "Bremen",
            "Frankfurt",
            "Halle",
            "Hamburg",
            "Hannover",
            "Leipzig",
            "Mannheim",
            "München",
            "Nürnberg",
            "Rheinland",
            "Rhein-Ruhrgebiet",
            "Ruhrgebiet",
            "Wiesbaden-Mainz",
        ]

        # Create Region objects in a loop
        regions = []
        for name in region_names:
            region = Region(name=name, is_active=True)  # default: region is active
            regions.append(region)

        # Add all regions to the session
        session.add_all(regions)

        # Flush to get database IDs for later relations
        session.flush()

        # -------------------- Pharmacies --------------------
        pharmacy_a1 = Pharmacy(
            name="Test Pharmacy A1",
            region_id=region_a.id,
            address="Demo address A1",
        )
        pharmacy_b1 = Pharmacy(
            name="Test Pharmacy B1",
            region_id=region_b.id,
            address="Demo address B1",
        )
        session.add(pharmacy_a1)
        session.add(pharmacy_b1)
        session.flush()

        # -------------------- Users --------------------
        admin = User(
            login="admin",
            password_hash=hash_password("admin123"),
            role=UserRole.admin,
            is_active=True,
            require_pickup_location=False,
        )

        driver1 = User(
            login="driver1",
            password_hash=hash_password("driver1"),
            role=UserRole.driver,
            is_active=True,
            require_pickup_location=True,
        )
        driver2 = User(
            login="driver2",
            password_hash=hash_password("driver2"),
            role=UserRole.driver,
            is_active=True,
            require_pickup_location=True,
        )
        driver3 = User(
            login="driver3",
            password_hash=hash_password("driver3"),
            role=UserRole.driver,
            is_active=True,
            require_pickup_location=None,
        )
        driver4 = User(
            login="driver4",
            password_hash=hash_password("driver4"),
            role=UserRole.driver,
            is_active=True,
            require_pickup_location=None,
        )

        session.add(admin)
        session.add(driver1)
        session.add(driver2)
        session.add(driver3)
        session.add(driver4)
        session.flush()

        # -------------------- User ↔ Pharmacy assignments --------------------
        # All drivers can access both demo pharmacies
        for drv in (driver1, driver2, driver3, driver4):
            session.add(UserPharmacyLink(user_id=drv.id, pharmacy_id=pharmacy_a1.id))
            session.add(UserPharmacyLink(user_id=drv.id, pharmacy_id=pharmacy_b1.id))

        session.commit()
