# Preview-only duplicate analysis. No writes, no deletes.
from typing import Any, Dict, List

from sqlalchemy import text
from sqlmodel import Session


def preview_dup_regions(session: Session) -> List[Dict[str, Any]]:
    """
    Return duplicate region groups by normalized name.
    Each item: {"name": "<lower(name)>", "ids": [ids...], "keep_id": min_id}
    """
    rows = session.exec(
        text(
            """
            WITH norm AS (
                SELECT id, LOWER(TRIM(name)) AS nname
                FROM "PP_region"
            ),
            dups AS (
                SELECT nname, MIN(id) AS keep_id, ARRAY_AGG(id ORDER BY id) AS ids
                FROM norm
                GROUP BY nname
                HAVING COUNT(*) > 1
            )
            SELECT nname, keep_id, ids FROM dups
            """
        )
    ).all()
    return [{"name": r[0], "keep_id": r[1], "ids": list(r[2])} for r in rows]


def preview_dup_pharmacies(session: Session) -> List[Dict[str, Any]]:
    """
    Return duplicate pharmacy groups by (region_id, lower(name)).
    Each item: {"region_id": <id>, "name": "<lower(name)>", "ids": [...], "keep_id": min_id}
    """
    rows = session.exec(
        text(
            """
            WITH norm AS (
                SELECT id, region_id, LOWER(TRIM(name)) AS nname
                FROM "PP_pharmacy"
            ),
            dups AS (
                SELECT region_id, nname, MIN(id) AS keep_id, ARRAY_AGG(id ORDER BY id) AS ids
                FROM norm
                GROUP BY region_id, nname
                HAVING COUNT(*) > 1
            )
            SELECT region_id, nname, keep_id, ids FROM dups
            """
        )
    ).all()
    return [
        {"region_id": r[0], "name": r[1], "keep_id": r[2], "ids": list(r[3])}
        for r in rows
    ]


def quick_counts(session: Session) -> dict:
    counts = {}
    for tbl in [
        "PP_user",
        "PP_region",
        "PP_pharmacy",
        "PP_pickup",
        "PP_user_pharmacy_link",
    ]:
        n = session.exec(text(f'SELECT COUNT(*) FROM "{tbl}"')).one()[0]
        counts[tbl] = n
    return counts
