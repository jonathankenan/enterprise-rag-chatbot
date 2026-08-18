"""
[PENANGGUNG JAWAB: Anggota B]
Fungsi bantu untuk hashing password dan pembuatan/validasi JWT token.
"""
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

# ---------- SRS ISR-001.f: "Sistem melimitasi multiple logon pada akun ----------
# yang sama." JWT stateless artinya SEMUA token yang pernah diterbitkan
# untuk satu akun tetap valid sampai masa berlakunya habis sendiri-sendiri
# — tanpa state tambahan, user bisa login dari 5 device sekaligus dan
# kelimanya tetap jalan terus. _active_session menyimpan SATU "sid" (session
# id) yang lagi aktif per user — login baru menimpa entry lama, otomatis
# membuat token LAMA jadi tidak valid lagi (bukan menolak login baru, tapi
# "mengusir" sesi lama — pola umum dipakai aplikasi perbankan: "Anda sudah
# login di perangkat lain").
_active_session: dict[str, str] = {}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str) -> str:
    """
    Bikin token baru DAN jadikan token ini satu-satunya sesi "resmi" aktif
    untuk user ini (ISR-001.f) — sesi lama (kalau ada) otomatis jadi tidak
    valid lagi begitu token ini dipakai. "sid" (session id) ini yang dicek
    di get_current_user() tiap request.
    """
    session_id = str(uuid.uuid4())
    _active_session[user_id] = session_id

    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "sid": session_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


# ---------- SRS ISR-001.d: MFA untuk akun IT Admin ----------
# Token "menunggu MFA" — dipakai untuk 2 langkah login (password benar TAPI
# belum lolos MFA). SENGAJA token JWT terpisah (bukan access_token biasa):
# masa berlakunya cuma 5 menit, dan get_current_user() akan MENOLAKNYA kalau
# dipakai ke endpoint biasa (tidak punya "sid" dalam bentuk yang valid) —
# jadi token ini SATU-SATUNYA yang bisa dipakai ke endpoint verifikasi MFA,
# tidak bisa dipakai buat apa pun lagi.
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


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Dependency FastAPI — dipakai di endpoint yang butuh login."""
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

    # ---------- SRS ISR-001.f: token ini masih sesi yang "resmi" aktif? ----------
    # Kalau ada login LEBIH BARU dari device/tab lain untuk user yang sama,
    # _active_session[user_id] sudah ditimpa sid yang beda — token ini
    # otomatis jadi "sesi lama yang sudah digantikan", ditolak walau secara
    # teknis JWT-nya sendiri belum expired.
    if session_id is None or _active_session.get(user_id) != session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi ini sudah digantikan oleh login dari perangkat/tab lain, silakan login kembali",
        )

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
