# app/core/deps.py
"""
Common FastAPI dependencies:

- DB session (`get_session`)
- Current user (`get_current_user`)
- Admin guard (`require_admin`)
- Global app settings (`get_app_settings`)
- Jinja2 templates helper (`templates`)
"""

from __future__ import annotations

from typing import Generator

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.core.security import hash_password
from app.db.models.settings import AppSettings
from app.db.models.user import User, UserRole
from app.db.session import get_engine

# Jinja templates (adjust path if your templates/ live elsewhere)
templates = Jinja2Templates(directory="app/templates")


def get_session() -> Generator[Session, None, None]:
    """
    Provide a SQLModel session for each request.

    This is a thin wrapper around the shared engine from app.db.session.
    """
    engine = get_engine()
    with Session(engine) as session:
        yield session


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    """
    Detect current user based on cookie "user_id".

    Behaviour:
    1) If a valid user_id cookie is present and refers to an active user → return it.
    2) If no users exist at all → bootstrap an admin:admin user and return it.
    3) Otherwise → raise 401 (Not logged in).
    """
    # 1. Try to read user_id from cookies (set by /login)
    user_id = request.cookies.get("user_id")
    if user_id:
        try:
            uid = int(user_id)
        except ValueError:
            uid = None
        if uid is not None:
            user = session.get(User, uid)
            if user and user.is_active:
                return user

    # 2. If no users exist at all → bootstrap admin:admin
    total_users = session.exec(select(User)).all()
    if not total_users:
        admin = User(
            login="admin",
            password_hash=hash_password("admin"),
            role=UserRole.admin,
            is_active=True,
            require_pickup_location=False,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        return admin

    # 3. Otherwise unauthorized
    raise HTTPException(status_code=401, detail="Not logged in")


def require_admin(user: User) -> User:
    """Guard: only admins are allowed."""
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


def get_app_settings(
    session: Session = Depends(get_session),
) -> AppSettings:
    """
    Load the single AppSettings row, creating it with defaults if missing.

    This gives a DB-backed replacement for several .env flags:
    - allowed_pickups_per_day
    - require_pickup_location_global
    - min_required_photos
    - photo_source_mode
    """
    settings_obj = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()

    if settings_obj is None:
        settings_obj = AppSettings(id=1)
        session.add(settings_obj)
        session.commit()
        session.refresh(settings_obj)

    return settings_obj
