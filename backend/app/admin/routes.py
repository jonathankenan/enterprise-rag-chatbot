"""Endpoint manajemen user (ganti role/divisi) — sebelumnya cuma bisa lewat SQL manual. Dibatasi Role.IT_ADMIN."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User, SystemSettings
from app.schemas import AdminUserResponse, UserRoleUpdateRequest, UserDivisiUpdateRequest, SystemSettingsResponse, UpdateExportRolesRequest
from app.auth.utils import require_role, get_divisi_scope
from app.guardrail.audit_log import log_guardrail_event, EventType

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
