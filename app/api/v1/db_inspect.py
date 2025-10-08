# app/api/v1/db_inspect.py
# Read-only DB inspection endpoints (no data modification).

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_engine

router = APIRouter()

SYSTEM_SCHEMAS = {"pg_catalog", "information_schema"}

# ----------------------- BASICS (твои эндпоинты) -----------------------


@router.get("/db/ping")
def db_ping():
    """Checks DB connectivity and returns version string."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT version()")).scalar()
        return {"ok": True, "version": ver}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}") from e


@router.get("/db/schemas")
def list_schemas() -> List[str]:
    """Lists non-system schemas."""
    insp = inspect(get_engine())
    return [s for s in insp.get_schema_names() if s not in SYSTEM_SCHEMAS]


@router.get("/db/tables")
def list_tables() -> Dict[str, List[str]]:
    """Returns {schema: [tables...]} for non-system schemas."""
    engine = get_engine()
    insp = inspect(engine)
    out: Dict[str, List[str]] = {}
    for schema in insp.get_schema_names():
        if schema in SYSTEM_SCHEMAS:
            continue
        out[schema] = insp.get_table_names(schema=schema)
    return out


@router.get("/db/columns")
def list_columns():
    """Returns {schema: {table: [{name,type,nullable,default}, ...]}}."""
    engine = get_engine()
    insp = inspect(engine)
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


@router.get("/db/counts")
def table_counts():
    """
    Fast row-estimates per table using pg_stat_user_tables (no full scans).
    """
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
        raise HTTPException(status_code=500, detail=f"DB error: {e}") from e


# ----------------------- EXTRA / FULL INFO -----------------------


@router.get("/db/info")
def db_info():
    """
    Detailed info about current connection and server.
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            data = {
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
        return data
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}") from e


@router.get("/db/databases")
def list_databases():
    """
    List all databases with owner and size (requires permissions).
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        """
                SELECT
                  d.datname      AS database,
                  pg_get_userbyid(d.datdba) AS owner,
                  pg_database_size(d.datname) AS size_bytes,
                  pg_size_pretty(pg_database_size(d.datname)) AS size_pretty,
                  d.datcollate, d.datctype, d.datistemplate
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
        raise HTTPException(status_code=500, detail=f"DB error: {e}") from e


@router.get("/db/connections")
def connections_summary():
    """
    Summary of connections using pg_stat_activity (by state) + max_connections.
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            max_conn = conn.execute(text("SHOW max_connections")).scalar()
            rows = conn.execute(
                text(
                    """
                SELECT
                  state,
                  count(*) AS cnt
                FROM pg_stat_activity
                GROUP BY state
            """
                )
            ).all()
            by_db = conn.execute(
                text(
                    """
                SELECT datname, count(*) AS cnt
                FROM pg_stat_activity
                GROUP BY datname
                ORDER BY datname
            """
                )
            ).all()
        return {
            "max_connections": int(max_conn) if max_conn is not None else None,
            "by_state": [{"state": s, "count": c} for s, c in rows],
            "by_database": [{"database": d, "count": c} for d, c in by_db],
        }
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}") from e
