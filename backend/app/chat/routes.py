"""
[TITIK INTEGRASI A + B]
Endpoint ini menggabungkan:
- Fungsi dari Anggota B: autentikasi, guardrail (F1-04, F2-04), audit log, simpan/ambil dari database
- Fungsi dari Anggota A: retrieval RAG, LLM switching (F1-05)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Chat, Message, SenderType, User
from app.schemas import ChatCreate, ChatResponse, MessageCreate, MessageResponse, ChatReplyResponse
from app.auth.utils import get_current_user
from app.guardrail.filters import is_prompt_blocked
from app.guardrail.prompt_injection import is_prompt_injection, get_matched_signals
from app.guardrail.audit_log import log_guardrail_event, EventType
from app.rag.vectorstore import retrieve_context
from app.llm.router import route_and_generate
from app.llm.commercial_llm import call_commercial_llm, CommercialLLMError

router = APIRouter(prefix="/api/chat", tags=["chat"])

GUARDRAIL_REFUSAL_MESSAGE = (
    "Maaf, saya tidak dapat memproses pertanyaan tersebut karena melanggar kebijakan penggunaan. "
    "Silakan ajukan pertanyaan lain."
)


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
    2. [B] Guardrail dasar (F1-04) + lanjutan (F2-04) — BALAS NORMAL (bukan error) kalau ditolak
    3. [B] Simpan pesan user ke database
    4. [A] Retrieval — cari potongan dokumen relevan (RAG)
    5. [A+B] LLM switching + guardrail before/after LLM (masking PII, output filter)
    6. [B] Simpan jawaban AI ke database + catat audit log (dengan detail lengkap)
    """
    chat = db.query(Chat).filter(Chat.id == payload.chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    # ---------- Guardrail F1-04 & F2-04 (before LLM) ----------
    is_blocked = is_prompt_blocked(payload.content)
    is_injection = is_prompt_injection(payload.content)

    if is_blocked or is_injection:
        event_type = EventType.PROMPT_BLOCKED if is_blocked else EventType.INJECTION_BLOCKED
        metadata = {"matched_patterns": get_matched_signals(payload.content)} if is_injection else None
        log_guardrail_event(db, user.id, event_type, detail=payload.content[:200], metadata=metadata)

        user_msg = Message(chat_id=chat.id, sender=SenderType.user, content=payload.content)
        db.add(user_msg)
        ai_msg = Message(
            chat_id=chat.id, sender=SenderType.assistant,
            content=GUARDRAIL_REFUSAL_MESSAGE, llm_used="blocked",
        )
        db.add(ai_msg)
        db.commit()

        return ChatReplyResponse(
            reply=GUARDRAIL_REFUSAL_MESSAGE,
            llm_used="blocked",
            is_sensitive=False,
            confidence_score=None,
            pii_detected=False,
            sources=[],
            new_title=None,
        )

    chat_history = db.query(Message).filter(Message.chat_id == chat.id).order_by(Message.created_at.desc()).limit(6).all()
    chat_history.reverse()

    user_msg = Message(chat_id=chat.id, sender=SenderType.user, content=payload.content)
    db.add(user_msg)
    db.commit()

    from app.llm.router import get_standalone_query
    search_query = await get_standalone_query(payload.content, chat_history, payload.llm_provider)

    query_lower = search_query.lower()
    if "summarize" in query_lower or "summary" in query_lower or "ringkas" in query_lower:
        from app.rag.vectorstore import get_all_session_chunks
        context_chunks = get_all_session_chunks(chat_id=chat.id, limit=15)
    else:
        context_chunks = retrieve_context(search_query, chat_id=chat.id, collection_name="kb_general", top_k=10)

    try:
        result = await route_and_generate(payload.content, context_chunks, chat_history, payload.llm_provider)
    except CommercialLLMError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # ---------- Audit log untuk kejadian F2-04 di dalam alur LLM (dengan detail lengkap) ----------
    if result.pii_detected:
        log_guardrail_event(
            db, user.id, EventType.PII_DETECTED,
            detail=f"chat_id={chat.id}",
            metadata={
                "llm_used": result.llm_used,
                "pii_types": [e["type"] for e in result.pii_entities],
                "pii_count": len(result.pii_entities),
            },
        )

    if result.output_blocked_category:
        log_guardrail_event(
            db, user.id, EventType.OUTPUT_BLOCKED,
            detail=f"chat_id={chat.id}",
            metadata={"category": result.output_blocked_category, "llm_used": result.llm_used},
        )

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
        pii_detected=result.pii_detected,
        sources=context_chunks,
        new_title=new_title,
    )