"""
[PENANGGUNG JAWAB: Anggota B]
Fungsi bantu untuk hashing password dan pembuatan/validasi JWT token.
"""
import time
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

# ---------- SRS ISR-005: idle-timeout sesi (15 menit tanpa aktivitas) ----------
# JWT itu stateless by design (jwt_expire_minutes cuma masa berlaku TETAP,
# bukan idle-timeout — token yang sama sekali tidak dipakai selama 24 jam
# tetap valid sampai jam ke-24 persis). Supaya ISR-005 beneran ditegakkan
# (sesi berakhir kalau IDLE, bukan cuma kadaluarsa tetap), perlu state
# tambahan di luar JWT: dict in-memory yang dicek/diupdate di SETIAP request
# terautentikasi (lewat get_current_user, dependency yang dipakai semua
# endpoint yang butuh login). Pola in-memory ini sama seperti rate_limit.py/
# rate_limiter.py yang sudah ada — reset saat server restart, tidak
# konsisten kalau backend dijalankan multi-instance (batasan yang sudah
# didokumentasikan di modul-modul serupa, cukup untuk skala PoC).
IDLE_TIMEOUT_SECONDS = 15 * 60
_last_activity: dict[str, float] = {}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Dependency FastAPI — dipakai di endpoint yang butuh login."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesi tidak valid, silakan login kembali",
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    # ---------- SRS ISR-005: cek & update idle-timeout ----------
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


def require_role(*allowed_roles: str):
    """
    Dependency FACTORY (bukan dependency langsung) — dipakai seperti:
        user: User = Depends(require_role(Role.ADMIN, Role.COMPLIANCE))
    Beda dari get_current_user: ini bukan cuma cek "sudah login atau belum",
    tapi juga cek apakah role user termasuk yang diizinkan untuk endpoint ini
    (SRS FCR-003 hal. 15, poin 2.d — restriction per role/grup).

    Dibuat sebagai factory (fungsi yang mengembalikan fungsi) karena FastAPI
    Depends() butuh callable tanpa argumen tambahan di luar dependency lain
    — pola ini yang memungkinkan tiap endpoint pasang daftar role berbeda
    tanpa harus bikin fungsi dependency baru satu-satu per kombinasi role.
    """
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses untuk melakukan aksi ini",
            )
        return user
    return dependency
