"""
[TITIK INTEGRASI A + B]
Endpoint ini menggabungkan:
- Fungsi dari Anggota B: autentikasi, guardrail (F1-04, F2-04), audit log, simpan/ambil dari database
- Fungsi dari Anggota A: retrieval RAG, LLM switching (F1-05)
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Chat, Message, SenderType, User, HelpdeskTicket
from app.schemas import ChatCreate, ChatResponse, MessageCreate, MessageResponse, ChatReplyResponse
from app.auth.utils import get_current_user
from app.guardrail.filters import is_prompt_blocked, get_blocked_category
from app.guardrail.prompt_injection import (
    is_prompt_injection, get_matched_signals,
    is_multi_turn_injection, get_cumulative_injection_score,
)
from app.guardrail.pii_detector import detect_pii_entities, mask_pii, demask
from app.guardrail.audit_log import log_guardrail_event, EventType
from app.guardrail.rate_limiter import check_chat_rate_limit
from app.rag.vectorstore import retrieve_context
from app.llm.router import route_and_generate
from app.llm.commercial_llm import call_commercial_llm, CommercialLLMError
from app.chat.pdf_export import generate_pdf


router = APIRouter(prefix="/api/chat", tags=["chat"])

GUARDRAIL_REFUSAL_MESSAGE = (
    "Maaf, saya tidak dapat memproses pertanyaan tersebut karena melanggar kebijakan penggunaan. "
    "Silakan ajukan pertanyaan lain."
)


def _mask_for_storage(text: str, entities: list[dict] | None = None) -> tuple[str, str | None]:
    """
    Siapkan (content, pii_mapping) untuk disimpan ke kolom Message — SRS
    FCR-003 poin 3.j: histori WAJIB dalam bentuk sudah di-mask. Kembalikan
    pii_mapping sebagai None (bukan "{}") kalau tidak ada PII, supaya kolom
    di DB tetap NULL untuk pesan biasa (bukan string JSON kosong di mana-mana).
    """
    if entities is None:
        entities = detect_pii_entities(text)
    if not entities:
        return text, None
    masked_text, mapping = mask_pii(text, entities=entities)
    return masked_text, json.dumps(mapping, ensure_ascii=False)


def _display_content(msg: Message) -> str:
    """
    Kembalikan isi pesan yang SIAP ditampilkan ke pemilik chat: demasked
    kembali ke data asli kalau pesan ini punya pii_mapping tersimpan. Dipakai
    di endpoint yang menampilkan riwayat (get_messages, export_pdf) — BUKAN
    di respons langsung setelah kirim pesan (send_message sudah pakai
    result.reply yang belum sempat di-mask sama sekali, jadi tidak perlu
    di-demask ulang).
    """
    if not msg.pii_mapping:
        return msg.content
    return demask(msg.content, json.loads(msg.pii_mapping))


@router.post("", response_model=ChatResponse)
def create_chat(payload: ChatCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """[B] Buat sesi percakapan baru."""
    chat = Chat(user_id=user.id, title=payload.title)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    log_guardrail_event(db, user.id, EventType.CHAT_CREATED, detail=f"chat_id={chat.id}, title={payload.title}")
    return chat


@router.get("/history", response_model=list[ChatResponse])
def get_chat_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """[B] Ambil daftar percakapan milik user yang sedang login."""
    return db.query(Chat).filter(Chat.user_id == user.id).order_by(Chat.created_at.desc()).all()


@router.get("/{chat_id}/messages", response_model=list[MessageResponse])
def get_messages(chat_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    [B] Ambil semua pesan dalam satu percakapan.
    Isi pesan tersimpan dalam bentuk masked (SRS 3.j) — di-demask di sini
    khusus untuk pemilik chat yang sah (endpoint ini sudah dijaga
    `Chat.user_id == user.id` di atas), supaya dia tetap lihat data asli.
    """
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
    return [
        MessageResponse(
            id=m.id, sender=m.sender, content=_display_content(m),
            llm_used=m.llm_used, confidence_score=m.confidence_score, created_at=m.created_at,
        )
        for m in chat.messages
    ]


@router.delete("/{chat_id}")
def delete_chat(chat_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """[B] Hapus percakapan beserta seluruh pesannya."""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    # Log SEBELUM benar-benar dihapus — setelah ini, chat & pesannya lenyap
    # permanen, jadi ini satu-satunya kesempatan mencatat chat.title dan
    # jumlah pesannya sebelum hilang (aksi destruktif, sebelumnya TIDAK ADA
    # jejak sama sekali kalau ada chat yang terhapus).
    message_count = db.query(Message).filter(Message.chat_id == chat.id).count()
    log_guardrail_event(
        db, user.id, EventType.CHAT_DELETED,
        detail=f"chat_id={chat.id}, title={chat.title}",
        metadata={"message_count": message_count},
    )

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
    1. [B] Rate limiting per-user (F2-04 / SRS Model Usage Policy poin c-d)
    2. [B] Validasi chat milik user
    3. [B] Guardrail dasar (F1-04) + lanjutan (F2-04) — BALAS NORMAL (bukan error) kalau ditolak
    4. [B] Simpan pesan user ke database
    5. [A] Retrieval — cari potongan dokumen relevan (RAG)
    6. [A+B] LLM switching + guardrail before/after LLM (masking PII, output filter)
    7. [B] Simpan jawaban AI ke database + catat audit log (dengan detail lengkap)
    """
    # ---------- Rate limiting (paling murah, dicek paling awal) ----------
    check_chat_rate_limit(db, user.id)

    chat = db.query(Chat).filter(Chat.id == payload.chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    # ---------- Guardrail F1-04 & F2-04 (before LLM) ----------
    is_blocked = is_prompt_blocked(payload.content)
    is_injection = is_prompt_injection(payload.content)

    # ---------- Guardrail lintas-giliran: cuma perlu dicek kalau pesan ----------
    # SEKARANG belum ke-flag sendirian — kalau sudah, cek kumulatif jadi
    # tidak relevan lagi (sudah pasti diblokir juga).
    is_multi_turn = False
    if not is_blocked and not is_injection:
        recent_user_texts = [
            m.content for m in
            db.query(Message)
            .filter(Message.chat_id == chat.id, Message.sender == SenderType.user)
            .order_by(Message.created_at.desc())
            .limit(3)
            .all()
        ]
        is_multi_turn = is_multi_turn_injection(payload.content, recent_user_texts)

    if is_blocked or is_injection or is_multi_turn:
        event_type = EventType.PROMPT_BLOCKED if is_blocked else EventType.INJECTION_BLOCKED

        # dict biasa yang diisi bertahap (bukan reassignment) — supaya kalau
        # is_blocked & is_injection kebetulan sama-sama True di satu pesan
        # yang sama, metadata-nya TERGABUNG, bukan salah satu ketimpa.
        metadata: dict = {}
        if is_blocked:
            metadata["category"] = get_blocked_category(payload.content)
        if is_injection or is_multi_turn:
            metadata["matched_patterns"] = get_matched_signals(payload.content)
        if is_multi_turn:
            metadata["multi_turn"] = True
            metadata["cumulative_score"] = get_cumulative_injection_score(payload.content, recent_user_texts)
        metadata = metadata or None
        log_guardrail_event(db, user.id, event_type, detail=payload.content[:200], metadata=metadata)

        # Simpan tetap dalam bentuk masked (SRS 3.j) meski pesannya diblokir
        # sebelum sempat diproses LLM — PII di pesan tetap PII, terlepas dari
        # apakah pesannya lolos guardrail lain atau tidak.
        blocked_content, blocked_pii_mapping = _mask_for_storage(payload.content)
        user_msg = Message(chat_id=chat.id, sender=SenderType.user, content=blocked_content, pii_mapping=blocked_pii_mapping)
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

    # ---------- Deteksi PII SEKALI di sini, dipakai untuk 2 keperluan ----------
    # (1) masking sebelum simpan ke histori (SRS 3.j), (2) diteruskan ke
    # route_and_generate supaya Presidio tidak jalan ulang untuk teks yang
    # sama persis (lihat parameter pii_entities baru di router.py).
    user_pii_entities = detect_pii_entities(payload.content)
    stored_user_content, user_pii_mapping = _mask_for_storage(payload.content, entities=user_pii_entities)

    user_msg = Message(chat_id=chat.id, sender=SenderType.user, content=stored_user_content, pii_mapping=user_pii_mapping)
    db.add(user_msg)
    db.commit()

    from app.llm.router import get_standalone_query
    search_query = await get_standalone_query(payload.content, chat_history, payload.llm_provider)

    query_lower = search_query.lower()
    if "summarize" in query_lower or "summary" in query_lower or "ringkas" in query_lower:
        from app.rag.vectorstore import get_all_session_chunks, has_session_document
        context_chunks = get_all_session_chunks(chat_id=chat.id, limit=15)
        session_has_document = has_session_document(chat_id=chat.id)
    else:
        from app.rag.vectorstore import has_session_document
        context_chunks = retrieve_context(search_query, chat_id=chat.id, collection_name="kb_general", top_k=10)
        session_has_document = has_session_document(chat_id=chat.id)

    try:
        result = await route_and_generate(
            payload.content, context_chunks, chat_history, payload.llm_provider,
            pii_entities=user_pii_entities,
            session_has_document=session_has_document,
        )
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

    # Jawaban AI juga bisa mengandung PII — entah karena mengulang balik data
    # yang user kirim, atau mengutip data dari dokumen RAG yang di-upload.
    # Ini teks BARU (hasil generate), jadi deteksi PII-nya tidak bisa reuse
    # dari mana pun, harus dihitung sendiri di sini.
    stored_ai_content, ai_pii_mapping = _mask_for_storage(result.reply)

    ai_msg = Message(
        chat_id=chat.id,
        sender=SenderType.assistant,
        content=stored_ai_content,
        pii_mapping=ai_pii_mapping,
        llm_used=result.llm_used,
        confidence_score=result.confidence_score,
    )
    db.add(ai_msg)
    db.commit()

    # ---------- FCR-003 poin 7: Eskalasi otomatis ke human helpdesk ----------
    # Confidence None (percakapan umum tanpa RAG) sengaja TIDAK memicu ini —
    # itu bukan "jawaban tidak meyakinkan", memang tidak relevan diberi skor
    # (lihat router.py: confidence dipaksa None kalau context_chunks kosong).
    escalated = False
    if result.confidence_score is not None and result.confidence_score < settings.escalation_confidence_threshold:
        ticket = HelpdeskTicket(
            chat_id=chat.id, user_id=user.id, message_id=ai_msg.id,
            confidence_score=result.confidence_score,
        )
        db.add(ticket)
        db.commit()
        escalated = True
        log_guardrail_event(
            db, user.id, EventType.HELPDESK_ESCALATED,
            detail=f"chat_id={chat.id}, ticket_id={ticket.id}",
            metadata={"confidence_score": result.confidence_score},
        )

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
        escalated=escalated,
    )

@router.get("/{chat_id}/export-pdf")
def export_pdf(chat_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """[B] Ekspor riwayat percakapan menjadi PDF."""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    messages = [
        {"role": "user" if msg.sender == SenderType.user else "assistant", "content": _display_content(msg)}
        for msg in chat.messages
    ]

    model_used = "Various"
    for msg in reversed(chat.messages):
        if msg.sender == SenderType.assistant and msg.llm_used:
            model_used = msg.llm_used
            break

    try:
        pdf_bytes = generate_pdf(session_title=chat.title, messages=messages, model_used=model_used)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal generate PDF: {str(e)}")

    # Data keluar sistem sebagai file — jalur potensial kebocoran data,
    # dicatat siapa yang export chat mana dan kapan.
    log_guardrail_event(db, user.id, EventType.CHAT_EXPORTED, detail=f"chat_id={chat.id}, title={chat.title}")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="chat_{chat_id}.pdf"'}
    )