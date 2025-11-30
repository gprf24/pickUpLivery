# app/main.py
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.db_inspect import router as db_router
from app.api.v1.health import router as health_router
from app.api.v1.pages import router as pages_router
from app.api.v1.pickups import router as pickups_router
from app.core.deps import templates
from app.db.migrations import run_minimal_migrations
from app.db.session import get_engine, init_db

# -----------------------------------------------------------------------------
# Logging: make sure we see clear startup errors in the console
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
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

# -----------------------------------------------------------------------------
# Routers
# -----------------------------------------------------------------------------
# Health / DB inspect
app.include_router(health_router, prefix="/api/v1", tags=["health"])
app.include_router(db_router, prefix="/api/v1", tags=["db"])

# Core app routes
app.include_router(pickups_router, include_in_schema=False)
app.include_router(admin_router, tags=["admin"])
app.include_router(pages_router, include_in_schema=False)
app.include_router(auth_router, include_in_schema=False)


# -----------------------------------------------------------------------------
# Startup: create tables if missing (non-destructive) + minimal migrations
# -----------------------------------------------------------------------------
@app.on_event("startup")
def _startup() -> None:
    """
    On startup, ensure that all SQLModel tables exist and run minimal migrations.

    - init_db() calls SQLModel.metadata.create_all(engine):
        * creates missing tables,
        * does NOT drop or alter existing tables.
    - run_minimal_migrations(engine) then adds new columns on existing tables
      in an idempotent way (ADD COLUMN IF NOT EXISTS, etc.).

    This combination:
      * works for fresh databases (tables created with all current columns),
      * and for existing databases (missing columns are added via migrations).
    """
    try:
        engine = get_engine()
        init_db()
        run_minimal_migrations(engine)
        log.info("DB init + minimal migrations completed.")
    except Exception as e:
        # Never crash the app on init errors — log and allow /ping to work.
        log.exception("DB init or migrations failed: %s", e)


# -----------------------------------------------------------------------------
# Minimal health endpoint
# -----------------------------------------------------------------------------
@app.get("/ping")
def ping():
    """Simple liveness check."""
    return {"ok": True}


# -----------------------------------------------------------------------------
# Exception handlers
# -----------------------------------------------------------------------------
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
