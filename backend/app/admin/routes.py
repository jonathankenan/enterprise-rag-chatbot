"""Endpoint manajemen user (ganti role/divisi) — sebelumnya cuma bisa lewat SQL manual. Dibatasi Role.IT_ADMIN."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User, SystemSettings, Chat
from app.schemas import (
    AdminUserResponse, UserRoleUpdateRequest, UserDivisiUpdateRequest, SystemSettingsResponse,
    UpdateExportRolesRequest, UpdateRateLimitRequest, UpdateRetentionRequest, RetentionApplyResponse,
)
from app.auth.utils import require_role, get_divisi_scope
from app.guardrail.audit_log import log_guardrail_event, EventType

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _assert_global_admin(admin: User):
    """SystemSettings itu tabel singleton (efeknya lintas divisi), jadi setelan sistem dikunci ke admin global — kecuali force-stop, lihat catatan di toggle_commercial_llm()."""
    if get_divisi_scope(admin) is not None:
        raise HTTPException(status_code=403, detail="Cuma admin global yang bisa mengubah setelan sistem")


def _get_or_create_settings(db: Session) -> SystemSettings:
    settings_row = db.query(SystemSettings).filter(SystemSettings.id == "global").first()
    if not settings_row:
        settings_row = SystemSettings(id="global")
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row


def _settings_response(settings_row: SystemSettings) -> SystemSettingsResponse:
    # export_allowed_roles disimpan string koma-pisah di DB, API keluar sebagai list[str]
    return SystemSettingsResponse(
        commercial_llm_force_stopped=settings_row.commercial_llm_force_stopped,
        export_allowed_roles=settings_row.get_export_allowed_roles(),
        chat_rate_limit_max_messages=settings_row.chat_rate_limit_max_messages,
        chat_rate_limit_window_seconds=settings_row.chat_rate_limit_window_seconds,
        chat_retention_days=settings_row.chat_retention_days,
        updated_by=settings_row.updated_by,
        updated_at=settings_row.updated_at,
    )


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_role(Role.IT_ADMIN))):
    # SRS hal. 68/70: admin divisi cuma lihat user di divisinya sendiri; admin global (divisi=None) lihat semua
    scope = get_divisi_scope(admin)
    query = db.query(User)
    if scope is not None:
        query = query.filter(User.divisi == scope)
    return query.order_by(User.created_at.desc()).all()


@router.patch("/users/{user_id}/role", response_model=AdminUserResponse)
def update_user_role(
    user_id: str,
    payload: UserRoleUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(Role.IT_ADMIN)),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Tidak bisa mengubah role akun sendiri")  # cegah admin mengunci diri sendiri

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    scope = get_divisi_scope(admin)
    if scope is not None and target.divisi != scope:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")  # 404 bukan 403 -- jangan bocorkan keberadaan user divisi lain

    old_role = target.role
    target.role = payload.role
    db.commit()
    db.refresh(target)

    log_guardrail_event(
        db, admin.id, EventType.USER_ROLE_CHANGED,
        detail=f"Role user {target.email} diubah oleh {admin.email}",
        metadata={"target_user_id": target.id, "old_role": old_role, "new_role": payload.role},
    )
    return target


@router.patch("/users/{user_id}/divisi", response_model=AdminUserResponse)
def update_user_divisi(
    user_id: str,
    payload: UserDivisiUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(Role.IT_ADMIN)),
):
    """Cuma admin GLOBAL (divisi=None) yang boleh memindah keanggotaan divisi user mana pun."""
    if get_divisi_scope(admin) is not None:
        raise HTTPException(status_code=403, detail="Cuma admin global yang bisa mengubah keanggotaan divisi")
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Tidak bisa mengubah divisi akun sendiri")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    old_divisi = target.divisi
    target.divisi = payload.divisi
    db.commit()
    db.refresh(target)

    log_guardrail_event(
        db, admin.id, EventType.USER_DIVISI_CHANGED,
        detail=f"Divisi user {target.email} diubah oleh {admin.email}",
        metadata={"target_user_id": target.id, "old_divisi": old_divisi, "new_divisi": payload.divisi},
    )
    return target


# ---------- SRS FCR-003 Rules poin 2: force-stop LLM Commercial ----------

@router.get("/system-settings", response_model=SystemSettingsResponse)
def get_system_settings(db: Session = Depends(get_db), user: User = Depends(require_role(Role.IT_ADMIN))):
    return _settings_response(_get_or_create_settings(db))


@router.post("/system-settings/toggle-commercial-llm", response_model=SystemSettingsResponse)
def toggle_commercial_llm(db: Session = Depends(get_db), admin: User = Depends(require_role(Role.IT_ADMIN))):
    """Toggle force-stop LLM Commercial — SRS hal. 10 Rules poin 2, satu tombol yang berubah fungsi tergantung status."""
    # SENGAJA TIDAK dikunci ke admin global (beda dari setelan sistem lain di file ini): ini emergency
    # kill switch, arahnya fail-safe (semua dipaksa ke on-prem), reversibel, dan teraudit CRITICAL —
    # risiko "tidak ada yang bisa menekan saat insiden" lebih besar daripada risiko salah tekan.
    # Efeknya tetap GLOBAL walau ditekan admin divisi: ancaman "jangan kirim apa pun ke LLM
    # commercial" tidak selesai kalau cuma satu divisi yang dihentikan.
    settings_row = _get_or_create_settings(db)
    settings_row.commercial_llm_force_stopped = not settings_row.commercial_llm_force_stopped
    settings_row.updated_by = admin.id
    db.commit()
    db.refresh(settings_row)

    log_guardrail_event(
        db, admin.id, EventType.COMMERCIAL_LLM_TOGGLED,
        detail=f"Force-stop LLM Commercial diubah oleh {admin.email}",
        metadata={"commercial_llm_force_stopped": settings_row.commercial_llm_force_stopped},
    )
    return _settings_response(settings_row)


# ---------- F2-08 (spesifikasi Tingkat 2): role mana boleh export PDF ----------

@router.post("/system-settings/export-roles", response_model=SystemSettingsResponse)
def update_export_roles(
    payload: UpdateExportRolesRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(Role.IT_ADMIN)),
):
    _assert_global_admin(admin)  # kontrol keluarnya data dari sistem, sekelas kebijakan retensi
    invalid = [r for r in payload.roles if r not in Role.ALL]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Role tidak dikenal: {', '.join(invalid)}")

    roles = sorted(set(payload.roles) | {Role.IT_ADMIN})  # IT_ADMIN dipaksa selalu ikut supaya admin tidak bisa mengunci diri sendiri

    settings_row = _get_or_create_settings(db)
    old_roles = settings_row.export_allowed_roles
    settings_row.export_allowed_roles = ",".join(roles)
    settings_row.updated_by = admin.id
    db.commit()
    db.refresh(settings_row)

    log_guardrail_event(
        db, admin.id, EventType.EXPORT_ROLES_CHANGED,
        detail=f"Role yang boleh export PDF diubah oleh {admin.email}",
        metadata={"old_roles": old_roles, "new_roles": settings_row.export_allowed_roles},
    )
    return _settings_response(settings_row)


# ---------- SRS poin 4.c-d: rate limit & API limiter dikonfigurasi IT Admin (dulu cuma lewat .env) ----------

@router.post("/system-settings/rate-limit", response_model=SystemSettingsResponse)
def update_rate_limit(
    payload: UpdateRateLimitRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(Role.IT_ADMIN)),
):
    _assert_global_admin(admin)  # kapasitas server itu sumber daya BERSAMA — kalau tiap divisi bisa naikkan jatahnya sendiri, proteksinya tidak ada artinya
    settings_row = _get_or_create_settings(db)
    old_values = (settings_row.chat_rate_limit_max_messages, settings_row.chat_rate_limit_window_seconds)
    settings_row.chat_rate_limit_max_messages = payload.max_messages
    settings_row.chat_rate_limit_window_seconds = payload.window_seconds
    settings_row.updated_by = admin.id
    db.commit()
    db.refresh(settings_row)

    log_guardrail_event(
        db, admin.id, EventType.RATE_LIMIT_CONFIG_CHANGED,
        detail=f"Rate limit chat diubah oleh {admin.email}",
        metadata={
            "old_max_messages": old_values[0], "old_window_seconds": old_values[1],
            "new_max_messages": payload.max_messages, "new_window_seconds": payload.window_seconds,
        },
    )
    return _settings_response(settings_row)


# ---------- SRS poin 6: konfigurasi retensi data historis ----------

@router.post("/system-settings/retention", response_model=SystemSettingsResponse)
def update_retention(
    payload: UpdateRetentionRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(Role.IT_ADMIN)),
):
    _assert_global_admin(admin)  # retensi = kewajiban regulasi (POJK/kearsipan), harus seragam se-perusahaan, bukan preferensi tiap divisi
    settings_row = _get_or_create_settings(db)
    old_value = settings_row.chat_retention_days
    settings_row.chat_retention_days = payload.retention_days
    settings_row.updated_by = admin.id
    db.commit()
    db.refresh(settings_row)

    log_guardrail_event(
        db, admin.id, EventType.RETENTION_POLICY_CHANGED,
        detail=f"Kebijakan retensi chat diubah oleh {admin.email}",
        metadata={"old_retention_days": old_value, "new_retention_days": payload.retention_days},
    )
    return _settings_response(settings_row)


@router.post("/system-settings/retention/apply", response_model=RetentionApplyResponse)
def apply_retention(db: Session = Depends(get_db), admin: User = Depends(require_role(Role.IT_ADMIN))):
    """Terapkan kebijakan retensi SEKARANG — arsipkan (bukan hapus permanen) chat aktif yang lebih tua dari chat_retention_days."""
    _assert_global_admin(admin)  # aksi massal lintas divisi (menyentuh chat SEMUA user), bukan cuma divisi si admin
    settings_row = _get_or_create_settings(db)
    if settings_row.chat_retention_days is None:
        raise HTTPException(status_code=400, detail="Kebijakan retensi belum diatur — set jumlah hari terlebih dahulu")

    cutoff = datetime.utcnow() - timedelta(days=settings_row.chat_retention_days)
    stale_chats = db.query(Chat).filter(Chat.archived.is_(False), Chat.created_at < cutoff).all()
    now = datetime.utcnow()
    for chat in stale_chats:
        chat.archived = True
        chat.archived_at = now
    db.commit()

    log_guardrail_event(
        db, admin.id, EventType.RETENTION_POLICY_APPLIED,
        detail=f"Kebijakan retensi diterapkan oleh {admin.email}",
        metadata={"retention_days": settings_row.chat_retention_days, "archived_count": len(stale_chats)},
    )
    return RetentionApplyResponse(archived_count=len(stale_chats))
