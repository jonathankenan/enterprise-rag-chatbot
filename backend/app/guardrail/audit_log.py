"""
[PENANGGUNG JAWAB: Anggota B]
Audit trail untuk aktivitas guardrail (F2-04) — jejak lengkap untuk
investigasi insiden, pelaporan compliance, dan analitik tren pelanggaran.
"""
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import AuditLog


# ---------- Daftar tipe event standar (supaya konsisten, tidak typo bebas) ----------
class EventType:
    PROMPT_BLOCKED = "prompt_blocked"           # F1-04: kata kunci terlarang
    INJECTION_BLOCKED = "injection_blocked"      # F2-04: prompt injection
    PII_DETECTED = "pii_detected"                # F2-04: PII terdeteksi & di-mask
    OUTPUT_BLOCKED = "output_blocked"            # F2-04: jawaban AI diblokir
    RATE_LIMIT_HIT = "rate_limit_hit"            # F1-01: login gagal berulang
    LOGIN_FAILED = "login_failed"
    LOGIN_SUCCESS = "login_success"


# ---------- Tingkat keparahan, untuk prioritas review ----------
class Severity:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_MAP = {
    EventType.PROMPT_BLOCKED: Severity.LOW,
    EventType.INJECTION_BLOCKED: Severity.MEDIUM,
    EventType.PII_DETECTED: Severity.LOW,
    EventType.OUTPUT_BLOCKED: Severity.MEDIUM,
    EventType.RATE_LIMIT_HIT: Severity.HIGH,
    EventType.LOGIN_FAILED: Severity.LOW,
    EventType.LOGIN_SUCCESS: Severity.LOW,
}


def log_guardrail_event(
    db: Session,
    user_id: str | None,
    event_type: str,
    detail: str = "",
    metadata: dict | None = None,
):
    """
    Catat satu kejadian guardrail ke database.
    metadata: dict bebas untuk info tambahan (mis. skor injection, kategori PII)
              disimpan sebagai JSON string di kolom detail bersama teks ringkas.
    """
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
    """
    Hitung jumlah kejadian per tipe dalam N jam terakhir —
    berguna untuk dashboard ringkasan/tren pelanggaran.
    """
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