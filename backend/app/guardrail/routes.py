"""
[PENANGGUNG JAWAB: Anggota B]
Endpoint audit log guardrail — dibatasi Role.AUDIT_VIEWERS (IT_ADMIN,
COMPLIANCE, AUDITOR — SRS FCR-003 hal. 15, poin 2.d).

Catatan pembersihan (2026-08-12): endpoint /recent dan /high-severity yang
dulu ada di sini SUDAH DIHAPUS — keduanya cuma kasus khusus dari /search
(recent = /search tanpa filter apapun, high-severity = /search?severity=high)
dan tidak pernah benar-benar dipakai frontend (dead code sejak dibuat).
Fungsi get_recent_events()/get_high_severity_events() di audit_log.py tetap
dibiarkan ada (utility murni, tidak berbahaya kalau tidak dipakai), tapi
endpoint API-nya dihapus supaya tidak ada permukaan API yang menganggur.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.schemas import AuditLogResponse, AuditSummaryResponse
from app.auth.utils import require_role
from app.guardrail.audit_log import count_events_by_type, search_events, export_events_to_csv

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/summary", response_model=AuditSummaryResponse)
def summary(
    since_hours: int = 24,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*Role.AUDIT_VIEWERS)),
):
    """Ringkasan jumlah kejadian per tipe dalam N jam terakhir — untuk dashboard tren pelanggaran."""
    return AuditSummaryResponse(since_hours=since_hours, counts_by_type=count_events_by_type(db, since_hours=since_hours))


@router.get("/search", response_model=list[AuditLogResponse])
def search(
    event_type: str | None = None,
    severity: str | None = None,
    user_id: str | None = None,
    q: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*Role.AUDIT_VIEWERS)),
):
    """
    Pencarian audit log serba-guna — SRS ISR-004.d (Search, Sort, Filter data).
    Semua parameter opsional & bisa dikombinasikan, mis.
    /api/audit/search?event_type=injection_blocked&severity=medium&sort_by=severity&sort_order=asc
    """
    return search_events(
        db, event_type=event_type, severity=severity, user_id=user_id,
        search_text=q, since=since, until=until,
        sort_by=sort_by, sort_order=sort_order, limit=limit, offset=offset,
    )


@router.get("/export")
def export(
    event_type: str | None = None,
    severity: str | None = None,
    user_id: str | None = None,
    q: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*Role.AUDIT_VIEWERS)),
):
    """
    Export audit log ke file CSV — SRS ISR-004.d 'Export to file'. Pakai
    filter yang sama seperti /search (tanpa limit/sort, export semua yang
    cocok filter — default limit besar supaya tidak keliru kepotong diam-diam).
    """
    events = search_events(
        db, event_type=event_type, severity=severity, user_id=user_id,
        search_text=q, since=since, until=until, limit=10000,
    )
    csv_content = export_events_to_csv(events)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit_log_export_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv"'},
    )
