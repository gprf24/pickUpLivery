from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.core.deps import get_current_user, get_session, templates
from app.core.security import verify_password
from app.db.models.user import User, UserRole

router = APIRouter()


# ---------------------- LOGIN (GET) ----------------------
@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: str | None = Query(None),
    session: Session = Depends(get_session),
):
    """
    Render login form.

    Behaviour:
      - If user already has a valid auth cookie (user_id) and the user exists in DB,
        we immediately redirect them away from /login (no need to see the form).
      - If ?next=/somepage is supplied and the user is already logged in, we respect
        that and redirect to ?next.
      - Otherwise we render the login page as usual.
    """

    # Try to read existing auth cookie (if any).
    user_id_cookie = request.cookies.get("user_id")

    if user_id_cookie:
        try:
            user_id = int(user_id_cookie)
        except ValueError:
            # Malformed cookie → ignore it and just show the login page.
            user_id = None

        if user_id is not None:
            # Look up user in DB.
            user = session.exec(select(User).where(User.id == user_id)).first()

            if user:
                # If user is already authenticated, decide where to send them:
                # 1) If ?next=... is present, prefer that.
                # 2) Otherwise role-based redirect (same logic as in POST /login).
                if next:
                    target = next
                else:
                    if user.role == UserRole.history:
                        target = "/history"
                    elif user.role == UserRole.admin:
                        target = "/history"
                    else:
                        # Drivers (and any future non-history, non-admin roles)
                        # land on /tasks as their main working page.
                        target = "/tasks"

                return RedirectResponse(url=target, status_code=303)

    # No valid cookie or user not found → render login form.
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
            "next": next or "",
        },
    )


# ---------------------- LOGIN (POST) ----------------------
@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    next_url: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """
    Authenticate user; on failure, return login form with error.
    On success:
        - set auth cookie
        - redirect history-only → /history
        - redirect admin       → /history
        - redirect driver      → /tasks
        - or redirect to ?next=... (if supplied)

    Note:
      We don't strictly need to check "already logged in" here, because
      GET /login already handles that scenario. If a logged-in user
      manually POSTs to /login again, we simply treat it as a normal
      re-auth attempt.
    """

    # Lookup user by login.
    user = session.exec(select(User).where(User.login == login)).first()

    # Invalid login or password.
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "❌ Invalid username or password.",
                "login_value": login,
                "next": next_url or "",
            },
            status_code=401,
        )

    # Determine redirect target:
    # - If next was requested → use it as-is.
    # - Otherwise role-based redirect.
    if next_url:
        target = next_url
    else:
        # History-only users must never land on /tasks by default.
        if user.role == UserRole.history:
            target = "/history"
        elif user.role == UserRole.admin:
            target = "/history"
        else:
            # Drivers (and any other future non-history, non-admin roles)
            # land on tasks as their main working page.
            target = "/tasks"

    # Build redirect response.
    resp = RedirectResponse(url=target, status_code=303)

    # Set secure auth cookie with user_id.
    # IMPORTANT:
    #   - secure=False is fine for local development.
    #   - In production (HTTPS), set secure=True!
    resp.set_cookie(
        key="user_id",
        value=str(user.id),
        httponly=True,
        samesite="lax",
        secure=False,  # set True when behind HTTPS
        path="/",
        max_age=60 * 60 * 24 * 30,  # 30 days
    )
    return resp


# ---------------------- LOGOUT ----------------------
@router.get("/logout")
def logout():
    """
    Remove auth cookie and redirect to login.

    We simply delete the "user_id" cookie and then send the user
    back to /login.
    """
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("user_id", path="/")
    return resp


# ---------------------- WHO AM I ----------------------
@router.get("/me")
def whoami(user: User = Depends(get_current_user)):
    """
    Return current authenticated user details.

    This is a simple helper endpoint that shows which user the backend
    sees as "current", based on the auth cookie.
    """
    return {
        "id": user.id,
        "login": user.login,
        "role": user.role,
    }
