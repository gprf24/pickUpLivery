# app/db/init_db.py
"""
Development helper to **reset** the database schema and seed demo data.

WARNING:
    This script DROPS ALL TABLES and recreates them from scratch.
    Use only in development or in an environment where data loss is acceptable.

What it does:
    - Drop all SQLModel tables.
    - Recreate all tables.
    - Seed:
        * 1 admin user
        * 4 driver users
        * 2 regions
        * 2 pharmacies (1 per region)
        * user ↔ pharmacy links
        * a default AppSettings row
"""

from __future__ import annotations

from sqlmodel import Session, SQLModel

from app.core.security import hash_password
from app.db.models import (
    AppSettings,
    Pharmacy,
    Region,
    User,
    UserPharmacyLink,
    UserRole,
)
from app.db.session import get_engine


def seed_db() -> None:
    """Drop all tables, recreate schema, and insert demo data."""
    engine = get_engine()

    print("Dropping all SQLModel tables...")
    SQLModel.metadata.drop_all(engine)

    print("Creating all SQLModel tables...")
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
        session.flush()  # to get IDs

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

    print("Seed completed.")
