"""
[PENANGGUNG JAWAB: Anggota B]
Endpoint manajemen user — sebelumnya ganti role user cuma bisa manual lewat
SQL langsung ke database (lihat catatan di project-handoff.md), tidak ada
jalur API sama sekali. Router ini menutup gap itu. Dibatasi Role.IT_ADMIN.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.schemas import AdminUserResponse, UserRoleUpdateRequest
from app.auth.utils import require_role
from app.guardrail.audit_log import log_guardrail_event, EventType

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_role(Role.IT_ADMIN))):
    return db.query(User).order_by(User.created_at.desc()).all()


@router.patch("/users/{user_id}/role", response_model=AdminUserResponse)
def update_user_role(
    user_id: str,
    payload: UserRoleUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(Role.IT_ADMIN)),
):
    if user_id == admin.id:
        # Cegah admin tidak sengaja menurunkan role akunnya sendiri sampai
        # terkunci dari fitur admin — kalau memang perlu, minta admin LAIN
        # yang ubah, atau lewat SQL manual (jalur darurat yang masih ada).
        raise HTTPException(status_code=400, detail="Tidak bisa mengubah role akun sendiri")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

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
