"""WebSocket chat real-time untuk tiket helpdesk — "human helpdesk" (SRS poin 7) sebagai percakapan langsung user<->admin, bukan tiket satu-arah."""
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import Role, Chat, HelpdeskTicket, HelpdeskMessage, HelpdeskSender, TicketStatus
from app.schemas import HelpdeskMessageResponse
from app.auth.utils import resolve_user_from_token
from app.helpdesk.routes import serialize_helpdesk_message

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, ticket_id: str, ws: WebSocket):
        await ws.accept()
        self._connections[ticket_id].append(ws)

    def disconnect(self, ticket_id: str, ws: WebSocket):
        if ws in self._connections.get(ticket_id, []):
            self._connections[ticket_id].remove(ws)
        if not self._connections.get(ticket_id):
            self._connections.pop(ticket_id, None)

    async def broadcast(self, ticket_id: str, payload: dict):
        for ws in list(self._connections.get(ticket_id, [])):
            try:
                await ws.send_json(payload)
            except Exception:
                pass


manager = ConnectionManager()


@router.websocket("/ws/helpdesk/tickets/{ticket_id}")
async def ticket_chat(websocket: WebSocket, ticket_id: str, token: str = Query(...)):
    # Depends() tidak jalan otomatis di @websocket seperti di @router.get -- Session dibuat manual per koneksi, ditutup di finally
    db: Session = SessionLocal()
    try:
        try:
            user = resolve_user_from_token(token, db)
        except Exception:
            await websocket.close(code=4401)
            return

        ticket = db.query(HelpdeskTicket).filter(HelpdeskTicket.id == ticket_id).first()
        if not ticket:
            await websocket.close(code=4404)
            return
        # Aturan akses SAMA dengan REST (_get_ticket_or_403): admin divisi lain
        # tidak boleh ikut nimbrung di tiket yang bukan tanggung jawabnya.
        is_handler = user.role == Role.IT_ADMIN and user.divisi == ticket.target_divisi
        if ticket.user_id != user.id and not is_handler:
            await websocket.close(code=4403)
            return

        sender_role = HelpdeskSender.USER if user.id == ticket.user_id else HelpdeskSender.ADMIN

        await manager.connect(ticket_id, websocket)
        try:
            while True:
                data = await websocket.receive_json()
                content = (data.get("content") or "").strip()
                if not content:
                    continue

                db.refresh(ticket)  # tiket yang sudah ditutup admin tidak bisa dilanjutkan chatnya
                if ticket.status == TicketStatus.CLOSED:
                    await websocket.send_json({"error": "Tiket ini sudah ditutup"})
                    continue

                # Lampiran percakapan cuma sah kalau chat itu MILIK pengirim —
                # kalau tidak, lampiran jadi jalan pintas membaca chat orang lain.
                attached_id = data.get("attached_chat_id") or None
                if attached_id:
                    owns = db.query(Chat).filter(Chat.id == attached_id, Chat.user_id == user.id).first()
                    if not owns:
                        await websocket.send_json({"error": "Percakapan yang dilampirkan tidak ditemukan"})
                        continue

                msg = HelpdeskMessage(
                    ticket_id=ticket_id, sender_role=sender_role,
                    sender_id=user.id, content=content, attached_chat_id=attached_id,
                )
                db.add(msg)
                db.commit()
                db.refresh(msg)

                await manager.broadcast(
                    ticket_id,
                    serialize_helpdesk_message(msg, db).model_dump(mode="json"),
                )
        except WebSocketDisconnect:
            pass
        finally:
            manager.disconnect(ticket_id, websocket)
    finally:
        db.close()
