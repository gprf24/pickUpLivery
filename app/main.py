# app/main.py
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.db_inspect import router as db_router  # <-- ADD
from app.api.v1.pages import router as pages_router
from app.api.v1.pickups import router as pickups_router
from app.db.migrations import run_minimal_migrations

# DB init only; we will wire routers later
from app.db.session import get_engine, init_db

# -----------------------------------------------------------------------------
# Logging: make sure we see clear startup errors in the console
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("app")

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(title="PickUp Livery", debug=os.getenv("DEBUG") == "1")

# -----------------------------------------------------------------------------
# Static files (guard against missing directory)
# -----------------------------------------------------------------------------
# Compute absolute path to app/static based on this file location
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Ensure the directory exists (avoid Starlette error at mount time)
# If you don't want auto-create, replace with: if not STATIC_DIR.exists(): raise ...
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Mount /static → app/static
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(db_router, prefix="/api/v1", tags=["db"])
app.include_router(pickups_router, include_in_schema=False)

# app.include_router(admin_router, include_in_schema=False)
app.include_router(admin_router, tags=["admin"])
app.include_router(pages_router, include_in_schema=False)

app.include_router(auth_router, include_in_schema=False)


# -----------------------------------------------------------------------------
# Startup: create tables if missing, but never crash the app on error.
# We log the error so /ping still works and you can debug via console.
# -----------------------------------------------------------------------------
@app.on_event("startup")
def _startup() -> None:
    try:
        init_db()  # creates tables if missing
        # run idempotent migrations (adds columns if missing)
        run_minimal_migrations(get_engine())
        log.info("DB init + minimal migrations completed.")
    except Exception as e:
        log.exception("DB init/migrations failed: %s", e)


# -----------------------------------------------------------------------------
# Minimal health endpoint
# -----------------------------------------------------------------------------
@app.get("/ping")
def ping():
    """Simple liveness check."""
    return {"ok": True}


from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.deps import templates


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request, exc):
    """Custom 404 and generic HTTP error pages rendered via Jinja templates."""
    # 404 page
    if exc.status_code == 404:
        return templates.TemplateResponse(
            "404.html",
            {"request": request, "path": request.url.path},
            status_code=404,
        )
    # other HTTP errors
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    """Nice page for validation errors (422)."""
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "code": 422,
            "detail": "Validation error",
            "errors": exc.errors(),
        },
        status_code=422,
    )


# # app/main.py
# # Keep it simple: home + health + DB inspection routes.

# import os

# from fastapi import FastAPI

# from app.api.v1.db_inspect import router as db_router
# from app.api.v1.health import router as health_router

# app = FastAPI(title="PickUp Livery (DB inspect)", debug=os.getenv("DEBUG") == "1")


# @app.get("/")
# def home():
#     return {"status": "ok", "message": "app is running"}


# # API v1
# app.include_router(health_router, prefix="/api/v1", tags=["health"])
# app.include_router(db_router, prefix="/api/v1", tags=["db"])


# @app.get("/ping")
# def ping():
#     return {"ok": True}
#     return {"ok": True}
#     return {"ok": True}
#     return {"ok": True}
