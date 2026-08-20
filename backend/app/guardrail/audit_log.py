"""
[PENANGGUNG JAWAB: Anggota B]
Audit trail untuk aktivitas guardrail (F2-04) — jejak lengkap untuk
investigasi insiden, pelaporan compliance, dan analitik tren pelanggaran.

Field yang dicatat (ISR-003.d / ISR-004.c — Waktu kejadian, Akun terlibat,
Aktivitas terjadi, Level kejadian) sudah lengkap sejak awal lewat kolom
created_at/user_id/event_type+detail/severity. Yang ditambahkan di sini:
search_events() untuk ISR-004.d (Search, Sort, Filter data) dan
export_events_to_csv() untuk ISR-004.d (Export to file).
"""
import csv
import io
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
    DOCUMENT_BLOCKED = "document_blocked"        # F2-04: dokumen upload ditolak guardrail
    RATE_LIMIT_HIT = "rate_limit_hit"            # F1-01 (login gagal berulang) & F2-04 (chat message rate limit)
    LOGIN_FAILED = "login_failed"
    LOGIN_SUCCESS = "login_success"

    # ---- Aktivitas umum (ISR-003.c: "Semua aktivitas operator dan
    # administrator sistem harus tercatat") — SENGAJA TIDAK termasuk kirim
    # pesan/prompt biasa: itu sudah tercatat lengkap (siapa, kapan, isi apa)
    # di tabel Message yang sudah terenkripsi+masked, jadi baris AuditLog
    # terpisah untuk tiap prompt normal cuma duplikasi tanpa nilai investigasi
    # tambahan, sekaligus membengkakkan tabel audit log yang seharusnya berisi
    # kejadian signifikan, bukan noise rutin.
    CHAT_CREATED = "chat_created"
    CHAT_DELETED = "chat_deleted"                # aksi destruktif — sebelumnya TIDAK ADA jejak sama sekali
    CHAT_RENAMED = "chat_renamed"                # user ganti judul chat secara manual
    DOCUMENT_UPLOADED = "document_uploaded"      # upload yang BERHASIL (beda dari DOCUMENT_BLOCKED)
    CHAT_EXPORTED = "chat_exported"              # data keluar sistem sebagai file
    USER_REGISTERED = "user_registered"
    PASSWORD_CHANGED = "password_changed"

    HELPDESK_ESCALATED = "helpdesk_escalated"    # FCR-003 poin 7: user setuju tawaran eskalasi, tiket dibuat
    HELPDESK_TICKET_CLOSED = "helpdesk_ticket_closed"  # admin menutup tiket
    USER_ROLE_CHANGED = "user_role_changed"      # admin ubah role user lain
    COMMERCIAL_LLM_TOGGLED = "commercial_llm_toggled"  # IT Admin nyala/matikan force-stop LLM commercial


# ---------- Tingkat keparahan, untuk prioritas review ----------
class Severity:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_MAP = {
    # Keputusan pemilik produk (2026-08-11): prompt_blocked dinaikkan ke HIGH
    # meski deteksinya berbasis keyword polos (lebih rawan false-positive
    # dibanding injection_blocked yang berbasis skor gabungan) — catatan ini
    # disimpan supaya alasannya jelas kalau nanti mau ditinjau ulang gara-gara
    # alert fatigue.
    EventType.PROMPT_BLOCKED: Severity.HIGH,
    EventType.INJECTION_BLOCKED: Severity.CRITICAL,
    EventType.PII_DETECTED: Severity.MEDIUM,
    EventType.OUTPUT_BLOCKED: Severity.HIGH,
    EventType.DOCUMENT_BLOCKED: Severity.HIGH,
    EventType.RATE_LIMIT_HIT: Severity.HIGH,
    EventType.LOGIN_FAILED: Severity.LOW,
    EventType.LOGIN_SUCCESS: Severity.LOW,
    EventType.CHAT_CREATED: Severity.LOW,
    EventType.CHAT_DELETED: Severity.LOW,        # aksi normal user, bukan indikasi pelanggaran — LOW meski destruktif
    EventType.DOCUMENT_UPLOADED: Severity.LOW,
    EventType.CHAT_EXPORTED: Severity.LOW,
    EventType.USER_REGISTERED: Severity.LOW,
    EventType.PASSWORD_CHANGED: Severity.LOW,
    EventType.HELPDESK_ESCALATED: Severity.MEDIUM,  # bukan pelanggaran keamanan, tapi sinyal kualitas layanan yang layak ditinjau
    EventType.HELPDESK_TICKET_CLOSED: Severity.LOW,
    EventType.USER_ROLE_CHANGED: Severity.HIGH,     # perubahan hak akses — selalu layak ditinjau
    EventType.COMMERCIAL_LLM_TOGGLED: Severity.CRITICAL,  # mempengaruhi SEMUA user sistem sekaligus
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
    """
    Pencarian audit log serba-guna — menutup SRS ISR-004.d (Search, Sort,
    Filter data). Filter event_type/severity/user_id/rentang tanggal
    dijalankan di level SQL (cepat, pakai kolom yang tidak dienkripsi).

    search_text (cari teks bebas di kolom `detail`) TERPAKSA dijalankan di
    level APLIKASI setelah query SQL, BUKAN lewat SQL ILIKE — karena `detail`
    sekarang EncryptedText (ciphertext acak di database), SQL tidak bisa
    mencocokkan pola teks asli terhadap data terenkripsi. ini trade-off yang
    disengaja: keamanan (enkripsi at-rest, SRS ISR-006) diprioritaskan di
    atas kecepatan pencarian teks bebas. Cukup untuk skala PoC (baris audit
    log tidak akan jutaan); untuk skala enterprise sungguhan butuh solusi
    seperti indeks pencarian terenkripsi terpisah (di luar cakupan PoC ini).
    """
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

    # Ambil kandidat lebih banyak dari `limit` supaya setelah difilter teks
    # (di Python, pasca-dekripsi) masih cukup hasil tersisa.
    candidates = query.limit(max(limit * 5, 500)).all()
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