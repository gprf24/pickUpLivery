from sqlalchemy import text
from sqlalchemy.engine import Engine


def run_minimal_migrations(engine: Engine) -> None:
    """
    Idempotent migrations safe to run on every startup.
    Adds new columns to existing tables if they are missing.
    """
    with engine.begin() as conn:
        # coords (if you haven't already added)
        conn.execute(
            text(
                """
            ALTER TABLE "PP_pickup"
            ADD COLUMN IF NOT EXISTS latitude double precision NULL
        """
            )
        )
        conn.execute(
            text(
                """
            ALTER TABLE "PP_pickup"
            ADD COLUMN IF NOT EXISTS longitude double precision NULL
        """
            )
        )

        # status
        conn.execute(
            text(
                """
            ALTER TABLE "PP_pickup"
            ADD COLUMN IF NOT EXISTS status varchar(50) NULL
        """
            )
        )
        conn.execute(
            text(
                """
            UPDATE "PP_pickup" SET status = 'done' WHERE status IS NULL
        """
            )
        )

        # photo stored in DB (legacy columns on PP_pickup)
        conn.execute(
            text(
                """
            ALTER TABLE "PP_pickup"
            ADD COLUMN IF NOT EXISTS image_bytes bytea NULL
        """
            )
        )
        conn.execute(
            text(
                """
            ALTER TABLE "PP_pickup"
            ADD COLUMN IF NOT EXISTS image_content_type text NULL
        """
            )
        )
        conn.execute(
            text(
                """
            ALTER TABLE "PP_pickup"
            ADD COLUMN IF NOT EXISTS image_filename text NULL
        """
            )
        )

        conn.execute(
            text(
                """
            ALTER TABLE "PP_region"
            ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT TRUE
        """
            )
        )
        conn.execute(
            text(
                """
            ALTER TABLE "PP_pharmacy"
            ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT TRUE
        """
            )
        )

        # --- Create PP_pickup_photo and backfill from legacy columns ---
        conn.execute(
            text(
                """
        CREATE TABLE IF NOT EXISTS "PP_pickup_photo" (
            id SERIAL PRIMARY KEY,
            pickup_id INTEGER NOT NULL REFERENCES "PP_pickup"(id) ON DELETE CASCADE,
            idx INTEGER NOT NULL CHECK (idx BETWEEN 1 AND 4),
            image_bytes BYTEA,
            image_content_type TEXT,
            image_filename TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW())
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pickup_photo_pickup_idx
            ON "PP_pickup_photo"(pickup_id, idx);
        CREATE INDEX IF NOT EXISTS ix_pickup_photo_pickup_id
            ON "PP_pickup_photo"(pickup_id);
        CREATE INDEX IF NOT EXISTS ix_pickup_photo_idx
            ON "PP_pickup_photo"(idx);
        """
            )
        )

        # Backfill: move legacy single image from PP_pickup to PP_pickup_photo as idx=1
        # Only for pickups that have image_bytes and have no child rows yet.
        conn.execute(
            text(
                """
        INSERT INTO "PP_pickup_photo" (pickup_id, idx, image_bytes, image_content_type, image_filename)
        SELECT p.id, 1, p.image_bytes, p.image_content_type, p.image_filename
        FROM "PP_pickup" p
        LEFT JOIN "PP_pickup_photo" ph
        ON ph.pickup_id = p.id
        WHERE p.image_bytes IS NOT NULL
        AND ph.id IS NULL
        """
            )
        )

        # ------------------------------------------------------------------
        # NEW: public_id for pharmacies (non-guessable external identifier)
        # ------------------------------------------------------------------
        conn.execute(
            text(
                """
        ALTER TABLE "PP_pharmacy"
        ADD COLUMN IF NOT EXISTS public_id varchar(64);
        """
            )
        )

        # Ensure pgcrypto is available for gen_random_bytes()
        conn.execute(
            text(
                """
        CREATE EXTENSION IF NOT EXISTS pgcrypto;
        """
            )
        )

        # Backfill public_id for existing pharmacies where it's NULL
        conn.execute(
            text(
                """
        UPDATE "PP_pharmacy"
        SET public_id = encode(gen_random_bytes(16), 'hex')
        WHERE public_id IS NULL;
        """
            )
        )

        # Make sure public_id is NOT NULL and indexed
        conn.execute(
            text(
                """
        ALTER TABLE "PP_pharmacy"
        ALTER COLUMN public_id SET NOT NULL;
        """
            )
        )
        conn.execute(
            text(
                """
        CREATE INDEX IF NOT EXISTS ix_PP_pharmacy_public_id
        ON "PP_pharmacy"(public_id);
        """
            )
        )

        # ------------------------------------------------------------------
        # NEW: public_id for pickup photos (non-guessable external identifier)
        # ------------------------------------------------------------------
        conn.execute(
            text(
                """
        ALTER TABLE "PP_pickup_photo"
        ADD COLUMN IF NOT EXISTS public_id varchar(64);
        """
            )
        )

        # Backfill public_id for existing photos where it's NULL
        conn.execute(
            text(
                """
        UPDATE "PP_pickup_photo"
        SET public_id = encode(gen_random_bytes(16), 'hex')
        WHERE public_id IS NULL;
        """
            )
        )

        conn.execute(
            text(
                """
        ALTER TABLE "PP_pickup_photo"
        ALTER COLUMN public_id SET NOT NULL;
        """
            )
        )
        conn.execute(
            text(
                """
        CREATE INDEX IF NOT EXISTS ix_PP_pickup_photo_public_id
        ON "PP_pickup_photo"(public_id);
        """
            )
        )
