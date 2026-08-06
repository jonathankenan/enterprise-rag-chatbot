"""
[TITIK INTEGRASI A + B]
Endpoint ini menggabungkan:
- Fungsi dari Anggota B: autentikasi (get_current_user), simpan/ambil dari database
- Fungsi dari Anggota A: retrieval RAG, LLM switching (on-prem/commercial)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Chat, Message, SenderType, User
from app.schemas import ChatCreate, ChatResponse, MessageCreate, MessageResponse, ChatReplyResponse
from app.auth.utils import get_current_user
from app.guardrail.filters import is_prompt_blocked
from app.guardrail.prompt_injection import is_prompt_injection
from app.rag.vectorstore import retrieve_context
from app.llm.router import route_and_generate
from app.llm.commercial_llm import call_commercial_llm, CommercialLLMError

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


@router.delete("/{chat_id}")
def delete_chat(chat_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """[B] Hapus percakapan beserta seluruh pesannya."""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    db.query(Message).filter(Message.chat_id == chat.id).delete()
    db.delete(chat)
    db.commit()
    return {"detail": "Percakapan berhasil dihapus"}


@router.post("/message", response_model=ChatReplyResponse)
async def send_message(
    payload: MessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Endpoint utama chat — alur lengkap F1-03, F1-04, F1-05, F2-04:
    1. [B] Validasi chat milik user
    2. [B] Guardrail dasar — tolak kalau prompt terlarang (F1-04)
    3. [B] Guardrail lanjutan — tolak kalau terdeteksi prompt injection (F2-04)
    4. [B] Simpan pesan user ke database
    5. [A] Retrieval — cari potongan dokumen relevan (RAG)
    6. [A] LLM switching — pilih on-prem/commercial (PII otomatis dipaksa on-prem, F2-04)
    7. [B] Simpan jawaban AI ke database
    """
    chat = db.query(Chat).filter(Chat.id == payload.chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    if is_prompt_blocked(payload.content):
        raise HTTPException(status_code=400, detail="Pertanyaan mengandung konten yang tidak diizinkan")

    if is_prompt_injection(payload.content):
        raise HTTPException(status_code=400, detail="Prompt terdeteksi sebagai percobaan manipulasi instruksi sistem")

    chat_history = db.query(Message).filter(Message.chat_id == chat.id).order_by(Message.created_at.desc()).limit(6).all()
    chat_history.reverse()

    user_msg = Message(chat_id=chat.id, sender=SenderType.user, content=payload.content)
    db.add(user_msg)
    db.commit()

    context_chunks = retrieve_context(payload.content, chat_id=chat.id, collection_name="kb_general", top_k=5)

    try:
        result = await route_and_generate(payload.content, context_chunks, chat_history, payload.llm_provider)
    except CommercialLLMError as e:
        raise HTTPException(status_code=502, detail=str(e))

    ai_msg = Message(
        chat_id=chat.id,
        sender=SenderType.assistant,
        content=result.reply,
        llm_used=result.llm_used,
        confidence_score=result.confidence_score,
    )
    db.add(ai_msg)
    db.commit()

    new_title = None
    if chat.title == "Percakapan Baru":
        try:
            prompt = f"Buatlah judul singkat (maksimal 3-5 kata) yang merangkum pesan berikut. Hanya kembalikan teks judulnya saja, tanpa tanda kutip atau penjelasan apapun.\n\nPesan: {payload.content}"
            new_title = await call_commercial_llm(prompt)
            chat.title = new_title
            db.commit()
        except Exception as e:
            print("Gagal generate judul:", e)

    return ChatReplyResponse(
        reply=result.reply,
        llm_used=result.llm_used,
        is_sensitive=result.is_sensitive,
        confidence_score=result.confidence_score,
        sources=context_chunks,
        new_title=new_title,
    )