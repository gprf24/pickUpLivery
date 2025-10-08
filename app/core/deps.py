# Common dependencies (session, current user, admin guard) + templates.
from typing import Generator

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.core.security import hash_password
from app.db.models.user import User, UserRole
from app.db.session import get_engine

# Jinja templates (adjust path if your templates/ lives elsewhere)
templates = Jinja2Templates(directory="app/templates")


def get_session() -> Generator[Session, None, None]:
    """Provide a SQLModel session for each request."""
    engine = get_engine()
    with Session(engine) as session:
        yield session


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """
    Detect current user based on cookie "user_id".
    Falls back to bootstrap admin if DB empty.
    """
    # 1. Try to read user_id from cookies (set by /login)
    user_id = request.cookies.get("user_id")
    if user_id:
        user = session.get(User, int(user_id))
        if user and user.is_active:
            return user

    # 2. If no users exist at all → bootstrap admin:admin
    total_users = session.exec(select(User)).all()
    if not total_users:
        admin = User(
            login="admin",
            password_hash=hash_password("admin"),
            role=UserRole.admin,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        return admin

    # 3. Otherwise unauthorized
    raise HTTPException(status_code=401, detail="Not logged in")


def require_admin(user: User) -> User:
    """Guard: only admins allowed."""
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
