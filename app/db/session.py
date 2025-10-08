# app/db/session.py
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine

# Load environment variables from project root
ROOT = Path(__file__).resolve().parents[2]  # → project root
ENV = ROOT / ".env"
if ENV.exists():
    load_dotenv(ENV)
else:
    load_dotenv()

# Expect connection string in .env like:
# PG_CONN_STR=postgresql+psycopg://user:pass@host:5432/dbname
PG_URL = os.getenv("PG_CONN_STR")
if not PG_URL:
    raise RuntimeError("PG_CONN_STR is not set in .env")

# Create SQLAlchemy engine (PostgreSQL only)
engine = create_engine(
    PG_URL,
    pool_pre_ping=True,  # validate connection before each use
    echo=False,  # set True to log SQL
    future=True,
)


def get_engine():
    """Return the shared SQLAlchemy engine."""
    return engine


def get_session():
    """Dependency for FastAPI routes — yields a scoped DB session."""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """
    Create all tables if they don't exist.
    Does NOT drop or delete anything.
    Models must be imported so SQLModel sees their metadata.
    """
    from app.db import models  # ensure models are registered

    SQLModel.metadata.create_all(engine)
