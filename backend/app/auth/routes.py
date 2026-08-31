"""Endpoint: register, login, me, change-password, mfa/setup, mfa/setup/confirm, mfa/verify, azure/login-url, azure/callback."""
import base64
import io
from datetime import datetime, timedelta

import msal
import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
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
    AzureLoginUrlResponse,
    AzureCallbackRequest,
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
    """Selesaikan login sungguhan (bikin access_token, catat LOGIN_SUCCESS) — dipanggil dari login()/mfa_setup_confirm()/mfa_verify() supaya cuma dihitung sekali."""
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

    # Akun "azure" login lewat SSO, tidak punya siklus password lokal -- password_expired cuma relevan buat akun "local"
    password_expired = False
    if user.auth_provider == "local":
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
        # SRS ISR-001.c: catat upaya akses gagal -- user_id None kalau email bahkan tidak terdaftar
        log_guardrail_event(
            db, user.id if user else None, EventType.LOGIN_FAILED,
            detail=f"Percobaan login gagal untuk email={payload.email}",
        )
        raise HTTPException(status_code=401, detail="Email atau password salah")

    clear_attempts(payload.email)

    # SRS ISR-001.d: password benar saja tidak cukup untuk IT_ADMIN -- wajib MFA, token sementara 5 menit
    if user.role == Role.IT_ADMIN:
        pending_token = create_pending_mfa_token(user.id)
        if not user.mfa_enabled:
            return TokenResponse(mfa_setup_required=True, mfa_token=pending_token)
        return TokenResponse(mfa_required=True, mfa_token=pending_token)

    return _complete_login(db, user)


@router.post("/mfa/setup", response_model=MfaSetupResponse)
def mfa_setup(payload: MfaSetupRequest, db: Session = Depends(get_db)):
    """Langkah 1 setup MFA: generate secret baru + QR code, belum disimpan ke DB sampai user confirm."""
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
    """Langkah 2: kode 6-digit cocok -> MFA resmi aktif & login selesai."""
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
    """Untuk IT Admin yang MFA-nya sudah aktif — verifikasi kode 6-digit tiap login."""
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


# ---------- SSO Azure AD — simulasi "Logon menggunakan LDAP M365 BEI" (SRS hal. 64) ----------
# Tenant di sini tenant developer/pribadi, bukan tenant BEI asli -- alur OAuth-nya beneran jalan, cuma tidak terhubung ke direktori karyawan BEI sungguhan.

def _get_msal_app():
    # Mode direktori tiruan (auth/mock_directory.py) — dipakai kalau tenant
    # Azure tidak tersedia. Dicegat DI SINI, di satu-satunya tempat MSAL
    # dibuat, supaya azure_login_url() dan azure_callback() di bawah tidak
    # perlu tahu apa-apa soal mode ini: keduanya tetap memanggil dua metode
    # yang sama, dan MockMsalApp mengembalikan bentuk yang sama dengan MSAL.
    # Kalau tenant sudah ada, cukup matikan AZURE_MOCK_ENABLED — tidak ada
    # cabang khusus yang tertinggal di endpoint.
    if settings.azure_mock_enabled:
        from app.auth.mock_directory import MockMsalApp
        return MockMsalApp(picker_url=settings.azure_mock_picker_url)

    # Pengecekan "sudah dikonfigurasi atau belum" ditaruh DI SINI (satu-satunya
    # tempat), bukan diulang di tiap endpoint pemanggilnya — sebelumnya
    # azure_login_url() punya pengecekan ini tapi azure_callback() lupa,
    # akibatnya azure_callback() lempar 500 mentah (ValueError dari MSAL,
    # authority URL tidak lengkap) bukan 400 yang rapi kalau .env kosong.
    if not (settings.azure_client_id and settings.azure_tenant_id and settings.azure_client_secret):
        raise HTTPException(status_code=400, detail="SSO Azure AD belum dikonfigurasi di server (lihat backend/.env)")
    return msal.ConfidentialClientApplication(
        settings.azure_client_id,
        authority=f"https://login.microsoftonline.com/{settings.azure_tenant_id}",
        client_credential=settings.azure_client_secret,
    )


@router.get("/azure/login-url", response_model=AzureLoginUrlResponse)
def azure_login_url():
    auth_url = _get_msal_app().get_authorization_request_url(
        scopes=["User.Read"],
        redirect_uri=settings.azure_redirect_uri,
    )
    return AzureLoginUrlResponse(auth_url=auth_url)


@router.get("/azure/mock-picker", include_in_schema=False)
def azure_mock_picker(redirect_uri: str):
    """
    Berdiri menggantikan halaman login Microsoft saat AZURE_MOCK_ENABLED aktif.
    Menampilkan daftar pegawai palsu; memilih satu = redirect balik ke
    redirect_uri dengan ?code=<email>, persis bentuk yang dikirim Microsoft.

    include_in_schema=False supaya endpoint ini tidak ikut muncul di /docs —
    dia bukan bagian dari API produk, cuma perkakas pengembangan.
    """
    if not settings.azure_mock_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    # redirect_uri dibatasi ke yang dikonfigurasi. Tanpa ini endpoint yang
    # menerima URL bebas ini jadi open redirect — kecil, tapi tidak ada
    # alasan membiarkannya karena nilainya memang cuma satu.
    if redirect_uri != settings.azure_redirect_uri:
        raise HTTPException(status_code=400, detail="redirect_uri tidak dikenal")
    from fastapi.responses import HTMLResponse
    from app.auth.mock_directory import render_picker_page
    return HTMLResponse(render_picker_page(redirect_uri))


@router.post("/azure/callback", response_model=TokenResponse)
def azure_callback(payload: AzureCallbackRequest, db: Session = Depends(get_db)):
    """Dipanggil frontend setelah Microsoft redirect balik dengan `code` — tukar code jadi token asli lewat MSAL."""
    result = _get_msal_app().acquire_token_by_authorization_code(
        payload.code, scopes=["User.Read"], redirect_uri=settings.azure_redirect_uri,
    )
    if "error" in result:
        raise HTTPException(status_code=401, detail=f"Login Azure AD gagal: {result.get('error_description', result['error'])}")

    claims = result.get("id_token_claims", {})
    email = claims.get("preferred_username") or claims.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Tidak bisa membaca email dari akun Azure AD")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        # SRS hal. 64: akun harus SUDAH terdaftar oleh Admin IT, bukan auto-signup
        log_guardrail_event(
            db, None, EventType.LOGIN_FAILED,
            detail=f"Login Azure AD ditolak, akun belum terdaftar: email={email}",
        )
        raise HTTPException(
            status_code=403,
            detail="Akun ini belum terdaftar di sistem. Hubungi IT Admin untuk didaftarkan terlebih dahulu.",
        )

    # Login lewat direktori tiruan TIDAK BOLEH senyap: dari sisi data hasilnya
    # sesi yang sah persis seperti SSO beneran, jadi satu-satunya cara
    # membedakannya belakangan adalah jejak ini. Dicatat SEBELUM cabang MFA
    # supaya tetap tercatat walau user berhenti di layar MFA.
    if settings.azure_mock_enabled:
        log_guardrail_event(
            db, user.id, EventType.AZURE_MOCK_LOGIN,
            detail=f"Login lewat DIREKTORI AZURE TIRUAN (bukan Microsoft): email={email}",
        )

    if user.auth_provider != "azure":
        user.auth_provider = "azure"
        db.commit()

    # IT Admin tetap wajib MFA -- SSO cuma menggantikan verifikasi password
    if user.role == Role.IT_ADMIN:
        pending_token = create_pending_mfa_token(user.id)
        if not user.mfa_enabled:
            return TokenResponse(mfa_setup_required=True, mfa_token=pending_token)
        return TokenResponse(mfa_required=True, mfa_token=pending_token)

    return _complete_login(db, user)
