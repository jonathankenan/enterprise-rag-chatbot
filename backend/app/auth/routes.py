"""
[PENANGGUNG JAWAB: Anggota B]
Endpoint: POST /api/auth/register, POST /api/auth/login,
          GET /api/auth/me, POST /api/auth/change-password
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, AuditLog
from app.schemas import (
    UserRegister,
    UserLogin,
    TokenResponse,
    UserResponse,
    ChangePasswordRequest,
)
from app.auth.utils import hash_password, verify_password, create_access_token, get_current_user
from app.auth.rate_limit import check_rate_limit, record_failed_attempt, clear_attempts
from app.guardrail.audit_log import log_guardrail_event, EventType

PASSWORD_MAX_AGE_DAYS = 90  # SRS ISR-002.c

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_guardrail_event(db, user.id, EventType.USER_REGISTERED, detail=f"Registrasi akun baru: {payload.email}")
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    check_rate_limit(payload.email)

    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        record_failed_attempt(payload.email)
        # SRS ISR-001.c: "upaya akses yang tidak terotorisasi harus dicatat,
        # termasuk tindakan pengguna yang ditolak atau gagal" — sebelumnya
        # EventType.LOGIN_FAILED sudah ada tapi tidak pernah dipanggil di
        # mana pun. user_id None kalau emailnya bahkan tidak terdaftar
        # (tidak ada akun untuk dikaitkan), tapi detail tetap simpan email
        # yang dicoba supaya investigasi tetap bisa jalan.
        log_guardrail_event(
            db, user.id if user else None, EventType.LOGIN_FAILED,
            detail=f"Percobaan login gagal untuk email={payload.email}",
        )
        raise HTTPException(status_code=401, detail="Email atau password salah")

    clear_attempts(payload.email)

    # ---------- SRS ISR-001.g: tampilkan waktu login sebelumnya + jumlah ----------
    # percobaan gagal sejak saat itu. HARUS dihitung SEBELUM log_guardrail_event()
    # di bawah menulis baris LOGIN_SUCCESS baru — kalau dihitung sesudahnya,
    # query "login sukses terakhir" bakal nemu baris yang baru saja ditulis
    # sendiri (selalu "login sebelumnya = sekarang").
    previous_login = (
        db.query(AuditLog)
        .filter(AuditLog.user_id == user.id, AuditLog.event_type == EventType.LOGIN_SUCCESS)
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    since = previous_login.created_at if previous_login else user.created_at
    failed_attempts_since_last_login = (
        db.query(AuditLog)
        .filter(
            AuditLog.user_id == user.id,
            AuditLog.event_type == EventType.LOGIN_FAILED,
            AuditLog.created_at >= since,
        )
        .count()
    )

    log_guardrail_event(db, user.id, EventType.LOGIN_SUCCESS, detail="Login berhasil")
    token = create_access_token(user_id=user.id)

    # ---------- SRS ISR-002.c: password sudah lewat 90 hari? ----------
    password_age = datetime.utcnow() - (user.password_changed_at or user.created_at)
    password_expired = password_age > timedelta(days=PASSWORD_MAX_AGE_DAYS)

    return TokenResponse(
        access_token=token,
        previous_login_at=previous_login.created_at if previous_login else None,
        failed_attempts_since_last_login=failed_attempts_since_last_login,
        password_expired=password_expired,
    )


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Password lama tidak sesuai")

    user.hashed_password = hash_password(payload.new_password)
    user.password_changed_at = datetime.utcnow()  # ISR-002.c: reset umur password
    db.commit()
    log_guardrail_event(db, user.id, EventType.PASSWORD_CHANGED, detail="Password diubah oleh pemilik akun")
    return {"message": "Password berhasil diubah"}