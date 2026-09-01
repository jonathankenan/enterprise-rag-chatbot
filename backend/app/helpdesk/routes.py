"""Endpoint tiket helpdesk (SRS poin 7) — sistem cuma MENAWARKAN eskalasi, user sendiri yang konfirmasi. "Human helpdesk" diimplementasikan sebagai chat real-time (lihat helpdesk/ws.py)."""
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


# ---------- Hierarki eskalasi (SRS hal. 64/68/70: "Admin IT" vs "Admin User [divisi]") ----------
# User biasa divisi X  -> IT Admin divisi X
# IT Admin divisi X    -> IT Admin GLOBAL
# IT Admin global      -> tidak punya atasan, jadi tidak bisa membuat tiket
# Tujuannya: admin divisi tidak kebanjiran tiket divisi lain, dan admin global
# hanya menangani eskalasi yang benar-benar tidak selesai di tingkat divisi.

def resolve_target_divisi(user: User) -> str | None:
    """Divisi penanggung jawab tiket yang dibuat `user`. Raise 400 kalau user tidak punya atasan."""
    if user.role == Role.IT_ADMIN:
        if user.divisi is None:
            raise HTTPException(status_code=400, detail="IT Admin global tidak memiliki admin di atasnya untuk dihubungi")
        return None  # admin divisi -> naik ke admin global
    if user.divisi is None:
        raise HTTPException(status_code=400, detail="Akun Anda belum terdaftar di divisi mana pun, hubungi IT Admin")
    return user.divisi


def _is_handler(ticket: HelpdeskTicket, user: User) -> bool:
    """True kalau `user` adalah admin yang MENANGANI tiket ini (bukan sekadar IT Admin mana pun)."""
    if user.role != Role.IT_ADMIN:
        return False
    return user.divisi == ticket.target_divisi


def _get_ticket_or_403(ticket_id: str, db: Session, user: User) -> HelpdeskTicket:
    """Dipakai bersama oleh get_ticket() dan handshake WebSocket (helpdesk/ws.py)."""
    ticket = db.query(HelpdeskTicket).filter(HelpdeskTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    # Admin divisi LAIN sengaja ditolak — sebelumnya semua IT Admin bisa
    # membuka tiket siapa pun, yang menembus isolasi antar-divisi.
    if ticket.user_id != user.id and not _is_handler(ticket, user):
        raise HTTPException(status_code=403, detail="Anda tidak berhak mengakses tiket ini")
    return ticket


def serialize_helpdesk_message(msg: HelpdeskMessage, db: Session) -> HelpdeskMessageResponse:
    """Lampiran percakapan dibawa sebagai id + judul, supaya UI bisa menampilkan chip tanpa query tambahan."""
    title = None
    if msg.attached_chat_id:
        chat = db.query(Chat).filter(Chat.id == msg.attached_chat_id).first()
        title = chat.title if chat else "(percakapan dihapus)"
    return HelpdeskMessageResponse(
        id=msg.id, ticket_id=msg.ticket_id, sender_role=msg.sender_role, sender_id=msg.sender_id,
        content=msg.content, attached_chat_id=msg.attached_chat_id, attached_chat_title=title,
        created_at=msg.created_at,
    )


def _ticket_detail(ticket: HelpdeskTicket, db: Session) -> TicketDetailResponse:
    # Riwayat chat AI TIDAK lagi dilampirkan otomatis di sini — konteks sekarang
    # dipilih user secara eksplisit per pesan (attached_chat_id), supaya tiket
    # tidak terikat ke satu percakapan.
    chat = db.query(Chat).filter(Chat.id == ticket.chat_id).first() if ticket.chat_id else None
    ticket_messages = (
        db.query(HelpdeskMessage)
        .filter(HelpdeskMessage.ticket_id == ticket.id)
        .order_by(HelpdeskMessage.created_at)
        .all()
    )
    return TicketDetailResponse(
        id=ticket.id, chat_id=ticket.chat_id, user_id=ticket.user_id, user_email=ticket.owner.email,
        confidence_score=ticket.confidence_score, target_divisi=ticket.target_divisi, status=ticket.status, created_at=ticket.created_at,
        chat_title=chat.title if chat else None,
        ticket_messages=[serialize_helpdesk_message(m, db) for m in ticket_messages],
    )


@router.get("/tickets", response_model=list[TicketResponse])
def list_tickets(
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """IT Admin melihat tiket yang DIA tangani saja (divisi sendiri, atau — untuk admin global — tiket dari para admin divisi); user biasa cuma tiketnya sendiri."""
    query = db.query(HelpdeskTicket).join(User, HelpdeskTicket.user_id == User.id)
    if user.role == Role.IT_ADMIN:
        # Admin divisi PTI cuma lihat target_divisi="PTI"; admin global cuma
        # lihat target_divisi IS NULL (yaitu tiket kiriman para admin divisi).
        if user.divisi is None:
            query = query.filter(HelpdeskTicket.target_divisi.is_(None))
        else:
            query = query.filter(HelpdeskTicket.target_divisi == user.divisi)
    else:
        query = query.filter(HelpdeskTicket.user_id == user.id)
    if status:
        query = query.filter(HelpdeskTicket.status == status)
    tickets = query.order_by(HelpdeskTicket.created_at.desc()).all()
    return [
        TicketResponse(
            id=t.id, chat_id=t.chat_id, user_id=t.user_id, user_email=t.owner.email,
            confidence_score=t.confidence_score, target_divisi=t.target_divisi, status=t.status, created_at=t.created_at,
        )
        for t in tickets
    ]


@router.get("/my-open-ticket", response_model=TicketDetailResponse | None)
def my_open_ticket(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    Tiket terbuka yang DIBUAT user ini (bukan yang dia tangani sebagai admin).
    Dibedakan tegas dari GET /tickets: untuk IT Admin divisi, /tickets berisi
    ANTREAN divisinya, sedangkan yang dibutuhkan halaman "Hubungi Admin"
    adalah percakapannya sendiri dengan admin global.
    """
    ticket = (
        db.query(HelpdeskTicket)
        .filter(HelpdeskTicket.user_id == user.id, HelpdeskTicket.status == TicketStatus.OPEN)
        .order_by(HelpdeskTicket.created_at.desc())
        .first()
    )
    return _ticket_detail(ticket, db) if ticket else None


@router.post("/tickets", response_model=TicketDetailResponse)
def create_ticket(
    payload: CreateTicketRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    2 jalur eskalasi:
    1. message_id TERISI — dari banner confidence rendah, tiket terikat ke jawaban AI yang memicu.
    2. content TERISI — jalur "Hubungi Admin": tiket baru lahir saat user benar-benar
       mengirim pesan pertama, jadi membuka halaman saja tidak membanjiri antrean admin.
    """
    if payload.message_id:
        return _create_from_low_confidence(payload, db, user)

    if not (payload.content or "").strip():
        raise HTTPException(status_code=400, detail="Pesan tidak boleh kosong")

    target_divisi = resolve_target_divisi(user)  # menolak IT Admin global di sini

    # Satu user maksimal punya SATU tiket terbuka: percakapan dengan admin itu
    # berkelanjutan, bukan sekali-pakai. Pesan baru masuk ke tiket yang sudah
    # ada, supaya antrean admin tidak dipenuhi tiket kembar dari orang yang sama.
    existing = (
        db.query(HelpdeskTicket)
        .filter(HelpdeskTicket.user_id == user.id, HelpdeskTicket.status == TicketStatus.OPEN)
        .first()
    )
    if existing:
        attached_existing = _validate_attachment(payload.attached_chat_id, db, user)
        db.add(HelpdeskMessage(
            ticket_id=existing.id, sender_role=HelpdeskSender.USER, sender_id=user.id,
            content=payload.content.strip(), attached_chat_id=attached_existing.id if attached_existing else None,
        ))
        db.commit()
        return _ticket_detail(existing, db)

    attached = _validate_attachment(payload.attached_chat_id, db, user)

    ticket = HelpdeskTicket(user_id=user.id, chat_id=None, message_id=None, confidence_score=None, target_divisi=target_divisi)
    db.add(ticket)
    db.flush()  # butuh ticket.id untuk pesan pertama, tapi belum commit
    db.add(HelpdeskMessage(
        ticket_id=ticket.id, sender_role=HelpdeskSender.USER, sender_id=user.id,
        content=payload.content.strip(), attached_chat_id=attached.id if attached else None,
    ))
    db.commit()
    db.refresh(ticket)

    log_guardrail_event(
        db, user.id, EventType.HELPDESK_ESCALATED,
        detail=f"ticket_id={ticket.id} (manual, Hubungi Admin)",
        metadata={"manual": True, "attached_chat_id": payload.attached_chat_id},
    )
    return _ticket_detail(ticket, db)


def _validate_attachment(chat_id: str | None, db: Session, user: User) -> Chat | None:
    """User cuma boleh melampirkan percakapan MILIKNYA SENDIRI — kalau tidak, lampiran jadi jalan pintas membaca chat orang lain."""
    if not chat_id:
        return None
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan yang dilampirkan tidak ditemukan")
    return chat


def _create_from_low_confidence(payload: CreateTicketRequest, db: Session, user: User) -> TicketDetailResponse:
    chat = db.query(Chat).filter(Chat.id == payload.chat_id).first()
    if not chat or chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

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
        target_divisi=resolve_target_divisi(user),
    )
    db.add(ticket)
    db.flush()
    # Percakapan pemicu langsung dilampirkan ke pesan pembuka, supaya admin
    # tetap punya konteks tanpa perlu kolom "riwayat chat" terpisah.
    db.add(HelpdeskMessage(
        ticket_id=ticket.id, sender_role=HelpdeskSender.USER, sender_id=user.id,
        content="Jawaban AI kurang meyakinkan, mohon dibantu.", attached_chat_id=chat.id,
    ))
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


@router.get("/tickets/{ticket_id}/attached-chat/{chat_id}", response_model=list[MessageResponse])
def read_attached_chat(
    ticket_id: str, chat_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Isi percakapan yang DILAMPIRKAN ke tiket ini. Sengaja lewat jalur tiket
    (bukan GET /api/chat/{id}/messages) supaya admin cuma bisa membaca chat
    yang memang sengaja dibagikan user ke tiket, bukan chat siapa pun.
    """
    ticket = _get_ticket_or_403(ticket_id, db, user)

    is_attached = (
        db.query(HelpdeskMessage)
        .filter(HelpdeskMessage.ticket_id == ticket.id, HelpdeskMessage.attached_chat_id == chat_id)
        .first()
    )
    if not is_attached:
        raise HTTPException(status_code=404, detail="Percakapan ini tidak dilampirkan ke tiket tersebut")

    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    return [
        MessageResponse(
            id=m.id, sender=m.sender, content=_display_content(m),
            llm_used=m.llm_used, confidence_score=m.confidence_score, created_at=m.created_at,
        )
        for m in chat.messages
    ]


@router.post("/tickets/{ticket_id}/close", response_model=TicketResponse)
def close_ticket(ticket_id: str, db: Session = Depends(get_db), user: User = Depends(require_role(Role.IT_ADMIN))):
    """Yang boleh menutup adalah PIHAK YANG DIHUBUNGI — admin divisi untuk tiket divisinya, admin global untuk tiket dari admin divisi."""
    ticket = db.query(HelpdeskTicket).filter(HelpdeskTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    if not _is_handler(ticket, user):
        raise HTTPException(status_code=403, detail="Hanya admin yang menangani tiket ini yang bisa menutupnya")
    ticket.status = TicketStatus.CLOSED
    db.commit()
    log_guardrail_event(db, user.id, EventType.HELPDESK_TICKET_CLOSED, detail=f"ticket_id={ticket.id}")
    return TicketResponse(
        id=ticket.id, chat_id=ticket.chat_id, user_id=ticket.user_id, user_email=ticket.owner.email,
        confidence_score=ticket.confidence_score, target_divisi=ticket.target_divisi, status=ticket.status, created_at=ticket.created_at,
    )


@router.delete("/tickets/{ticket_id}")
def delete_ticket(ticket_id: str, db: Session = Depends(get_db), admin: User = Depends(require_role(Role.IT_ADMIN))):
    """Hapus tiket — dibatasi yang sudah CLOSED, supaya percakapan yang masih berjalan tidak bisa hilang di tengah jalan."""
    ticket = db.query(HelpdeskTicket).filter(HelpdeskTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    if not _is_handler(ticket, admin):
        raise HTTPException(status_code=403, detail="Hanya admin yang menangani tiket ini yang bisa menghapusnya")
    if ticket.status != TicketStatus.CLOSED:
        raise HTTPException(status_code=400, detail="Hanya tiket berstatus closed yang bisa dihapus")

    db.query(HelpdeskMessage).filter(HelpdeskMessage.ticket_id == ticket.id).delete()
    db.delete(ticket)
    db.commit()

    log_guardrail_event(
        db, admin.id, EventType.HELPDESK_TICKET_DELETED,
        detail=f"ticket_id={ticket_id} dihapus oleh {admin.email}",
    )
    return {"message": "Tiket dihapus"}
