import os
import pathlib
import shutil
from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer
from passlib.hash import pbkdf2_sha256 as hasher
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine, select

# ===================== Config =====================
DB_URL = "sqlite:///./pickup.db"
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

BASE_DIR = pathlib.Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


# ===================== Models =====================
class UserRole(str, Enum):
    admin = "admin"
    driver = "driver"


class UserPharmacyLink(SQLModel, table=True):
    user_id: Optional[int] = Field(
        default=None, foreign_key="user.id", primary_key=True
    )
    pharmacy_id: Optional[int] = Field(
        default=None, foreign_key="pharmacy.id", primary_key=True
    )


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    full_name: Optional[str] = None
    role: UserRole = Field(default=UserRole.driver, index=True)
    is_active: bool = Field(default=True, index=True)
    pharmacies: List["Pharmacy"] = Relationship(
        back_populates="users", link_model=UserPharmacyLink
    )


class Region(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    code: Optional[str] = None


class Pharmacy(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    region_id: Optional[int] = Field(default=None, foreign_key="region.id", index=True)
    address: Optional[str] = None
    users: List[User] = Relationship(
        back_populates="pharmacies", link_model=UserPharmacyLink
    )


class Pickup(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    pharmacy_id: int = Field(foreign_key="pharmacy.id")
    image_path: str  # храним только имя файла
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    status: str = Field(default="finished")  # finished | missed


# ===================== App & templating =====================
app = FastAPI(title="Pickup Proof MVP", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
serializer = URLSafeSerializer(SECRET_KEY, salt="session")


# ===================== DB init (seed) =====================
def init_db():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        if not s.exec(select(User)).first():
            admin = User(
                email="admin@example.com",
                password_hash=hasher.hash("admin123"),
                full_name="Admin",
                role=UserRole.admin,
                is_active=True,
            )
            driver = User(
                email="driver@example.com",
                password_hash=hasher.hash("test123"),
                full_name="Demo Driver",
                role=UserRole.driver,
                is_active=True,
            )
            s.add_all([admin, driver])
            s.commit()

            hh = Region(name="Hamburg", code="HH")
            s.add(hh)
            s.commit()

            ph1 = Pharmacy(name="Apotheke Altona", region_id=hh.id, address="Altona")
            ph2 = Pharmacy(
                name="Apotheke Eimsbüttel", region_id=hh.id, address="Eimsbüttel"
            )
            ph3 = Pharmacy(
                name="Apotheke Wandsbek", region_id=hh.id, address="Wandsbek"
            )
            s.add_all([ph1, ph2, ph3])
            s.commit()

            s.add_all(
                [
                    UserPharmacyLink(user_id=driver.id, pharmacy_id=ph1.id),
                    UserPharmacyLink(user_id=driver.id, pharmacy_id=ph2.id),
                    UserPharmacyLink(user_id=driver.id, pharmacy_id=ph3.id),
                ]
            )
            s.commit()


init_db()

# ===================== Auth helpers =====================
COOKIE_NAME = "pickup_session"


async def get_current_user(request: Request) -> Optional[User]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        data = serializer.loads(token)
        uid = data.get("uid")
    except Exception:
        return None
    if not uid:
        return None
    with Session(engine) as s:
        u = s.get(User, uid)
        if not u or not u.is_active:
            return None
        return u


def require_user(user: Optional[User]) -> User:
    if not user:
        raise HTTPException(403, "Not authenticated")
    if not user.is_active:
        raise HTTPException(403, "User is inactive")
    return user


def require_admin(user: Optional[User]) -> User:
    u = require_user(user)
    if u.role != UserRole.admin:
        raise HTTPException(403, "Admin only")
    return u


# ===================== Global guard (except public/static) =====================
PUBLIC_PATHS = {"/login", "/openapi.json", "/docs", "/redoc"}


def _is_public(path: str) -> bool:
    return (
        path in PUBLIC_PATHS
        or path.startswith("/static")
        or path.startswith("/uploads")
        or path.startswith("/.well-known")
        or path == "/favicon.ico"
    )


@app.middleware("http")
async def auth_guard(request, call_next):
    path = request.url.path
    if _is_public(path):
        return await call_next(request)
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    request.state.user = user
    return await call_next(request)


# ===================== Public: login/logout =====================
@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse(
        "login.html", {"request": request, "user": None, "error": None}
    )


@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    with Session(engine) as s:
        user = s.exec(select(User).where(User.email == email)).first()
        if (
            not user
            or not hasher.verify(password, user.password_hash)
            or not user.is_active
        ):
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "user": None, "error": "Invalid credentials"},
            )
    token = serializer.dumps({"uid": user.id, "ts": datetime.utcnow().timestamp()})
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax")
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# заглушка, чтобы DevTools не спамил 404
@app.get("/.well-known/{path:path}")
async def well_known_stub(path: str):
    return {}


# ===================== Driver UI =====================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user: User = Depends(get_current_user)):
    user = require_user(user)
    with Session(engine) as s:
        q = (
            select(Pharmacy)
            .join(UserPharmacyLink, UserPharmacyLink.pharmacy_id == Pharmacy.id)
            .where(UserPharmacyLink.user_id == user.id)
            .order_by(Pharmacy.name)
        )
        pharmacies = s.exec(q).all()
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "user": user, "pharmacies": pharmacies}
    )


@app.get("/pickup/{pharmacy_id}", response_class=HTMLResponse)
async def pickup_form(
    pharmacy_id: int, request: Request, user: User = Depends(get_current_user)
):
    user = require_user(user)
    with Session(engine) as s:
        ph = s.get(Pharmacy, pharmacy_id)
        if not ph:
            raise HTTPException(404, "Pharmacy not found")
        # безопасность: доступ только к своим аптекам (кроме админа)
        link = s.exec(
            select(UserPharmacyLink).where(
                UserPharmacyLink.user_id == user.id,
                UserPharmacyLink.pharmacy_id == pharmacy_id,
            )
        ).first()
        if not link and user.role != UserRole.admin:
            raise HTTPException(403, "No access to this pharmacy")
    return templates.TemplateResponse(
        "pickup.html", {"request": request, "user": user, "pharmacy": ph, "error": None}
    )


@app.post("/pickup/{pharmacy_id}")
async def pickup_submit(
    pharmacy_id: int,
    request: Request,
    image: UploadFile = File(...),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
    user: User = Depends(get_current_user),
):
    user = require_user(user)
    if lat is None or lon is None:
        # Не даём сохранять без геолокации
        with Session(engine) as s:
            ph = s.get(Pharmacy, pharmacy_id)
        return templates.TemplateResponse(
            "pickup.html",
            {
                "request": request,
                "user": user,
                "pharmacy": ph,
                "error": "Please capture location first.",
            },
        )

    # сохраняем файл как имя (без абсолютного пути)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = f"u{user.id}_p{pharmacy_id}_{stamp}_{image.filename.replace(' ', '_')}"
    dst = UPLOAD_DIR / safe_name
    with dst.open("wb") as f:
        shutil.copyfileobj(image.file, f)

    with Session(engine) as s:
        ph = s.get(Pharmacy, pharmacy_id)
        if not ph:
            raise HTTPException(404, "Pharmacy not found")
        rec = Pickup(
            user_id=user.id,
            pharmacy_id=pharmacy_id,
            image_path=safe_name,
            latitude=lat,
            longitude=lon,
            status="finished",
        )
        s.add(rec)
        s.commit()

    return RedirectResponse(url=f"/pickup/success/{pharmacy_id}", status_code=302)


@app.get("/pickup/success/{pharmacy_id}", response_class=HTMLResponse)
async def pickup_success(
    pharmacy_id: int, request: Request, user: User = Depends(get_current_user)
):
    user = require_user(user)
    return templates.TemplateResponse(
        "success.html", {"request": request, "user": user, "pharmacy_id": pharmacy_id}
    )


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request, user: User = Depends(get_current_user)):
    user = require_user(user)
    with Session(engine) as s:
        q = (
            select(Pickup, Pharmacy)
            .join(Pharmacy, Pickup.pharmacy_id == Pharmacy.id)
            .where(Pickup.user_id == user.id)
            .order_by(Pickup.created_at.desc())
            .limit(200)
        )
        rows = s.exec(q).all()
    return templates.TemplateResponse(
        "history.html", {"request": request, "user": user, "rows": rows}
    )


@app.get("/file/{fname}")
async def file_serve(fname: str):
    path = UPLOAD_DIR / fname
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path)


@app.post("/admin/close-day")
async def close_day():
    today = date.today()
    with Session(engine) as s:
        pharmacies = s.exec(select(Pharmacy)).all()
        for ph in pharmacies:
            picked = s.exec(
                select(Pickup)
                .where(Pickup.pharmacy_id == ph.id)
                .where(
                    Pickup.created_at >= datetime(today.year, today.month, today.day)
                )
            ).first()
            if not picked:
                s.add(
                    Pickup(user_id=0, pharmacy_id=ph.id, image_path="", status="missed")
                )
        s.commit()
    return {"ok": True}


# ===================== Admin UI & actions =====================
@app.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request, user: User = Depends(get_current_user)):
    admin = require_admin(user)
    with Session(engine) as s:
        users = s.exec(select(User).order_by(User.role, User.email)).all()
        regions = s.exec(select(Region).order_by(Region.name)).all()
        pharmacies = s.exec(select(Pharmacy).order_by(Pharmacy.name)).all()
        links = s.exec(select(UserPharmacyLink)).all()
    return templates.TemplateResponse(
        "admin/home.html",
        {
            "request": request,
            "user": admin,
            "users": users,
            "regions": regions,
            "pharmacies": pharmacies,
            "links": links,
        },
    )


@app.post("/admin/users/create")
async def admin_users_create(
    email: str = Form(...),
    full_name: str = Form(""),
    role: UserRole = Form(UserRole.driver),
    password: str = Form(...),
    user: User = Depends(get_current_user),
):
    require_admin(user)
    with Session(engine) as s:
        if s.exec(select(User).where(User.email == email)).first():
            raise HTTPException(400, "Email already exists")
        u = User(
            email=email,
            full_name=full_name or None,
            role=role,
            is_active=True,
            password_hash=hasher.hash(password),
        )
        s.add(u)
        s.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users/{uid}/toggle")
async def admin_users_toggle(uid: int, user: User = Depends(get_current_user)):
    admin = require_admin(user)
    with Session(engine) as s:
        u = s.get(User, uid)
        if not u:
            raise HTTPException(404, "User not found")
        if u.id == admin.id and u.role == UserRole.admin:
            raise HTTPException(400, "Cannot deactivate yourself")
        u.is_active = not u.is_active
        s.add(u)
        s.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users/{uid}/set-role")
async def admin_users_set_role(
    uid: int, role: UserRole = Form(...), user: User = Depends(get_current_user)
):
    admin = require_admin(user)
    with Session(engine) as s:
        u = s.get(User, uid)
        if not u:
            raise HTTPException(404, "User not found")
        u.role = role
        s.add(u)
        s.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/regions/create")
async def admin_regions_create(
    name: str = Form(...), code: str = Form(""), user: User = Depends(get_current_user)
):
    require_admin(user)
    with Session(engine) as s:
        r = Region(name=name, code=code or None)
        s.add(r)
        s.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/pharmacies/create")
async def admin_pharmacies_create(
    name: str = Form(...),
    region_id: Optional[int] = Form(None),
    address: str = Form(""),
    user: User = Depends(get_current_user),
):
    require_admin(user)
    with Session(engine) as s:
        ph = Pharmacy(name=name, region_id=region_id, address=address or None)
        s.add(ph)
        s.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/pharmacies/{pid}/assign")
async def admin_pharmacies_assign(
    pid: int, driver_id: int = Form(...), user: User = Depends(get_current_user)
):
    require_admin(user)
    with Session(engine) as s:
        if not s.get(Pharmacy, pid):
            raise HTTPException(404, "Pharmacy not found")
        du = s.get(User, driver_id)
        if not du or du.role != UserRole.driver:
            raise HTTPException(404, "Driver not found")
        exists = s.exec(
            select(UserPharmacyLink).where(
                UserPharmacyLink.user_id == driver_id,
                UserPharmacyLink.pharmacy_id == pid,
            )
        ).first()
        if not exists:
            s.add(UserPharmacyLink(user_id=driver_id, pharmacy_id=pid))
            s.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/pharmacies/{pid}/unassign")
async def admin_pharmacies_unassign(
    pid: int, driver_id: int = Form(...), user: User = Depends(get_current_user)
):
    require_admin(user)
    with Session(engine) as s:
        link = s.exec(
            select(UserPharmacyLink).where(
                UserPharmacyLink.user_id == driver_id,
                UserPharmacyLink.pharmacy_id == pid,
            )
        ).first()
        if link:
            s.delete(link)
            s.commit()
    return RedirectResponse(url="/admin", status_code=303)


# ===================== Debug (optional) =====================
@app.on_event("startup")
async def _debug_print_routes():
    print("\n=== ROUTES REGISTERED ===")
    for r in app.routes:
        methods = getattr(r, "methods", [])
        print(
            f"{r.path}  {methods}  include_in_schema={getattr(r, 'include_in_schema', None)}"
        )
    print("=========================\n")


@app.get("/ping")
def ping():
    return {"ok": True}
