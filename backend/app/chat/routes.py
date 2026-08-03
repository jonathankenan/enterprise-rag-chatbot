"""
[TITIK INTEGRASI A + B]
Endpoint ini menggabungkan:
- Fungsi dari Anggota B: autentikasi (get_current_user), simpan/ambil dari database
- Fungsi dari Anggota A: retrieval RAG, LLM switching (on-prem/commercial)

Kerjakan file ini BERSAMA setelah masing-masing fungsi dasar (auth & RAG) siap.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Chat, Message, SenderType, User
from app.schemas import ChatCreate, ChatResponse, MessageCreate, MessageResponse, ChatReplyResponse
from app.auth.utils import get_current_user
from app.guardrail.filters import is_prompt_blocked
from app.rag.vectorstore import retrieve_context
from app.llm.router import route_and_generate

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def create_chat(payload: ChatCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """[B] Buat sesi percakapan baru."""
    chat = Chat(user_id=user.id, title=payload.title)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


@router.get("/history", response_model=list[ChatResponse])
def get_chat_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """[B] Ambil daftar percakapan milik user yang sedang login."""
    return db.query(Chat).filter(Chat.user_id == user.id).order_by(Chat.created_at.desc()).all()


@router.get("/{chat_id}/messages", response_model=list[MessageResponse])
def get_messages(chat_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """[B] Ambil semua pesan dalam satu percakapan."""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
    return chat.messages


@router.post("/message", response_model=ChatReplyResponse)
async def send_message(
    payload: MessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Endpoint utama chat — alur lengkap F1-03, F1-04, F1-05:
    1. [B] Validasi chat milik user
    2. [B] Guardrail — tolak kalau prompt terlarang
    3. [B] Simpan pesan user ke database
    4. [A] Retrieval — cari potongan dokumen relevan (RAG)
    5. [A] LLM switching — pilih on-prem/commercial, hasilkan jawaban
    6. [B] Simpan jawaban AI ke database
    """
    chat = db.query(Chat).filter(Chat.id == payload.chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    if is_prompt_blocked(payload.content):
        raise HTTPException(status_code=400, detail="Pertanyaan mengandung konten yang tidak diizinkan")

    user_msg = Message(chat_id=chat.id, sender=SenderType.user, content=payload.content)
    db.add(user_msg)
    db.commit()

    context_chunks = retrieve_context(payload.content, collection_name="kb_general", top_k=3)
    result = await route_and_generate(payload.content, context_chunks)

    ai_msg = Message(
        chat_id=chat.id,
        sender=SenderType.assistant,
        content=result.reply,
        llm_used=result.llm_used,
    )
    db.add(ai_msg)
    db.commit()

    return ChatReplyResponse(
        reply=result.reply,
        llm_used=result.llm_used,
        is_sensitive=result.is_sensitive,
        sources=context_chunks,
    )
