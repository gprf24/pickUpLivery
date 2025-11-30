# app/db/migrations.py
from __future__ import annotations

"""
Minimal migrations module.

This module contains small, idempotent migrations that are safe to run on
every application startup.

Current responsibilities:
- Ensure new columns exist on already-created tables:
  - pickups.comment                  (TEXT, nullable)
  - app_settings.show_history_to_drivers (BOOLEAN NOT NULL DEFAULT TRUE)
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def run_minimal_migrations(engine: Engine) -> None:
    """
    Run small idempotent migrations for already-created tables.

    Safe to call multiple times. If a column already exists, the statements
    will either be no-ops (ADD COLUMN IF NOT EXISTS) or simply re-apply
    DEFAULT/NOT NULL constraints.
    """
    with engine.connect() as conn:
        # 1) Add comment column to pickups table (nullable TEXT)
        conn.execute(
            text(
                """
                ALTER TABLE pickups
                ADD COLUMN IF NOT EXISTS comment TEXT;
                """
            )
        )

        # 2) Add show_history_to_drivers to app_settings
        #    - ensure column exists
        #    - set DEFAULT TRUE
        #    - fill NULLs with TRUE
        #    - enforce NOT NULL
        conn.execute(
            text(
                """
                ALTER TABLE app_settings
                ADD COLUMN IF NOT EXISTS show_history_to_drivers BOOLEAN;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE app_settings
                ALTER COLUMN show_history_to_drivers
                SET DEFAULT TRUE;
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE app_settings
                SET show_history_to_drivers = TRUE
                WHERE show_history_to_drivers IS NULL;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE app_settings
                ALTER COLUMN show_history_to_drivers
                SET NOT NULL;
                """
            )
        )

        conn.commit()
