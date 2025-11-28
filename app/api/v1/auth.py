from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.core.deps import get_current_user, get_session, templates
from app.core.security import verify_password
from app.db.models.user import User

router = APIRouter()


# ---------------------- LOGIN (GET) ----------------------
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str | None = Query(None)):
    """
    Render login form.

    If ?next=/somepage is supplied, keep it and submit with form.
    """
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
        - redirect admin → /history
        - redirect driver → /tasks
        - or redirect to ?next=...
    """
    user = session.exec(select(User).where(User.login == login)).first()

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
    # - If next was requested → use it.
    # - Otherwise role-based redirect.
    if next_url:
        target = next_url
    else:
        if getattr(user, "role", None) == "admin":
            target = "/history"
        else:
            target = "/tasks"

    resp = RedirectResponse(url=target, status_code=303)

    # Secure cookie
    resp.set_cookie(
        key="user_id",
        value=str(user.id),
        httponly=True,
        samesite="lax",
        secure=False,  # set True in HTTPS
        path="/",
        max_age=60 * 60 * 24 * 30,  # 30 days
    )
    return resp


# ---------------------- LOGOUT ----------------------
@router.get("/logout")
def logout():
    """Remove auth cookie and redirect to login."""
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("user_id", path="/")
    return resp


# ---------------------- WHO AM I ----------------------
@router.get("/me")
def whoami(user: User = Depends(get_current_user)):
    """Return current authenticated user details."""
    return {
        "id": user.id,
        "login": user.login,
        "role": user.role,
    }
