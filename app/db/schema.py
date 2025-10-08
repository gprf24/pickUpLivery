# Compatibility shim so legacy code importing SessionLocal/config keeps working.

from sqlmodel import Session

from app.core.config import config  # re-export to satisfy old imports
from app.db.session import engine


def SessionLocal() -> Session:
    """
    Legacy factory returning a SQLModel Session bound to our shared engine.
    Supports both:
        s = SessionLocal()
        with SessionLocal() as s:
    """
    return Session(engine)
