# app/api/v1/db_inspect.py
"""
Read-only database inspection endpoints.

- All endpoints require a logged-in admin user.
- All paths are under /admin/db/*.
- Visibility in Swagger (/docs) is controlled by a single global flag.
"""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.deps import get_current_user, require_admin
from app.db.models.user import User
from app.db.session import get_engine

router = APIRouter()

# System schemas that should be excluded
SYSTEM_SCHEMAS = {"pg_catalog", "information_schema"}

# Global flag controlling visibility in Swagger docs
INCLUDE_IN_SCHEMA: bool = False


# ---------------------------------------------------------
# Basic info
# ---------------------------------------------------------


@router.get("/admin/db/ping", include_in_schema=INCLUDE_IN_SCHEMA)
def db_ping(current: User = Depends(get_current_user)):
    """
    Test DB connectivity and return PostgreSQL version (admin-only).
    """
    require_admin(current)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT version()")).scalar()
        return {"ok": True, "version": ver}
    except SQLAlchemyError as e:
        raise HTTPException(500, f"DB error: {e}") from e


@router.get("/admin/db/schemas", include_in_schema=INCLUDE_IN_SCHEMA)
def list_schemas(current: User = Depends(get_current_user)) -> List[str]:
    """
    Return a list of all non-system schemas (admin-only).
    """
    require_admin(current)

    insp = inspect(get_engine())
    return [s for s in insp.get_schema_names() if s not in SYSTEM_SCHEMAS]


@router.get("/admin/db/tables", include_in_schema=INCLUDE_IN_SCHEMA)
def list_tables(current: User = Depends(get_current_user)) -> Dict[str, List[str]]:
    """
    Return {schema: [table names]} for all non-system schemas (admin-only).
    """
    require_admin(current)

    insp = inspect(get_engine())
    out: Dict[str, List[str]] = {}

    for schema in insp.get_schema_names():
        if schema in SYSTEM_SCHEMAS:
            continue
        out[schema] = insp.get_table_names(schema=schema)
    return out


@router.get("/admin/db/columns", include_in_schema=INCLUDE_IN_SCHEMA)
def list_columns(current: User = Depends(get_current_user)):
    """
    Return detailed column structure per table (admin-only).
    Format: {schema: {table: [{name, type, nullable, default}, ...]}}
    """
    require_admin(current)

    insp = inspect(get_engine())
    result: Dict[str, Dict[str, list]] = {}

    for schema in insp.get_schema_names():
        if schema in SYSTEM_SCHEMAS:
            continue

        tables = insp.get_table_names(schema=schema)
        result[schema] = {}

        for t in tables:
            cols = insp.get_columns(t, schema=schema)
            result[schema][t] = [
                {
                    "name": c["name"],
                    "type": str(c["type"]),
                    "nullable": c["nullable"],
                    "default": c.get("default"),
                }
                for c in cols
            ]

    return result


@router.get("/admin/db/counts", include_in_schema=INCLUDE_IN_SCHEMA)
def table_counts(current: User = Depends(get_current_user)):
    """
    Return approximate row counts per table using pg_stat_user_tables (admin-only).
    No full table scans are performed.
    """
    require_admin(current)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT schemaname, relname, n_live_tup
                    FROM pg_stat_user_tables
                    ORDER BY schemaname, relname
                    """
                )
            ).all()

        return [{"schema": s, "table": t, "approx_rows": n} for s, t, n in rows]

    except SQLAlchemyError as e:
        raise HTTPException(500, f"DB error: {e}") from e


# ---------------------------------------------------------
# Extended information
# ---------------------------------------------------------


@router.get("/admin/db/info", include_in_schema=INCLUDE_IN_SCHEMA)
def db_info(current: User = Depends(get_current_user)):
    """
    Return detailed server and connection information (admin-only).
    """
    require_admin(current)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            return {
                "server_version": conn.execute(text("SHOW server_version")).scalar(),
                "current_database": conn.execute(
                    text("SELECT current_database()")
                ).scalar(),
                "current_user": conn.execute(text("SELECT current_user")).scalar(),
                "timezone": conn.execute(text("SHOW TimeZone")).scalar(),
                "server_addr": conn.execute(
                    text("SELECT inet_server_addr()::text")
                ).scalar(),
                "server_port": conn.execute(text("SELECT inet_server_port()")).scalar(),
                "is_superuser": conn.execute(
                    text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                ).scalar(),
                "default_isolation": conn.execute(
                    text("SHOW default_transaction_isolation")
                ).scalar(),
                "datestyle": conn.execute(text("SHOW DateStyle")).scalar(),
            }
    except SQLAlchemyError as e:
        raise HTTPException(500, f"DB error: {e}") from e


@router.get("/admin/db/databases", include_in_schema=INCLUDE_IN_SCHEMA)
def list_databases(current: User = Depends(get_current_user)):
    """
    Return all PostgreSQL databases with size and owner (admin-only).
    """
    require_admin(current)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        """
                        SELECT
                          d.datname AS database,
                          pg_get_userbyid(d.datdba) AS owner,
                          pg_database_size(d.datname) AS size_bytes,
                          pg_size_pretty(pg_database_size(d.datname)) AS size_pretty,
                          d.datcollate,
                          d.datctype,
                          d.datistemplate
                        FROM pg_database d
                        ORDER BY d.datistemplate DESC, d.datname
                        """
                    )
                )
                .mappings()
                .all()
            )

        return {"databases": [dict(r) for r in rows]}
    except SQLAlchemyError as e:
        raise HTTPException(500, f"DB error: {e}") from e


@router.get("/admin/db/connections", include_in_schema=INCLUDE_IN_SCHEMA)
def connections_summary(current: User = Depends(get_current_user)):
    """
    Return connection statistics (admin-only): total, by state, by database.
    """
    require_admin(current)

    engine = get_engine()

    try:
        with engine.connect() as conn:
            max_conn = conn.execute(text("SHOW max_connections")).scalar()

            by_state = conn.execute(
                text(
                    """
                    SELECT state, count(*)
                    FROM pg_stat_activity
                    GROUP BY state
                    """
                )
            ).all()

            by_db = conn.execute(
                text(
                    """
                    SELECT datname, count(*)
                    FROM pg_stat_activity
                    GROUP BY datname
                    ORDER BY datname
                    """
                )
            ).all()

        return {
            "max_connections": int(max_conn) if max_conn else None,
            "by_state": [{"state": s, "count": c} for s, c in by_state],
            "by_database": [{"database": d, "count": c} for d, c in by_db],
        }

    except SQLAlchemyError as e:
        raise HTTPException(500, f"DB error: {e}") from e
