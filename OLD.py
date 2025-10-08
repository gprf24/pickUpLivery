# ===================== Imports & Config (PostgreSQL only) =====================
import os
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from sqlalchemy import UniqueConstraint, text
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine, select

load_dotenv()

# IMPORTANT: Only Postgres. No SQLite, no filesystem writes.

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"
load_dotenv(dotenv_path=ENV_PATH)

DATABASE_URL = os.getenv("PG_CONN_STR")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)

app = FastAPI(title="PickUp Livery")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ===================== Roles & Auth helpers =====================
class UserRole(str, Enum):
    # Only two roles as requested
    admin = "admin"
    driver = "driver"


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ===================== ORM Models (SQLModel) =====================
class UserPharmacyLink(SQLModel, table=True):
    """Many-to-many link between users and pharmacies."""

    __tablename__ = "PP_user_pharmacy_link"
    user_id: int = Field(foreign_key="PP_user.id", primary_key=True)
    pharmacy_id: int = Field(foreign_key="PP_pharmacy.id", primary_key=True)


class User(SQLModel, table=True):
    __tablename__ = "PP_user"
    id: Optional[int] = Field(default=None, primary_key=True)
    # FIX: remove sa_column; index is fine alone
    login: str = Field(index=True)
    password_hash: str
    role: UserRole = Field(default=UserRole.driver, index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    # Relations
    pharmacies: List["Pharmacy"] = Relationship(
        back_populates="users", link_model=UserPharmacyLink
    )

    __table_args__ = (UniqueConstraint("login", name="uq_pp_user_login"),)


class Region(SQLModel, table=True):
    __tablename__ = "PP_region"
    id: Optional[int] = Field(default=None, primary_key=True)
    # Natural unique key is name (case-insensitive enforced by app logic and unique constraint)
    name: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    pharmacies: List["Pharmacy"] = Relationship(back_populates="region")

    __table_args__ = (UniqueConstraint("name", name="uq_pp_region_name"),)


class Pharmacy(SQLModel, table=True):
    __tablename__ = "PP_pharmacy"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    region_id: int = Field(foreign_key="PP_region.id", index=True)
    address: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    region: Optional[Region] = Relationship(back_populates="pharmacies")
    users: List[User] = Relationship(
        back_populates="pharmacies", link_model=UserPharmacyLink
    )

    __table_args__ = (
        # Prevent duplicates per (region, name)
        UniqueConstraint("region_id", "name", name="uq_pp_pharmacy_region_name"),
    )


class Pickup(SQLModel, table=True):
    __tablename__ = "PP_pickup"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="PP_user.id", index=True)
    pharmacy_id: int = Field(foreign_key="PP_pharmacy.id", index=True)

    # Store the image in DB as BYTEA; no disk I/O
    image_bytes: Optional[bytes] = Field(default=None, description="Binary image data")
    image_mime: Optional[str] = Field(
        default=None, description="MIME type, e.g., image/jpeg"
    )
    original_filename: Optional[str] = None

    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# ===================== DB Init =====================
def init_db() -> None:
    """Create tables if they don't exist."""
    SQLModel.metadata.create_all(engine)


@app.on_event("startup")
def on_startup():
    init_db()


# ===================== Session Dependency =====================
def get_session():
    with Session(engine) as session:
        yield session


# ===================== Minimal Auth (bootstrap) =====================
# NOTE: Replace with real session/cookie auth later.
def get_current_user(session: Session = Depends(get_session)) -> User:
    """
    Temporary: return first active user; if none, bootstrap a default admin.
    Replace with real auth for production.
    """
    user = session.exec(select(User).where(User.is_active == True)).first()
    if user:
        return user
    admin = User(
        login="admin", password_hash=hash_password("admin"), role=UserRole.admin
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    return admin


def require_admin(user: User) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


# ===================== De-duplication & Diagnostics =====================
def dedup_regions(session: Session) -> int:
    """Collapse duplicate regions by lower(name); keep the oldest id."""
    dup_rows = session.exec(
        text(
            """
        WITH norm AS (
            SELECT id, LOWER(TRIM(name)) AS nname, created_at
            FROM "PP_region"
        ),
        dups AS (
            SELECT nname, MIN(id) AS keep_id, ARRAY_AGG(id ORDER BY id) AS ids
            FROM norm
            GROUP BY nname
            HAVING COUNT(*) > 1
        )
        SELECT nname, keep_id, ids FROM dups
        """
        )
    ).all()

    removed = 0
    for _, keep_id, ids in dup_rows:
        to_delete = [i for i in ids if i != keep_id]
        if not to_delete:
            continue

        # Re-point pharmacies to the kept region
        session.exec(
            text(
                """
            UPDATE "PP_pharmacy" SET region_id = :keep_id
            WHERE region_id = ANY(:to_delete)
            """
            ),
            {"keep_id": keep_id, "to_delete": to_delete},
        )

        # Delete duplicate regions
        session.exec(
            text("""DELETE FROM "PP_region" WHERE id = ANY(:to_delete)"""),
            {"to_delete": to_delete},
        )
        removed += len(to_delete)

    session.commit()
    return removed


def dedup_pharmacies(session: Session) -> int:
    """Collapse duplicate pharmacies by (region_id, lower(name)); keep the oldest id."""
    dup_rows = session.exec(
        text(
            """
        WITH norm AS (
            SELECT id, region_id, LOWER(TRIM(name)) AS nname, created_at
            FROM "PP_pharmacy"
        ),
        dups AS (
            SELECT region_id, nname, MIN(id) AS keep_id, ARRAY_AGG(id ORDER BY id) AS ids
            FROM norm
            GROUP BY region_id, nname
            HAVING COUNT(*) > 1
        )
        SELECT region_id, nname, keep_id, ids FROM dups
        """
        )
    ).all()

    removed = 0
    for _, _, keep_id, ids in dup_rows:
        to_delete = [i for i in ids if i != keep_id]
        if not to_delete:
            continue

        # Re-point pickups to the kept pharmacy
        session.exec(
            text(
                """
            UPDATE "PP_pickup" SET pharmacy_id = :keep_id
            WHERE pharmacy_id = ANY(:to_delete)
            """
            ),
            {"keep_id": keep_id, "to_delete": to_delete},
        )

        # Re-point user links, avoid duplicates
        session.exec(
            text(
                """
            UPDATE "PP_user_pharmacy_link" upl
            SET pharmacy_id = :keep_id
            WHERE pharmacy_id = ANY(:to_delete)
              AND NOT EXISTS (
                  SELECT 1 FROM "PP_user_pharmacy_link" x
                  WHERE x.user_id = upl.user_id AND x.pharmacy_id = :keep_id
              )
            """
            ),
            {"keep_id": keep_id, "to_delete": to_delete},
        )

        # Remove leftover links and pharmacies
        session.exec(
            text(
                """DELETE FROM "PP_user_pharmacy_link" WHERE pharmacy_id = ANY(:to_delete)"""
            ),
            {"to_delete": to_delete},
        )
        session.exec(
            text("""DELETE FROM "PP_pharmacy" WHERE id = ANY(:to_delete)"""),
            {"to_delete": to_delete},
        )

        removed += len(to_delete)

    session.commit()
    return removed


def db_health(session: Session) -> dict:
    """Return counts and duplicate groups for main tables."""
    counts = {}
    for tbl in [
        "PP_user",
        "PP_region",
        "PP_pharmacy",
        "PP_pickup",
        "PP_user_pharmacy_link",
    ]:
        n = session.exec(text(f'SELECT COUNT(*) FROM "{tbl}"')).one()[0]
        counts[tbl] = n

    dup_regions = session.exec(
        text(
            """
        SELECT LOWER(TRIM(name)) AS nname, COUNT(*) AS c
        FROM "PP_region"
        GROUP BY LOWER(TRIM(name))
        HAVING COUNT(*) > 1
        ORDER BY c DESC
        """
        )
    ).all()

    dup_pharm = session.exec(
        text(
            """
        SELECT region_id, LOWER(TRIM(name)) AS nname, COUNT(*) AS c
        FROM "PP_pharmacy"
        GROUP BY region_id, LOWER(TRIM(name))
        HAVING COUNT(*) > 1
        ORDER BY c DESC
        """
        )
    ).all()

    return {"counts": counts, "dup_regions": dup_regions, "dup_pharmacies": dup_pharm}


# ===================== Pages (match your templates structure) =====================
@app.get("/", response_class=HTMLResponse)
def root_to_tasks(request: Request, user: User = Depends(get_current_user)):
    """Home route -> render tasks.html from templates root."""
    return templates.TemplateResponse("tasks.html", {"request": request, "user": user})


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request, user: User = Depends(get_current_user)):
    """Explicit tasks route."""
    return templates.TemplateResponse("tasks.html", {"request": request, "user": user})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Render login page (placeholder; real auth not implemented here)."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/pickup", response_class=HTMLResponse)
def pickup_form(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Pickup form page; load regions/pharmacies for selection if needed."""
    regions = session.exec(select(Region).order_by(Region.name)).all()
    pharmacies = session.exec(select(Pharmacy).order_by(Pharmacy.name)).all()
    return templates.TemplateResponse(
        "pickup.html",
        {
            "request": request,
            "user": user,
            "regions": regions,
            "pharmacies": pharmacies,
        },
    )


@app.get("/success", response_class=HTMLResponse)
def success_page(request: Request, user: User = Depends(get_current_user)):
    """Generic success page."""
    return templates.TemplateResponse(
        "success.html", {"request": request, "user": user}
    )


@app.get("/history", response_class=HTMLResponse)
def history_page(
    request: Request,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    region_id: Optional[int] = None,
    pharmacy_id: Optional[int] = None,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """History page with clean filters: dates, region, pharmacy only."""
    stmt = (
        select(Pickup, Pharmacy, Region, User)
        .join(Pharmacy, Pharmacy.id == Pickup.pharmacy_id)
        .join(Region, Region.id == Pharmacy.region_id)
        .join(User, User.id == Pickup.user_id)
        .order_by(Pickup.created_at.desc())
    )

    if start_date:
        stmt = stmt.where(
            Pickup.created_at >= datetime.combine(start_date, datetime.min.time())
        )
    if end_date:
        stmt = stmt.where(
            Pickup.created_at <= datetime.combine(end_date, datetime.max.time())
        )
    if region_id:
        stmt = stmt.where(Region.id == region_id)
    if pharmacy_id:
        stmt = stmt.where(Pharmacy.id == pharmacy_id)

    rows = session.exec(stmt).all()
    regions = session.exec(select(Region).order_by(Region.name)).all()
    pharmacies = []
    if region_id:
        pharmacies = session.exec(
            select(Pharmacy)
            .where(Pharmacy.region_id == region_id)
            .order_by(Pharmacy.name)
        ).all()

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "user": user,
            "rows": rows,
            "filters": {
                "start_date": start_date.isoformat() if start_date else "",
                "end_date": end_date.isoformat() if end_date else "",
                "region_id": region_id or "",
                "pharmacy_id": pharmacy_id or "",
            },
            "regions": regions,
            "pharmacies": pharmacies,
        },
    )


# ===================== Admin (templates/admin/home.html) =====================
@app.get("/admin", response_class=HTMLResponse)
def admin_home(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Admin dashboard landing."""
    require_admin(user)
    stats = db_health(session)["counts"]
    regions = session.exec(select(Region).order_by(Region.name)).all()
    return templates.TemplateResponse(
        "admin/home.html",
        {"request": request, "user": user, "stats": stats, "regions": regions},
    )


@app.get("/admin/history", response_class=HTMLResponse)
def admin_history_page(
    request: Request,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    region_id: Optional[int] = None,
    pharmacy_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """Admin history with same clean filters."""
    require_admin(current)

    stmt = (
        select(Pickup, Pharmacy, Region, User)
        .join(Pharmacy, Pharmacy.id == Pickup.pharmacy_id)
        .join(Region, Region.id == Pharmacy.region_id)
        .join(User, User.id == Pickup.user_id)
        .order_by(Pickup.created_at.desc())
    )

    if start_date:
        stmt = stmt.where(
            Pickup.created_at >= datetime.combine(start_date, datetime.min.time())
        )
    if end_date:
        stmt = stmt.where(
            Pickup.created_at <= datetime.combine(end_date, datetime.max.time())
        )
    if region_id:
        stmt = stmt.where(Region.id == region_id)
    if pharmacy_id:
        stmt = stmt.where(Pharmacy.id == pharmacy_id)

    rows = session.exec(stmt).all()
    regions = session.exec(select(Region).order_by(Region.name)).all()
    pharmacies = []
    if region_id:
        pharmacies = session.exec(
            select(Pharmacy)
            .where(Pharmacy.region_id == region_id)
            .order_by(Pharmacy.name)
        ).all()

    return templates.TemplateResponse(
        "history.html",  # reuse same template if you don't have a separate admin/history.html
        {
            "request": request,
            "user": current,
            "rows": rows,
            "filters": {
                "start_date": start_date.isoformat() if start_date else "",
                "end_date": end_date.isoformat() if end_date else "",
                "region_id": region_id or "",
                "pharmacy_id": pharmacy_id or "",
            },
            "regions": regions,
            "pharmacies": pharmacies,
        },
    )


# ---------- Admin: CRUD & tools ----------
@app.post("/admin/users", response_class=RedirectResponse)
def admin_create_user(
    login: str = Form(...),
    password: str = Form(...),
    role: UserRole = Form(UserRole.driver),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """Create a new user; login must be unique."""
    require_admin(current)
    exists = session.exec(select(User).where(User.login == login)).first()
    if exists:
        raise HTTPException(status_code=400, detail="Login already exists")
    u = User(login=login, password_hash=hash_password(password), role=role)
    session.add(u)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users/{user_id}/password", response_class=RedirectResponse)
def admin_change_user_password(
    user_id: int,
    new_password: str = Form(..., min_length=6),
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """Admin can set a new password for any user."""
    require_admin(current)
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.password_hash = hash_password(new_password)
    session.add(u)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users/{user_id}/toggle", response_class=RedirectResponse)
def admin_toggle_active(
    user_id: int,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
):
    """Activate/Deactivate a user."""
    require_admin(current)
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.is_active = not u.is_active
    session.add(u)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/regions", response_class=RedirectResponse)
def admin_create_region(
    name: str = Form(...),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Create region; unique by name (case-insensitive check in app)."""
    require_admin(user)
    exists = session.exec(select(Region).where(Region.name.ilike(name))).first()
    if exists:
        raise HTTPException(status_code=400, detail="Region already exists")
    r = Region(name=name.strip())
    session.add(r)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/pharmacies", response_class=RedirectResponse)
def admin_create_pharmacy(
    name: str = Form(...),
    region_id: int = Form(...),
    address: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Create pharmacy; unique per (region_id, name)."""
    require_admin(user)
    exists = session.exec(
        select(Pharmacy).where(
            Pharmacy.region_id == region_id, Pharmacy.name.ilike(name)
        )
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Pharmacy already exists in region")
    p = Pharmacy(name=name.strip(), region_id=region_id, address=address)
    session.add(p)
    session.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/dedup")
def admin_run_dedup(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Run de-duplication for regions and pharmacies."""
    require_admin(user)
    r = dedup_regions(session)
    p = dedup_pharmacies(session)
    return {"removed_regions": r, "removed_pharmacies": p}


@app.get("/admin/db-check")
def admin_db_check(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Quick DB health snapshot: counts and duplicate groups."""
    require_admin(user)
    return db_health(session)


# ===================== Pickups API (no filesystem) =====================
@app.post("/pickup")
async def create_pickup(
    pharmacy_id: int = Form(...),
    note: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Create a pickup; store optional photo in DB (BYTEA)."""
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")

    image_bytes = None
    image_mime = None
    original_filename = None

    if photo:
        content = await photo.read()  # read entire file into memory
        image_bytes = content
        image_mime = photo.content_type
        original_filename = photo.filename

    pk = Pickup(
        user_id=user.id,
        pharmacy_id=pharmacy_id,
        note=note,
        image_bytes=image_bytes,
        image_mime=image_mime,
        original_filename=original_filename,
    )
    session.add(pk)
    session.commit()
    session.refresh(pk)
    return {"id": pk.id, "created_at": pk.created_at.isoformat()}


# ===================== Misc =====================
@app.get("/ping")
def ping():
    return {"ok": True}


# ===================== Notes =====================
# - Templates expected:
#     templates/
#       base.html
#       history.html
#       login.html
#       pickup.html
#       success.html
#       tasks.html
#       admin/
#         home.html
# - Photos are stored as BYTEA (image_bytes) with image_mime; no disk writes.
# - Uniqueness:
#     Region: UNIQUE(name)
#     Pharmacy: UNIQUE(region_id, name)
#     User: UNIQUE(login)
# - /admin/dedup collapses duplicates safely, re-pointing FKs.
# - History/Admin filters: start_date, end_date, region_id, pharmacy_id only.
# - Admin can change passwords via POST /admin/users/{user_id}/password.
# - Authentication is minimal bootstrap; integrate real auth later.
