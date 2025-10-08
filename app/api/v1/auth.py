# app/api/v1/auth.py
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.core.deps import get_session, templates
from app.core.security import verify_password
from app.db.models.user import User

router = APIRouter()


# ---------------------- LOGIN (GET + POST) ----------------------
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Render login form."""
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    """Authenticate user; on failure, show same form with error."""
    user = session.exec(select(User).where(User.login == login)).first()

    if not user or not verify_password(password, user.password_hash):
        # Render login form again with error message
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "❌ Invalid username or password.",
                "login_value": login,
            },
            status_code=401,
        )

    # success → set cookie and redirect
    resp = RedirectResponse(url="/tasks", status_code=303)
    resp.set_cookie(key="user_id", value=str(user.id), httponly=True, samesite="lax")
    return resp


# ---------------------- LOGOUT ----------------------
@router.get("/logout")
def logout():
    """Remove auth cookie and redirect to login."""
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("user_id")
    return resp


# ---------------------- Optional: /me ----------------------
@router.get("/me")
def whoami(user: User = Depends(get_session)):
    return {"id": user.id, "login": user.login}
