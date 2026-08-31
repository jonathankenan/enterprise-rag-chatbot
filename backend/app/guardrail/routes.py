"""Endpoint audit log guardrail — dibatasi Role.AUDIT_VIEWERS (IT_ADMIN, COMPLIANCE, AUDITOR — SRS hal. 15 poin 2.d)."""
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
    """Pencarian audit log serba-guna — SRS ISR-004.d (Search, Sort, Filter data), semua parameter opsional & bisa dikombinasikan."""
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
    """Export audit log ke CSV — SRS ISR-004.d 'Export to file', filter sama seperti /search, limit besar supaya tidak diam-diam kepotong."""
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
