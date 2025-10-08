from sqlmodel import SQLModel

from app.db import base  # noqa: F401 (imports tables)
from app.db.session import get_engine


def init_db() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
