from __future__ import annotations

"""
Minimal migrations module.

...
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def run_minimal_migrations(engine: Engine) -> None:
    """
    Run small idempotent migrations for already-created tables.
    """
    with engine.connect() as conn:
        # ---------------------------------------------------------------
        # 0a) Ensure enum type userrole has value 'history'
        #
        # This is needed because the Python enum UserRole now has:
        #   admin, driver, history
        # but the PostgreSQL enum `userrole` may still only have
        #   'admin', 'driver'.
        #
        # The block is idempotent: if 'history' already exists,
        # ALTER TYPE is not executed.
        # ---------------------------------------------------------------
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_type t
                        JOIN pg_enum e ON t.oid = e.enumtypid
                        WHERE t.typname = 'userrole'
                          AND e.enumlabel = 'history'
                    ) THEN
                        ALTER TYPE userrole ADD VALUE 'history';
                    END IF;
                END$$;
                """
            )
        )

        # ---------------------------------------------------------------
        # 0) Drop obsolete legacy columns IF they exist
        #    (defensive, before adding or backfilling new structure)
        # ---------------------------------------------------------------
        legacy_cols = [
            ("pharmacies", "latest_pickup_time_utc"),
            ("pickups", "cutoff_time_utc"),
            ("pickups", "image_bytes"),
            ("pickups", "image_content_type"),
            ("pickups", "image_filename"),
        ]

        for table, col in legacy_cols:
            conn.execute(
                text(
                    f"""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name = '{table}'
                              AND column_name = '{col}'
                        ) THEN
                            ALTER TABLE {table} DROP COLUMN {col};
                        END IF;
                    END$$;
                    """
                )
            )

        # ---------------------------------------------------------------
        # 1) Add comment column to pickups table (nullable TEXT)
        # ---------------------------------------------------------------
        conn.execute(
            text(
                """
                ALTER TABLE pickups
                ADD COLUMN IF NOT EXISTS comment TEXT;
                """
            )
        )

        # ---------------------------------------------------------------
        # 2) Add show_history_to_drivers to app_settings
        # ---------------------------------------------------------------
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

        # ---------------------------------------------------------------
        # 3) Weekly cutoff schedule on pharmacies (local time)
        # ---------------------------------------------------------------
        conn.execute(
            text(
                """
                ALTER TABLE pharmacies
                ADD COLUMN IF NOT EXISTS cutoff_mon_local TIME;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE pharmacies
                ADD COLUMN IF NOT EXISTS cutoff_tue_local TIME;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE pharmacies
                ADD COLUMN IF NOT EXISTS cutoff_wed_local TIME;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE pharmacies
                ADD COLUMN IF NOT EXISTS cutoff_thu_local TIME;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE pharmacies
                ADD COLUMN IF NOT EXISTS cutoff_fri_local TIME;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE pharmacies
                ADD COLUMN IF NOT EXISTS cutoff_sat_local TIME;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE pharmacies
                ADD COLUMN IF NOT EXISTS cutoff_sun_local TIME;
                """
            )
        )

        # ---------------------------------------------------------------
        # 3a) Backfill fake weekly schedule for existing pharmacies
        # ---------------------------------------------------------------
        conn.execute(
            text(
                """
                UPDATE pharmacies
                SET
                  cutoff_mon_local = COALESCE(cutoff_mon_local, TIME '15:50'),
                  cutoff_tue_local = COALESCE(cutoff_tue_local, TIME '15:50'),
                  cutoff_wed_local = COALESCE(cutoff_wed_local, TIME '15:50'),
                  cutoff_thu_local = COALESCE(cutoff_thu_local, TIME '15:50'),
                  cutoff_fri_local = COALESCE(cutoff_fri_local, TIME '15:50'),
                  cutoff_sat_local = COALESCE(cutoff_sat_local, TIME '12:00')
                  -- cutoff_sun_local left as-is (NULL => no cutoff)
                ;
                """
            )
        )

        # ---------------------------------------------------------------
        # 4) New cutoff_at_utc / timing_status on pickups
        # ---------------------------------------------------------------
        conn.execute(
            text(
                """
                ALTER TABLE pickups
                ADD COLUMN IF NOT EXISTS cutoff_at_utc TIMESTAMP;
                """
            )
        )

        conn.execute(
            text(
                """
                ALTER TABLE pickups
                ADD COLUMN IF NOT EXISTS timing_status VARCHAR(20);
                """
            )
        )

        # ---------------------------------------------------------------
        # 4a) Backfill cutoff_at_utc + timing_status for existing pickups
        # ---------------------------------------------------------------
        conn.execute(
            text(
                """
                UPDATE pickups AS p
                SET
                  cutoff_at_utc = sub.cutoff_at_utc,
                  timing_status =
                    CASE
                      WHEN sub.cutoff_at_utc IS NULL THEN 'no_cutoff'
                      WHEN p.created_at <= sub.cutoff_at_utc THEN 'on_time'
                      ELSE 'late'
                    END
                FROM (
                  SELECT
                    p.id AS pickup_id,
                    CASE
                      WHEN cutoff_time_local IS NULL THEN NULL
                      ELSE
                        (
                          (local_date + cutoff_time_local)
                          AT TIME ZONE 'Europe/Berlin'
                        )
                    END AS cutoff_at_utc
                  FROM (
                    SELECT
                      p.id,
                      (p.created_at AT TIME ZONE 'Europe/Berlin')::date AS local_date,
                      EXTRACT(
                        DOW FROM (p.created_at AT TIME ZONE 'Europe/Berlin')
                      ) AS local_dow,
                      ph.cutoff_mon_local,
                      ph.cutoff_tue_local,
                      ph.cutoff_wed_local,
                      ph.cutoff_thu_local,
                      ph.cutoff_fri_local,
                      ph.cutoff_sat_local,
                      ph.cutoff_sun_local,
                      CASE
                        WHEN EXTRACT(DOW FROM (p.created_at AT TIME ZONE 'Europe/Berlin')) = 1
                          THEN ph.cutoff_mon_local
                        WHEN EXTRACT(DOW FROM (p.created_at AT TIME ZONE 'Europe/Berlin')) = 2
                          THEN ph.cutoff_tue_local
                        WHEN EXTRACT(DOW FROM (p.created_at AT TIME ZONE 'Europe/Berlin')) = 3
                          THEN ph.cutoff_wed_local
                        WHEN EXTRACT(DOW FROM (p.created_at AT TIME ZONE 'Europe/Berlin')) = 4
                          THEN ph.cutoff_thu_local
                        WHEN EXTRACT(DOW FROM (p.created_at AT TIME ZONE 'Europe/Berlin')) = 5
                          THEN ph.cutoff_fri_local
                        WHEN EXTRACT(DOW FROM (p.created_at AT TIME ZONE 'Europe/Berlin')) = 6
                          THEN ph.cutoff_sat_local
                        WHEN EXTRACT(DOW FROM (p.created_at AT TIME ZONE 'Europe/Berlin')) = 0
                          THEN ph.cutoff_sun_local
                        ELSE NULL
                      END AS cutoff_time_local
                    FROM pickups p
                    JOIN pharmacies ph
                      ON ph.id = p.pharmacy_id
                  ) AS p
                ) AS sub
                WHERE p.id = sub.pickup_id
                  AND p.cutoff_at_utc IS NULL;
                """
            )
        )

        # ---------------------------------------------------------------
        # 5) Extra safety: drop legacy columns again via IF EXISTS
        # ---------------------------------------------------------------
        conn.execute(
            text(
                """
                ALTER TABLE pharmacies
                DROP COLUMN IF EXISTS latest_pickup_time_utc;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE pickups
                DROP COLUMN IF EXISTS cutoff_time_utc;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE pickups
                DROP COLUMN IF EXISTS image_bytes,
                DROP COLUMN IF EXISTS image_content_type,
                DROP COLUMN IF EXISTS image_filename;
                """
            )
        )

        conn.commit()
