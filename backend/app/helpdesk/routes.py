"""
[PENANGGUNG JAWAB: Anggota B]
Endpoint tiket helpdesk — SRS FCR-003 poin 7 "Eskalasi otomatis". Sesuai
teks SRS literal ("sistem MENAWARKAN eskalasi ke human helpdesk"), tiket
TIDAK dibuat otomatis oleh sistem lagi — chat/routes.py cuma menandai
jawaban sebagai escalation_offered=True, lalu USER sendiri yang konfirmasi
lewat POST /tickets di bawah kalau mau lanjut. "Human helpdesk" di sini
diimplementasikan sebagai chat real-time (lihat helpdesk/ws.py untuk
WebSocket-nya), bukan cuma tiket satu-arah yang dibaca sepihak oleh admin.

list_tickets/close_ticket tetap dibatasi Role.IT_ADMIN (belum ada role SRS
yang eksplisit representasi staf helpdesk, jadi IT Admin dipakai sebagai
analog terdekat). get_ticket & POST /tickets bisa diakses PEMILIK tiket
ATAU IT_ADMIN — pemilik perlu baca/kirim pesan di tiketnya sendiri.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User, HelpdeskTicket, HelpdeskMessage, HelpdeskSender, Chat, Message, SenderType, TicketStatus
from app.schemas import (
    TicketResponse, TicketDetailResponse, MessageResponse,
    CreateTicketRequest, HelpdeskMessageResponse,
)
from app.auth.utils import require_role, get_current_user
from app.chat.routes import _display_content
from app.guardrail.audit_log import log_guardrail_event, EventType

router = APIRouter(prefix="/api/helpdesk", tags=["helpdesk"])


def _get_ticket_or_403(ticket_id: str, db: Session, user: User) -> HelpdeskTicket:
    """Dipakai bersama oleh get_ticket() dan handshake WebSocket (helpdesk/ws.py)."""
    ticket = db.query(HelpdeskTicket).filter(HelpdeskTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    if ticket.user_id != user.id and user.role != Role.IT_ADMIN:
        raise HTTPException(status_code=403, detail="Anda tidak berhak mengakses tiket ini")
    return ticket


def _ticket_detail(ticket: HelpdeskTicket, db: Session) -> TicketDetailResponse:
    chat = db.query(Chat).filter(Chat.id == ticket.chat_id).first()
    # "Riwayat percakapan terlampir dalam tiket" (SRS) — demasked untuk pihak
    # yang berwenang (pemilik chat aslinya, atau staf helpdesk yang menangani).
    messages = [
        MessageResponse(
            id=m.id, sender=m.sender, content=_display_content(m),
            llm_used=m.llm_used, confidence_score=m.confidence_score, created_at=m.created_at,
        )
        for m in chat.messages
    ]
    ticket_messages = (
        db.query(HelpdeskMessage)
        .filter(HelpdeskMessage.ticket_id == ticket.id)
        .order_by(HelpdeskMessage.created_at)
        .all()
    )
    return TicketDetailResponse(
        id=ticket.id, chat_id=ticket.chat_id, user_id=ticket.user_id, user_email=ticket.owner.email,
        confidence_score=ticket.confidence_score, status=ticket.status, created_at=ticket.created_at,
        chat_title=chat.title,
        messages=messages,
        ticket_messages=[HelpdeskMessageResponse.model_validate(m) for m in ticket_messages],
    )


@router.get("/tickets", response_model=list[TicketResponse])
def list_tickets(
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    IT Admin melihat SEMUA tiket (antrian helpdesk). User biasa cuma boleh
    lihat tiketnya SENDIRI — dipaksa lewat filter user_id, bukan lewat
    require_role, supaya user bisa navigasi balik ke tiket aktifnya sendiri
    (lihat chat/page.jsx sidebar) tanpa endpoint terpisah.
    """
    query = db.query(HelpdeskTicket).join(User, HelpdeskTicket.user_id == User.id)
    if user.role != Role.IT_ADMIN:
        query = query.filter(HelpdeskTicket.user_id == user.id)
    if status:
        query = query.filter(HelpdeskTicket.status == status)
    tickets = query.order_by(HelpdeskTicket.created_at.desc()).all()
    return [
        TicketResponse(
            id=t.id, chat_id=t.chat_id, user_id=t.user_id, user_email=t.owner.email,
            confidence_score=t.confidence_score, status=t.status, created_at=t.created_at,
        )
        for t in tickets
    ]


@router.post("/tickets", response_model=TicketDetailResponse)
def create_ticket(
    payload: CreateTicketRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    2 jalur eskalasi, User SENDIRI yang memutuskan keduanya (SRS: "sistem
    menawarkan eskalasi" — bukan langsung membuat tiket tanpa izin):

    1. message_id TERISI — dari banner tawaran confidence rendah, mengikat
       tiket ke jawaban AI spesifik yang memicu.
    2. message_id KOSONG — tombol "Hubungi Admin" yang SELALU terlihat di
       chat, tidak bergantung skor confidence ATAU AI menebak-nebak niat
       user dari kalimat bebas. Ditambahkan setelah didiskusikan: deteksi
       niat lewat LLM ("saya mau bicara admin") punya masalah discoverability
       — user yang tidak tahu "kalimat sakti" apa pun tidak akan pernah
       ketemu fitur ini. Tombol permanen jauh lebih pasti & mudah ditemukan.
    """
    chat = db.query(Chat).filter(Chat.id == payload.chat_id).first()
    if not chat or chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    if payload.message_id is None:
        # Jalur manual — cegah spam tiket kalau tombol diklik berkali-kali:
        # pakai ulang tiket "open" yang sudah ada utk chat ini kalau ada.
        existing_manual = (
            db.query(HelpdeskTicket)
            .filter(HelpdeskTicket.chat_id == chat.id, HelpdeskTicket.message_id.is_(None), HelpdeskTicket.status == TicketStatus.OPEN)
            .first()
        )
        if existing_manual:
            return _ticket_detail(existing_manual, db)

        ticket = HelpdeskTicket(chat_id=chat.id, user_id=user.id, message_id=None, confidence_score=None)
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        log_guardrail_event(
            db, user.id, EventType.HELPDESK_ESCALATED,
            detail=f"chat_id={chat.id}, ticket_id={ticket.id} (manual, tombol Hubungi Admin)",
            metadata={"manual": True},
        )
        return _ticket_detail(ticket, db)

    # ---------- Jalur banner confidence rendah (perilaku lama, tidak berubah) ----------
    message = db.query(Message).filter(Message.id == payload.message_id).first()
    if not message or message.sender != SenderType.assistant:
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan")
    if message.chat_id != chat.id:
        raise HTTPException(status_code=400, detail="Pesan ini bukan bagian dari percakapan yang dimaksud")
    if message.confidence_score is None:
        raise HTTPException(status_code=400, detail="Pesan ini tidak memenuhi syarat eskalasi")

    existing = db.query(HelpdeskTicket).filter(HelpdeskTicket.message_id == message.id).first()
    if existing:
        return _ticket_detail(existing, db)

    ticket = HelpdeskTicket(
        chat_id=chat.id, user_id=user.id, message_id=message.id,
        confidence_score=message.confidence_score,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    log_guardrail_event(
        db, user.id, EventType.HELPDESK_ESCALATED,
        detail=f"chat_id={chat.id}, ticket_id={ticket.id}",
        metadata={"confidence_score": message.confidence_score},
    )
    return _ticket_detail(ticket, db)


@router.get("/tickets/{ticket_id}", response_model=TicketDetailResponse)
def get_ticket(ticket_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ticket = _get_ticket_or_403(ticket_id, db, user)
    return _ticket_detail(ticket, db)


@router.post("/tickets/{ticket_id}/close", response_model=TicketResponse)
def close_ticket(ticket_id: str, db: Session = Depends(get_db), user: User = Depends(require_role(Role.IT_ADMIN))):
    ticket = db.query(HelpdeskTicket).filter(HelpdeskTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    ticket.status = "closed"
    db.commit()
    log_guardrail_event(
        db, user.id, EventType.HELPDESK_TICKET_CLOSED,
        detail=f"ticket_id={ticket.id}",
    )
    return TicketResponse(
        id=ticket.id, chat_id=ticket.chat_id, user_id=ticket.user_id, user_email=ticket.owner.email,
        confidence_score=ticket.confidence_score, status=ticket.status, created_at=ticket.created_at,
    )
