"""Audit trail untuk aktivitas guardrail (F2-04) — jejak lengkap untuk investigasi insiden, compliance, dan analitik tren pelanggaran."""
import csv
import io
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import AuditLog


class EventType:
    PROMPT_BLOCKED = "prompt_blocked"           # F1-04: kata kunci terlarang
    INJECTION_BLOCKED = "injection_blocked"      # F2-04: prompt injection
    PII_DETECTED = "pii_detected"                # F2-04: PII terdeteksi & di-mask
    OUTPUT_BLOCKED = "output_blocked"            # F2-04: jawaban AI diblokir
    DOCUMENT_BLOCKED = "document_blocked"        # F2-04: dokumen upload ditolak guardrail
    RATE_LIMIT_HIT = "rate_limit_hit"            # F1-01 & F2-04
    LOGIN_FAILED = "login_failed"
    LOGIN_SUCCESS = "login_success"

    # Kirim pesan/prompt biasa SENGAJA tidak dicatat di sini — sudah lengkap di tabel Message terenkripsi, duplikasi cuma jadi noise
    CHAT_CREATED = "chat_created"
    CHAT_DELETED = "chat_deleted"                # aksi destruktif — dulu tidak ada jejak sama sekali
    CHAT_RENAMED = "chat_renamed"
    DOCUMENT_UPLOADED = "document_uploaded"
    CHAT_EXPORTED = "chat_exported"
    USER_REGISTERED = "user_registered"
    PASSWORD_CHANGED = "password_changed"

    HELPDESK_ESCALATED = "helpdesk_escalated"    # FCR-003 poin 7
    HELPDESK_TICKET_CLOSED = "helpdesk_ticket_closed"
    USER_ROLE_CHANGED = "user_role_changed"
    COMMERCIAL_LLM_TOGGLED = "commercial_llm_toggled"
    EXPORT_ROLES_CHANGED = "export_roles_changed"  # F2-08
    FAQ_CREATED = "faq_created"
    FAQ_DELETED = "faq_deleted"
    KB_DOCUMENT_UPLOADED = "kb_document_uploaded"  # SRS poin 11
    KB_DOCUMENT_DELETED = "kb_document_deleted"
    USER_DIVISI_CHANGED = "user_divisi_changed"
    RATE_LIMIT_CONFIG_CHANGED = "rate_limit_config_changed"  # SRS poin 4.c-d
    RETENTION_POLICY_CHANGED = "retention_policy_changed"    # SRS poin 6
    RETENTION_POLICY_APPLIED = "retention_policy_applied"
    CHAT_ARCHIVED = "chat_archived"
    CHAT_UNARCHIVED = "chat_unarchived"


class Severity:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_MAP = {
    EventType.PROMPT_BLOCKED: Severity.HIGH,  # dinaikkan sengaja meski keyword polos lebih rawan false-positive (2026-08-11)
    EventType.INJECTION_BLOCKED: Severity.CRITICAL,
    EventType.PII_DETECTED: Severity.MEDIUM,
    EventType.OUTPUT_BLOCKED: Severity.HIGH,
    EventType.DOCUMENT_BLOCKED: Severity.HIGH,
    EventType.RATE_LIMIT_HIT: Severity.HIGH,
    EventType.LOGIN_FAILED: Severity.LOW,
    EventType.LOGIN_SUCCESS: Severity.LOW,
    EventType.CHAT_CREATED: Severity.LOW,
    EventType.CHAT_DELETED: Severity.LOW,        # aksi normal user, bukan pelanggaran
    EventType.DOCUMENT_UPLOADED: Severity.LOW,
    EventType.CHAT_EXPORTED: Severity.LOW,
    EventType.USER_REGISTERED: Severity.LOW,
    EventType.PASSWORD_CHANGED: Severity.LOW,
    EventType.HELPDESK_ESCALATED: Severity.MEDIUM,
    EventType.HELPDESK_TICKET_CLOSED: Severity.LOW,
    EventType.USER_ROLE_CHANGED: Severity.HIGH,
    EventType.COMMERCIAL_LLM_TOGGLED: Severity.CRITICAL,  # mempengaruhi semua user sekaligus
    EventType.EXPORT_ROLES_CHANGED: Severity.MEDIUM,
    EventType.FAQ_CREATED: Severity.LOW,
    EventType.FAQ_DELETED: Severity.LOW,
    EventType.KB_DOCUMENT_UPLOADED: Severity.LOW,
    EventType.KB_DOCUMENT_DELETED: Severity.LOW,
    EventType.USER_DIVISI_CHANGED: Severity.HIGH,
    EventType.RATE_LIMIT_CONFIG_CHANGED: Severity.MEDIUM,  # mempengaruhi semua user
    EventType.RETENTION_POLICY_CHANGED: Severity.MEDIUM,
    EventType.RETENTION_POLICY_APPLIED: Severity.MEDIUM,   # aksi massal, mengarsipkan banyak chat sekaligus
    EventType.CHAT_ARCHIVED: Severity.LOW,
    EventType.CHAT_UNARCHIVED: Severity.LOW,
}


def log_guardrail_event(
    db: Session,
    user_id: str | None,
    event_type: str,
    detail: str = "",
    metadata: dict | None = None,
):
    """Catat satu kejadian guardrail ke database — metadata disimpan sebagai JSON string di kolom detail."""
    severity = _SEVERITY_MAP.get(event_type, Severity.LOW)

    detail_payload = {"message": detail[:500]}
    if metadata:
        detail_payload["metadata"] = metadata

    entry = AuditLog(
        user_id=user_id,
        event_type=event_type,
        severity=severity,
        detail=json.dumps(detail_payload, ensure_ascii=False),
    )
    db.add(entry)
    db.commit()


# ---------- Fungsi query untuk kebutuhan pelaporan/dashboard ----------

def get_recent_events(db: Session, limit: int = 50) -> list[AuditLog]:
    """Ambil kejadian terbaru, untuk keperluan monitoring."""
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()


def get_events_by_user(db: Session, user_id: str, limit: int = 50) -> list[AuditLog]:
    """Ambil riwayat kejadian guardrail milik satu user tertentu."""
    return (
        db.query(AuditLog)
        .filter(AuditLog.user_id == user_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )


def count_events_by_type(db: Session, since_hours: int = 24) -> dict[str, int]:
    """Hitung jumlah kejadian per tipe dalam N jam terakhir — untuk dashboard ringkasan/tren."""
    since = datetime.utcnow() - timedelta(hours=since_hours)
    results = (
        db.query(AuditLog.event_type, func.count(AuditLog.id))
        .filter(AuditLog.created_at >= since)
        .group_by(AuditLog.event_type)
        .all()
    )
    return {event_type: count for event_type, count in results}


def get_high_severity_events(db: Session, limit: int = 50) -> list[AuditLog]:
    """Ambil kejadian dengan tingkat keparahan tinggi/kritis — prioritas review manual."""
    return (
        db.query(AuditLog)
        .filter(AuditLog.severity.in_([Severity.HIGH, Severity.CRITICAL]))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )


# ---------- SRS ISR-004.d: Search, Sort, Filter data ----------

_SORTABLE_FIELDS = {
    "created_at": AuditLog.created_at,
    "severity": AuditLog.severity,
    "event_type": AuditLog.event_type,
}


def search_events(
    db: Session,
    event_type: str | None = None,
    severity: str | None = None,
    user_id: str | None = None,
    search_text: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    """Pencarian audit log serba-guna (SRS ISR-004.d) — search_text dijalankan di level aplikasi pasca-dekripsi karena `detail` terenkripsi, SQL ILIKE tidak bisa dipakai."""
    query = db.query(AuditLog)
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    if severity:
        query = query.filter(AuditLog.severity == severity)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if since:
        query = query.filter(AuditLog.created_at >= since)
    if until:
        query = query.filter(AuditLog.created_at <= until)

    sort_column = _SORTABLE_FIELDS.get(sort_by, AuditLog.created_at)
    query = query.order_by(sort_column.asc() if sort_order == "asc" else sort_column.desc())

    if not search_text:
        return query.offset(offset).limit(limit).all()

    candidates = query.limit(max(limit * 5, 500)).all()  # ambil kandidat lebih banyak supaya sisa cukup setelah filter teks
    needle = search_text.lower()
    matched = [e for e in candidates if e.detail and needle in e.detail.lower()]
    return matched[offset:offset + limit]


# ---------- SRS ISR-004.d: Export to file ----------

def export_events_to_csv(events: list[AuditLog]) -> str:
    """Serialisasi daftar AuditLog jadi teks CSV — SRS ISR-004.d 'Export to file'."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "waktu_kejadian", "akun_terlibat", "jenis_aktivitas", "level_kejadian", "detail"])
    for e in events:
        writer.writerow([e.id, e.created_at.isoformat(), e.user_id or "-", e.event_type, e.severity, e.detail or ""])
    return output.getvalue()
