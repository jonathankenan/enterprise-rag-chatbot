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
from app.models import Chat, Message, SenderType, User, SystemSettings, Role
from app.schemas import ChatCreate, ChatResponse, ChatRenameRequest, MessageCreate, MessageResponse, ChatReplyResponse, SourceCitation
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
from app.guardrail.intent_classifier import classify_intent, SKIP_RETRIEVAL_INTENTS, Intent
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


@router.patch("/{chat_id}/rename", response_model=ChatResponse)
def rename_chat(
    chat_id: str,
    payload: ChatRenameRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """[B] Ganti judul percakapan secara manual."""
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
    if chat.user_id != user.id:
        raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke chat ini.")
    old_title = chat.title
    chat.title = payload.title
    db.commit()
    db.refresh(chat)
    log_guardrail_event(
        db, user.id, EventType.CHAT_RENAMED,
        detail=f"chat_id={chat.id}, renamed from='{old_title}' to='{chat.title}'",
    )
    return chat


def _build_source_citations(context_chunks: list[dict]) -> list[SourceCitation]:
    """
    SRS FCR-003 poin 12.a: "Answers show source references". context_chunks
    sudah punya filename/page/source_type sejak retrieve_context() (lihat
    rag/vectorstore.py) -- ini DEDUP jadi satu entri per dokumen/FAQ unik
    (bukan satu per chunk, satu dokumen bisa nyumbang banyak chunk ke context
    yang sama), sambil MENGUMPULKAN semua nomor halaman yang chunk-nya ikut
    kepakai, supaya label-nya bisa jadi "file.pdf (hal. 2, 5)" bukan cuma
    "file.pdf" -- dua chunk beda halaman dari dokumen yang sama tetap satu
    entri citation, bukan dua.
    """
    order: list[str] = []          # key insertion order, buat urutan citation stabil
    labels: dict[str, str] = {}    # key -> "FAQ Helpdesk" atau nama file
    filenames: dict[str, str | None] = {}
    source_types: dict[str, str] = {}
    pages: dict[str, set[int]] = {}

    for chunk in context_chunks:
        # is_top_match ditandai retrieve_context() -- cuma 3 chunk dengan
        # similarity TERBAIK (sama seperti yang dipakai untuk confidence_score,
        # lihat komentar di sana) yang layak disebut sebagai sumber. Chunk lain
        # tetap masuk PROVIDED CONTEXT ke LLM (context_chunks di sini utuh),
        # tapi tidak semuanya "sumber jawaban ini" -- 2026-08-24, ditambahkan
        # setelah citation "FR-01" ikut menyebut 5 halaman lain yang tidak ada
        # kaitan sama sekali (cuma "di sekitar secara topik" di window top_k).
        # .get(..., True) -- default True supaya get_all_session_chunks() ("ringkas
        # semua", tidak diranking/tidak ditandai is_top_match) tetap kutip semuanya,
        # sesuai maksud awal permintaan "ringkas SEMUA dokumen ini".
        if not chunk.get("is_top_match", True):
            continue

        source_type = chunk.get("source_type", "chat_document")
        if source_type == "faq":
            key = "faq"
            filename = None
            label = "FAQ Helpdesk"
        else:
            filename = chunk.get("filename") or "Dokumen tanpa nama"
            # source_type ikut jadi bagian key -- filename yang sama secara
            # kebetulan muncul di kb_divisi DAN chat_document (jarang, tapi
            # mungkin) tetap dianggap 2 sumber berbeda, bukan digabung.
            key = f"{source_type}:{filename}"
            label = filename

        if key not in labels:
            order.append(key)
            labels[key] = label
            filenames[key] = filename
            source_types[key] = source_type
            pages[key] = set()

        page = chunk.get("page")
        if page is not None:
            pages[key].add(page)

    citations = []
    for key in order:
        sorted_pages = sorted(pages[key])
        label = labels[key]
        if sorted_pages:
            label = f"{label} (hal. {', '.join(str(p) for p in sorted_pages)})"
        citations.append(SourceCitation(
            label=label, filename=filenames[key], source_type=source_types[key], pages=sorted_pages,
        ))
    return citations


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

    # ---------- SRS FCR-003 Rules poin 2: force-stop LLM Commercial ----------
    # Dicek SEKALI di awal, dipakai untuk paksa SEMUA pemanggilan LLM di
    # endpoint ini (rephrase query, jawaban utama, auto-generate judul chat)
    # ke on-prem — bukan cuma jawaban utamanya saja. "Disable SELURUH
    # penggunaan LLM Commercial" di teks SRS ditafsirkan literal: termasuk
    # pemanggilan internal (auto-title) yang user bahkan tidak sadar terjadi.
    system_settings = db.query(SystemSettings).filter(SystemSettings.id == "global").first()
    commercial_llm_disabled = bool(system_settings and system_settings.commercial_llm_force_stopped)
    effective_provider = "on-prem" if commercial_llm_disabled else payload.llm_provider

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

    # ---------- SRS hal. 17, poin 9.a: Intent classification ----------
    # LAPIS 1 (regex, gratis) dicek PALING AWAL, sebelum analyze_query()
    # (LLM) maupun retrieve_context() (ensemble 4-leg) — buat sapaan/
    # basa-basi murni ("halo", "makasih"), KEDUANYA di-skip total.
    intent = classify_intent(payload.content)
    if intent in SKIP_RETRIEVAL_INTENTS:
        search_query = payload.content
        context_chunks, retrieval_confidence = [], None
        session_has_document = False
    else:
        # LAPIS 2 (LLM, nebeng ke pemanggilan yang sudah wajib ada buat
        # rephrase query — lihat llm/router.py: analyze_query()) TIMPA nilai
        # `intent` dari placeholder QUESTION lapis 1 jadi kategori yang
        # lebih kaya (document_query/faq_lookup/summary_request/dst).
        from app.llm.router import analyze_query
        analysis = await analyze_query(payload.content, chat_history, effective_provider)
        search_query = analysis["standalone_query"]
        intent = analysis["intent"]

        # OR keyword sengaja DIPERTAHANKAN sebagai jaring pengaman —
        # kalau LLM tidak menangkap "summary_request" (mis. keluaran JSON
        # gagal di-parse, fallback ke QUESTION), kata kunci eksplisit ini
        # tetap menangkapnya. Deteksi ganda, bukan saling menggantikan.
        query_lower = search_query.lower()
        is_summary = (
            intent == Intent.SUMMARY_REQUEST
            or "summarize" in query_lower or "summary" in query_lower or "ringkas" in query_lower
        )

        if is_summary:
            from app.rag.vectorstore import get_all_session_chunks, has_session_document
            context_chunks = get_all_session_chunks(chat_id=chat.id, limit=15)
            session_has_document = has_session_document(chat_id=chat.id)
            # Permintaan "ringkas semua" ambil SELURUH chunk apa adanya, bukan
            # hasil pencarian semantik top-k — konsep "seberapa relevan hasil
            # pencarian" tidak berlaku di sini, jadi tidak ada confidence yang
            # bisa dihitung secara jujur untuk kasus ini.
            retrieval_confidence = None
        else:
            from app.rag.vectorstore import has_session_document
            context_chunks, retrieval_confidence = retrieve_context(
                search_query, chat_id=chat.id, collection_name="kb_general", top_k=10, user_divisi=user.divisi,
                weight_hint=intent,
            )
            session_has_document = has_session_document(chat_id=chat.id)

    try:
        result = await route_and_generate(
            payload.content, context_chunks, chat_history, effective_provider,
            pii_entities=user_pii_entities,
            session_has_document=session_has_document,
            retrieval_confidence=retrieval_confidence,
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

    # ---------- FCR-003 poin 7: sistem MENAWARKAN eskalasi ke human helpdesk ----------
    # SRS literal: "sistem menawarkan eskalasi" (bukan langsung membuat tiket
    # tanpa izin). Confidence None (percakapan umum tanpa RAG) sengaja TIDAK
    # memicu ini — itu bukan "jawaban tidak meyakinkan", memang tidak relevan
    # diberi skor (lihat router.py: confidence dipaksa None kalau
    # context_chunks kosong). Tiket BARU dibuat kalau user klik konfirmasi
    # di frontend -> POST /api/helpdesk/tickets (lihat helpdesk/routes.py).
    escalation_offered = (
        result.confidence_score is not None
        and result.confidence_score < settings.escalation_confidence_threshold
    )

    new_title = None
    # commercial_llm_disabled dicek di sini juga — auto-generate judul chat
    # SELALU pakai call_commercial_llm() langsung (tidak lewat route_and_generate,
    # jadi tidak otomatis ke-cover oleh effective_provider di atas), jadi
    # perlu di-skip manual kalau force-stop aktif.
    if chat.title == "Percakapan Baru" and not commercial_llm_disabled:
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
        sources=_build_source_citations(context_chunks),
        new_title=new_title,
        message_id=ai_msg.id,
        escalation_offered=escalation_offered,
        intent=intent,
    )

@router.get("/{chat_id}/export-pdf")
def export_pdf(chat_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    [B] Ekspor riwayat percakapan menjadi PDF.

    Spesifikasi Tingkat 2 (F2-08): "Ekspor percakapan ke PDF, dibatasi hanya
    untuk role tertentu (mis. admin, compliance)." Daftar role yang
    diizinkan dikonfigurasi RUNTIME oleh IT Admin (SystemSettings.
    export_allowed_roles, lihat admin/routes.py) — bukan daftar tetap di
    kode, supaya bisa disesuaikan tanpa deploy ulang.
    """
    system_settings = db.query(SystemSettings).filter(SystemSettings.id == "global").first()
    allowed_roles = system_settings.get_export_allowed_roles() if system_settings else [Role.IT_ADMIN, Role.COMPLIANCE]
    if user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Role Anda tidak diizinkan mengekspor percakapan ke PDF")

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