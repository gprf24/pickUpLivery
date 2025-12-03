# app/core/deps.py
"""
Common FastAPI dependencies:

- DB session (`get_session`)
- Current user (`get_current_user`)
- Optional current user (`get_current_user_optional`)
- Admin guard (`require_admin`)
- Driver guard (`require_driver`)
- History-access guard (`require_history_access`)
- Global app settings (`get_app_settings`)
- Jinja2 templates helper (`templates`)
"""

from __future__ import annotations

from typing import Generator, Optional

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


# ---------------------------------------------------------------------------
# Internal helpers for user detection / bootstrap
# ---------------------------------------------------------------------------


def _get_user_from_cookie(request: Request, session: Session) -> Optional[User]:
    """
    Try to read the current user from the `user_id` cookie.

    Returns:
        - User instance if cookie is valid and user is active.
        - None otherwise.
    """
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None

    try:
        uid = int(user_id)
    except ValueError:
        return None

    user = session.get(User, uid)
    if user and user.is_active:
        return user

    return None


def _bootstrap_admin_if_none(session: Session) -> Optional[User]:
    """
    If there are no users in the DB at all, create a default admin:admin user.

    Returns:
        - The newly created admin user if bootstrap happened.
        - None if at least one user already exists.
    """
    total_users = session.exec(select(User)).all()
    if total_users:
        return None

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


# ---------------------------------------------------------------------------
# Public dependencies
# ---------------------------------------------------------------------------


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    """
    Strict current user dependency.

    Behaviour:
    1) If a valid user_id cookie is present and refers to an active user → return it.
    2) If no users exist at all → bootstrap an admin:admin user and return it.
    3) Otherwise → raise 401 (Not logged in).
    """
    # 1. Try to load from cookie
    user = _get_user_from_cookie(request, session)
    if user:
        return user

    # 2. Bootstrap admin if there are no users at all
    admin = _bootstrap_admin_if_none(session)
    if admin:
        return admin

    # 3. Otherwise unauthorized
    raise HTTPException(status_code=401, detail="Not logged in")


def get_current_user_optional(
    request: Request,
    session: Session = Depends(get_session),
) -> Optional[User]:
    """
    Soft / optional user dependency.

    Behaviour:
    1) If a valid user_id cookie is present and refers to an active user → return it.
    2) If no users exist at all → bootstrap an admin:admin user and return it.
    3) Otherwise → return None (do NOT raise 401).

    This is useful for routes like `/` where you want:
    - logged-in users to be redirected to tasks/history,
    - guests to be redirected to login,
    without throwing an HTTP 401.
    """
    # 1. Try to load from cookie
    user = _get_user_from_cookie(request, session)
    if user:
        return user

    # 2. Bootstrap admin if there are no users at all
    admin = _bootstrap_admin_if_none(session)
    if admin:
        return admin

    # 3. Guest – just return None
    return None


def require_admin(user: User) -> User:
    """
    Guard: only admins are allowed.

    NOTE: This keeps the old pattern:
      - route depends on `get_current_user` and also on `require_admin`,
        and FastAPI wires the `user` parameter of this function
        from the already-resolved user object.
    """
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


def require_driver(user: User = Depends(get_current_user)) -> User:
    """
    Guard: only drivers (and admins) are allowed.

    Intended for pickup-creation or driver-only endpoints.
    """
    if user.role not in (UserRole.admin, UserRole.driver):
        raise HTTPException(status_code=403, detail="Driver privileges required")
    return user


def require_history_access(user: User = Depends(get_current_user)) -> User:
    """
    Guard: only users that are allowed to access pickup history.

    Currently allowed:
      - Admins
      - Drivers   (final visibility is still additionally controlled in the
                   history endpoint via AppSettings.show_history_to_drivers)
      - History-only users (UserRole.history)
    """
    if user.role not in (UserRole.admin, UserRole.driver, UserRole.history):
        raise HTTPException(status_code=403, detail="History access required")
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
