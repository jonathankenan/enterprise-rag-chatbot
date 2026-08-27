"""Fungsi bantu untuk hashing password dan pembuatan/validasi JWT token."""
import time
import uuid
from datetime import datetime, timedelta

from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# SRS ISR-005: idle-timeout sesi (15 menit) -- JWT stateless tidak punya ini bawaan, jadi dilacak manual di sini (in-memory, reset saat restart)
IDLE_TIMEOUT_SECONDS = 15 * 60
_last_activity: dict[str, float] = {}

# SRS ISR-001.f: limit multi-logon per akun -- simpan SATU "sid" aktif per user, login baru menimpa & "mengusir" sesi lama
_active_session: dict[str, str] = {}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str) -> str:
    """Bikin token baru DAN jadikan sesi ini satu-satunya sesi resmi aktif user ini (ISR-001.f)."""
    session_id = str(uuid.uuid4())
    _active_session[user_id] = session_id

    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "sid": session_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


# SRS ISR-001.d: token sementara (5 menit) khusus buat 2 langkah login IT Admin (password benar, MFA belum)
MFA_PENDING_TOKEN_MINUTES = 5


def create_pending_mfa_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=MFA_PENDING_TOKEN_MINUTES)
    payload = {"sub": user_id, "mfa_pending": True, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_pending_mfa_token(token: str) -> str:
    """Kembalikan user_id kalau token valid & memang token 'menunggu MFA'. Raise 401 kalau tidak."""
    invalid = HTTPException(status_code=401, detail="Token verifikasi MFA tidak valid atau sudah kadaluarsa")
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise invalid
    if not payload.get("mfa_pending") or not payload.get("sub"):
        raise invalid
    return payload["sub"]


def resolve_user_from_token(token: str, db: Session) -> User:
    """Verifikasi token inti (JWT valid + sesi aktif ISR-001.f + idle-timeout ISR-005) — dipakai HTTP header maupun WebSocket query param."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesi tidak valid, silakan login kembali",
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        session_id = payload.get("sid")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    if session_id is None or _active_session.get(user_id) != session_id:
        # sudah ada login lebih baru dari device lain, sid ini sudah digantikan
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi ini sudah digantikan oleh login dari perangkat/tab lain, silakan login kembali",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    now = time.time()
    last_seen = _last_activity.get(user.id)
    if last_seen is not None and (now - last_seen) > IDLE_TIMEOUT_SECONDS:
        del _last_activity[user.id]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi berakhir karena tidak ada aktivitas selama 15 menit, silakan login kembali",
        )
    _last_activity[user.id] = now

    return user


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Dependency FastAPI — dipakai di endpoint HTTP biasa yang butuh login."""
    return resolve_user_from_token(token, db)


def require_role(*allowed_roles: str):
    """Dependency factory — Depends(require_role(Role.ADMIN)) cek login SEKALIGUS role yang diizinkan (SRS hal. 15 poin 2.d)."""
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses untuk melakukan aksi ini",
            )
        return user
    return dependency


def get_divisi_scope(user: User) -> str | None:
    """Cakupan divisi seorang IT_ADMIN: None = admin global (semua divisi), "PTI" = terbatas divisi PTI saja."""
    return user.divisi
