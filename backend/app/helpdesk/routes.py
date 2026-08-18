"""
[PENANGGUNG JAWAB: Anggota B]
Endpoint tiket helpdesk — SRS FCR-003 poin 7 "Eskalasi otomatis". Tiket
dibuat otomatis di chat/routes.py saat confidence_score AI di bawah ambang
(settings.escalation_confidence_threshold). Router ini cuma untuk MELIHAT
tiket yang sudah dibuat — tidak ada endpoint untuk membuat tiket manual
(sesuai SRS: "sistem membuat tiket otomatis", bukan user yang membuatnya).

Dibatasi Role.IT_ADMIN — belum ada satu pun dari 8 role SRS yang benar-benar
representasi "staf human helpdesk" secara eksplisit, jadi IT Admin dipakai
sebagai analog terdekat untuk sekarang (keputusan pragmatis, bukan pemetaan
SRS yang literal).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User, HelpdeskTicket, Chat
from app.schemas import TicketResponse, TicketDetailResponse, MessageResponse
from app.auth.utils import require_role
from app.chat.routes import _display_content

router = APIRouter(prefix="/api/helpdesk", tags=["helpdesk"])


@router.get("/tickets", response_model=list[TicketResponse])
def list_tickets(
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.IT_ADMIN)),
):
    query = db.query(HelpdeskTicket).join(User, HelpdeskTicket.user_id == User.id)
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


@router.get("/tickets/{ticket_id}", response_model=TicketDetailResponse)
def get_ticket(ticket_id: str, db: Session = Depends(get_db), user: User = Depends(require_role(Role.IT_ADMIN))):
    ticket = db.query(HelpdeskTicket).filter(HelpdeskTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")

    chat = db.query(Chat).filter(Chat.id == ticket.chat_id).first()
    # "Riwayat percakapan terlampir dalam tiket" (SRS) — demasked untuk staf
    # helpdesk yang berwenang menangani, sama seperti pemilik chat aslinya.
    messages = [
        MessageResponse(
            id=m.id, sender=m.sender, content=_display_content(m),
            llm_used=m.llm_used, confidence_score=m.confidence_score, created_at=m.created_at,
        )
        for m in chat.messages
    ]

    return TicketDetailResponse(
        id=ticket.id, chat_id=ticket.chat_id, user_id=ticket.user_id, user_email=ticket.owner.email,
        confidence_score=ticket.confidence_score, status=ticket.status, created_at=ticket.created_at,
        chat_title=chat.title, messages=messages,
    )


@router.post("/tickets/{ticket_id}/close", response_model=TicketResponse)
def close_ticket(ticket_id: str, db: Session = Depends(get_db), user: User = Depends(require_role(Role.IT_ADMIN))):
    ticket = db.query(HelpdeskTicket).filter(HelpdeskTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    ticket.status = "closed"
    db.commit()
    return TicketResponse(
        id=ticket.id, chat_id=ticket.chat_id, user_id=ticket.user_id, user_email=ticket.owner.email,
        confidence_score=ticket.confidence_score, status=ticket.status, created_at=ticket.created_at,
    )
