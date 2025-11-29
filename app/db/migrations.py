# app/db/migrations.py
from __future__ import annotations

"""
Minimal migrations module (no-op).

Previously this file contained ALTER TABLE statements for legacy
tables named with a "PP_" prefix (PP_pickup, PP_pharmacy, ...).

After performing a full clean reset of the database and switching to
the new SQLModel-based schema (tables: users, regions, pharmacies,
pickups, pickup_photos, user_pharmacy_links, app_settings, ...),
those migrations are no longer needed.

We keep this module only to avoid import errors and to have a place
for future small, idempotent migrations if necessary.
"""

from sqlalchemy.engine import Engine


def run_minimal_migrations(engine: Engine) -> None:
    """
    No-op placeholder.

    You can safely remove the call to this from app/main.py.
    If you later need to add a tiny idempotent migration
    (for already-created tables), you can implement it here.
    """
    return
