"""
[PENANGGUNG JAWAB: Anggota B]
Endpoint: POST /api/auth/register, POST /api/auth/login,
          GET /api/auth/me, POST /api/auth/change-password,
          POST /api/auth/mfa/setup, POST /api/auth/mfa/setup/confirm,
          POST /api/auth/mfa/verify
"""
import base64
import io
from datetime import datetime, timedelta

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, AuditLog, Role
from app.schemas import (
    UserRegister,
    UserLogin,
    TokenResponse,
    UserResponse,
    ChangePasswordRequest,
    MfaSetupRequest,
    MfaSetupResponse,
    MfaSetupConfirmRequest,
    MfaVerifyRequest,
)
from app.auth.utils import (
    hash_password, verify_password, create_access_token, get_current_user,
    create_pending_mfa_token, decode_pending_mfa_token,
)
from app.auth.rate_limit import check_rate_limit, record_failed_attempt, clear_attempts
from app.guardrail.audit_log import log_guardrail_event, EventType

PASSWORD_MAX_AGE_DAYS = 90  # SRS ISR-002.c
MFA_TOTP_ISSUER = "IDX Catalyst"

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


def _complete_login(db: Session, user: User) -> TokenResponse:
    """
    Selesaikan login SUNGGUHAN — bikin access_token, catat LOGIN_SUCCESS,
    hitung info ISR-001.g/ISR-002.c. Dipanggil dari 3 tempat: login() biasa
    (user tanpa MFA), mfa_setup_confirm() (IT Admin baru pertama kali setup
    MFA), dan mfa_verify() (IT Admin yang MFA-nya sudah aktif). Disatukan di
    sini supaya LOGIN_SUCCESS/previous_login_at cuma dihitung SEKALI di titik
    "login benar-benar selesai" — bukan di /login yang untuk akun ber-MFA
    baru separuh jalan (password benar, MFA belum).
    """
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

    password_age = datetime.utcnow() - (user.password_changed_at or user.created_at)
    password_expired = password_age > timedelta(days=PASSWORD_MAX_AGE_DAYS)

    return TokenResponse(
        access_token=token,
        previous_login_at=previous_login.created_at if previous_login else None,
        failed_attempts_since_last_login=failed_attempts_since_last_login,
        password_expired=password_expired,
    )


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

    # ---------- SRS ISR-001.d: password benar, tapi IT Admin WAJIB MFA ----------
    # Password saja TIDAK CUKUP untuk role IT_ADMIN — login belum selesai,
    # LOGIN_SUCCESS belum dicatat, access_token belum diterbitkan. User
    # dikasih token sementara (5 menit) yang cuma bisa dipakai ke endpoint
    # /mfa/setup atau /mfa/verify di bawah, bukan endpoint lain manapun.
    if user.role == Role.IT_ADMIN:
        pending_token = create_pending_mfa_token(user.id)
        if not user.mfa_enabled:
            return TokenResponse(mfa_setup_required=True, mfa_token=pending_token)
        return TokenResponse(mfa_required=True, mfa_token=pending_token)

    return _complete_login(db, user)


@router.post("/mfa/setup", response_model=MfaSetupResponse)
def mfa_setup(payload: MfaSetupRequest, db: Session = Depends(get_db)):
    """
    Langkah 1 dari setup MFA pertama kali: generate secret BARU + QR code.
    SENGAJA belum disimpan ke database di sini — kalau user batal di tengah
    jalan (tidak pernah confirm), tidak ada secret setengah-jadi yang
    nyangkut di akunnya. Baru benar-benar disimpan di /mfa/setup/confirm
    setelah user membuktikan aplikasi authenticator-nya menghasilkan kode
    yang cocok dengan secret ini.
    """
    user_id = decode_pending_mfa_token(payload.mfa_token)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    secret = pyotp.random_base32()
    otpauth_uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=MFA_TOTP_ISSUER)

    qr_img = qrcode.make(otpauth_uri)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode()

    return MfaSetupResponse(secret=secret, qr_code_base64=f"data:image/png;base64,{qr_base64}")


@router.post("/mfa/setup/confirm", response_model=TokenResponse)
def mfa_setup_confirm(payload: MfaSetupConfirmRequest, db: Session = Depends(get_db)):
    """Langkah 2: user ketik kode 6-digit dari aplikasi authenticator-nya — kalau cocok, MFA resmi aktif & login selesai."""
    user_id = decode_pending_mfa_token(payload.mfa_token)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    totp = pyotp.TOTP(payload.secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Kode MFA salah, coba lagi")

    user.totp_secret = payload.secret
    user.mfa_enabled = True
    db.commit()

    return _complete_login(db, user)


@router.post("/mfa/verify", response_model=TokenResponse)
def mfa_verify(payload: MfaVerifyRequest, db: Session = Depends(get_db)):
    """Untuk IT Admin yang MFA-nya SUDAH aktif — verifikasi kode 6-digit tiap login."""
    user_id = decode_pending_mfa_token(payload.mfa_token)
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.mfa_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="MFA belum aktif untuk akun ini")

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(payload.code, valid_window=1):
        log_guardrail_event(
            db, user.id, EventType.LOGIN_FAILED,
            detail=f"Kode MFA salah untuk email={user.email}",
        )
        raise HTTPException(status_code=401, detail="Kode MFA salah")

    return _complete_login(db, user)


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
