"""Titik integrasi: autentikasi/guardrail/audit log/database + retrieval RAG/LLM switching (F1-05)."""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Chat, Message, SenderType, User, SystemSettings, Role, Divisi
from app.schemas import ChatCreate, ChatResponse, ChatRenameRequest, MessageCreate, MessageResponse, ChatReplyResponse, SourceCitation, CitationChunk
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
from app.llm.router import route_and_generate, LLMResult
from app.llm.commercial_llm import call_commercial_llm, CommercialLLMError
from app.chat.pdf_export import generate_pdf


router = APIRouter(prefix="/api/chat", tags=["chat"])

GUARDRAIL_REFUSAL_MESSAGE = (
    "Maaf, saya tidak dapat memproses pertanyaan tersebut karena melanggar kebijakan penggunaan. "
    "Silakan ajukan pertanyaan lain."
)


def _mask_for_storage(text: str, entities: list[dict] | None = None) -> tuple[str, str | None]:
    """Siapkan (content, pii_mapping) untuk disimpan ke Message (SRS poin 3.j) — pii_mapping None (bukan "{}") kalau tidak ada PII."""
    if entities is None:
        entities = detect_pii_entities(text)
    if not entities:
        return text, None
    masked_text, mapping = mask_pii(text, entities=entities)
    return masked_text, json.dumps(mapping, ensure_ascii=False)


def _display_content(msg: Message) -> str:
    """Isi pesan siap ditampilkan ke pemilik chat (demasked) — dipakai di endpoint riwayat, bukan respons langsung setelah kirim pesan."""
    if not msg.pii_mapping:
        return msg.content
    return demask(msg.content, json.loads(msg.pii_mapping))


@router.post("", response_model=ChatResponse)
def create_chat(payload: ChatCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Buat sesi percakapan baru."""
    chat = Chat(user_id=user.id, title=payload.title)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    log_guardrail_event(db, user.id, EventType.CHAT_CREATED, detail=f"chat_id={chat.id}, title={payload.title}")
    return chat


@router.get("/history", response_model=list[ChatResponse])
def get_chat_history(archived: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Ambil daftar percakapan milik user yang sedang login — default cuma yang aktif, archived=true buat lihat arsip (SRS poin 4)."""
    return (
        db.query(Chat)
        .filter(Chat.user_id == user.id, Chat.archived.is_(archived))
        .order_by(Chat.created_at.desc())
        .all()
    )


@router.patch("/{chat_id}/archive", response_model=ChatResponse)
def archive_chat(chat_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Arsipkan percakapan — alternatif reversibel dari hapus permanen (SRS poin 4: 'menghapus atau mengarsipkan')."""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
    chat.archived = True
    chat.archived_at = datetime.utcnow()
    db.commit()
    db.refresh(chat)
    log_guardrail_event(db, user.id, EventType.CHAT_ARCHIVED, detail=f"chat_id={chat.id}, title={chat.title}")
    return chat


@router.patch("/{chat_id}/unarchive", response_model=ChatResponse)
def unarchive_chat(chat_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Pulihkan percakapan dari arsip."""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
    chat.archived = False
    chat.archived_at = None
    db.commit()
    db.refresh(chat)
    log_guardrail_event(db, user.id, EventType.CHAT_UNARCHIVED, detail=f"chat_id={chat.id}, title={chat.title}")
    return chat


@router.get("/{chat_id}/messages", response_model=list[MessageResponse])
def get_messages(chat_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Ambil semua pesan dalam satu percakapan — demasked khusus untuk pemilik chat yang sah."""
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
    """Hapus percakapan beserta seluruh pesannya."""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    message_count = db.query(Message).filter(Message.chat_id == chat.id).count()  # log SEBELUM dihapus, satu-satunya kesempatan mencatat
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
    """Ganti judul percakapan secara manual."""
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
    """SRS poin 12.a — dedup context_chunks jadi satu entri per dokumen/FAQ unik, kumpulkan semua nomor halaman jadi label "file.pdf (hal. 2, 5)"."""
    order: list[str] = []          # key insertion order, buat urutan citation stabil
    labels: dict[str, str] = {}    # key -> "FAQ Helpdesk" atau nama file/judul
    filenames: dict[str, str | None] = {}
    display_titles: dict[str, str | None] = {}
    doc_types: dict[str, str | None] = {}
    source_types: dict[str, str] = {}
    pages: dict[str, set[int]] = {}
    chunk_texts: dict[str, list[tuple]] = {}   # key -> [(page, text)], urutan kemunculan
    chunk_seen_shapes: dict[str, set[str]] = {}  # dedup potongan yang sama dirender dua bentuk (lihat catatan _dedup_shape di vectorstore.py)

    for chunk in context_chunks:
        # cuma chunk is_top_match (3 similarity terbaik) yang layak jadi sumber -- default True supaya get_all_session_chunks() ("ringkas semua") tetap kutip semuanya
        if not chunk.get("is_top_match", True):
            continue

        source_type = chunk.get("source_type", "chat_document")
        if source_type == "faq":
            key = "faq"
            filename = None
            display_title = None
            doc_type = None
            label = "FAQ Helpdesk"
        else:
            filename = chunk.get("filename") or "Dokumen tanpa nama"
            # 2026-09-01: judul yang diisi admin saat upload dipakai sebagai
            # label kalau ada -- filename mentah (ex. "KB_PDF_PTI.pdf") cuma
            # fallback utk dokumen lama/yang tidak diisi. doc_type ikut
            # ditempel di label kalau ada, biar "Pedoman Operasional PTI
            # 2025 (SOP)" alih-alih nama file teknis.
            display_title = chunk.get("display_title")
            doc_type = chunk.get("doc_type")
            key = f"{source_type}:{filename}"  # source_type ikut key -- filename sama tapi source_type beda tetap dianggap 2 sumber
            label = display_title or filename
            if doc_type:
                label = f"{label} ({doc_type})"

        if key not in labels:
            order.append(key)
            labels[key] = label
            filenames[key] = filename
            display_titles[key] = display_title
            doc_types[key] = doc_type
            source_types[key] = source_type
            pages[key] = set()
            chunk_texts[key] = []
            chunk_seen_shapes[key] = set()

        page = chunk.get("page")
        if page is not None:
            pages[key].add(page)

        # Cuplikan isi yang benar-benar dikutip -- dasar citation yang bisa
        # "dipencet" tanpa endpoint baru: teksnya sudah lolos filter divisi
        # di retrieve_context(), tinggal dikirim apa adanya. Shape (halaman +
        # 80 karakter pertama) dipakai membuang duplikat render (lihat
        # _dedup_shape di vectorstore.py) supaya user tidak melihat "isi
        # yang sama" dua kali di panel yang sama.
        shape = f"{page}|{' '.join(chunk.get('text', '').split())[:80].lower()}"
        if shape not in chunk_seen_shapes[key]:
            chunk_seen_shapes[key].add(shape)
            chunk_texts[key].append((page, chunk.get("text", "")))

    citations = []
    for key in order:
        sorted_pages = sorted(pages[key])
        label = labels[key]
        if sorted_pages:
            label = f"{label} (hal. {', '.join(str(p) for p in sorted_pages)})"
        ordered_chunks = sorted(chunk_texts[key], key=lambda pt: (pt[0] is None, pt[0]))
        citations.append(SourceCitation(
            label=label, filename=filenames[key], display_title=display_titles[key],
            doc_type=doc_types[key], source_type=source_types[key], pages=sorted_pages,
            chunks=[CitationChunk(page=p, text=t) for p, t in ordered_chunks],
        ))
    return citations


@router.post("/message", response_model=ChatReplyResponse)
async def send_message(
    payload: MessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Endpoint utama chat — F1-03/F1-04/F1-05/F2-04: rate limit -> validasi chat -> guardrail -> simpan pesan user -> retrieval RAG -> LLM+guardrail -> simpan jawaban+audit log."""
    check_chat_rate_limit(db, user.id)  # paling murah, dicek paling awal

    chat = db.query(Chat).filter(Chat.id == payload.chat_id, Chat.user_id == user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    # SRS hal. 10 Rules poin 2: force-stop dicek sekali, paksa SEMUA pemanggilan LLM (rephrase, jawaban, auto-title) ke on-prem
    system_settings = db.query(SystemSettings).filter(SystemSettings.id == "global").first()
    commercial_llm_disabled = bool(system_settings and system_settings.commercial_llm_force_stopped)
    effective_provider = "on-prem" if commercial_llm_disabled else payload.llm_provider

    # ---------- Guardrail F1-04 & F2-04 (before LLM) ----------
    is_blocked = is_prompt_blocked(payload.content)
    is_injection = is_prompt_injection(payload.content)

    is_multi_turn = False
    if not is_blocked and not is_injection:  # cek kumulatif cuma relevan kalau pesan sekarang belum ke-flag sendirian
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

        metadata: dict = {}  # diisi bertahap, bukan reassignment -- supaya blocked & injection sekaligus tergabung, tidak saling timpa
        if is_blocked:
            metadata["category"] = get_blocked_category(payload.content)
        if is_injection or is_multi_turn:
            metadata["matched_patterns"] = get_matched_signals(payload.content)
        if is_multi_turn:
            metadata["multi_turn"] = True
            metadata["cumulative_score"] = get_cumulative_injection_score(payload.content, recent_user_texts)
        metadata = metadata or None
        log_guardrail_event(db, user.id, event_type, detail=payload.content[:200], metadata=metadata)

        blocked_content, blocked_pii_mapping = _mask_for_storage(payload.content)  # tetap masked meski diblokir sebelum sempat diproses LLM
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

    # deteksi PII sekali, dipakai untuk (1) masking sebelum simpan, (2) diteruskan ke route_and_generate biar Presidio tidak jalan ulang
    user_pii_entities = detect_pii_entities(payload.content)
    stored_user_content, user_pii_mapping = _mask_for_storage(payload.content, entities=user_pii_entities)

    user_msg = Message(chat_id=chat.id, sender=SenderType.user, content=stored_user_content, pii_mapping=user_pii_mapping)
    db.add(user_msg)
    db.commit()

    # ---------- SRS hal. 17, poin 9.a: Intent classification ----------
    # Dicek PALING AWAL, sebelum get_standalone_query() (yang butuh 1
    # pemanggilan LLM) maupun retrieve_context() (ensemble 4-leg: dokumen
    # chat + FAQ + KB divisi + BM25) — buat sapaan/basa-basi murni ("halo",
    # "makasih"), KEDUANYA di-skip total. Bukan cuma penghematan kosmetik:
    # pesan sependek "oke" tidak pernah butuh RAG sama sekali.
    # Diisi daftar identifier (mis. ["FR-14"]) kalau query menyebut identifier
    # yang TIDAK ADA di korpus — lihat penjagaan identifier di bawah.
    identifier_missing: list[str] | None = None
    # Diisi kalau identifier yang ditanya ADA di korpus, tapi setiap
    # kemunculannya cuma di dalam cuplikan contoh — lihat penjagaan di bawah.
    identifier_in_example: list[str] | None = None
    # Diisi kalau query menyebut divisi yang BUKAN divisi user (dan bukan
    # Company Wide) — lihat penjagaan divisi di bawah.
    divisi_asing: list[str] | None = None
    # True kalau pertanyaannya menyebut identifier item korpus (SOP-02,
    # FR-01, dst.). Pertanyaan tentang item yang TERKATALOG tidak pernah
    # boleh dijawab dari pengetahuan umum — lihat build_prompt().
    answer_must_be_grounded = False

    intent = classify_intent(payload.content)
    if intent in SKIP_RETRIEVAL_INTENTS:
        search_query = payload.content
        context_chunks, retrieval_confidence = [], None
        session_has_document = False
    else:
        # Lapis 2 (LLM, nebeng pemanggilan rephrase query — llm/router.py analyze_query()) timpa intent placeholder jadi kategori lebih kaya
        from app.llm.router import analyze_query
        analysis = await analyze_query(payload.content, chat_history, effective_provider)
        search_query = analysis["standalone_query"]
        intent = analysis["intent"]

        query_lower = search_query.lower()  # keyword OR dipertahankan sebagai jaring pengaman kalau LLM gagal menangkap summary_request
        is_summary = (
            intent == Intent.SUMMARY_REQUEST
            or "summarize" in query_lower or "summary" in query_lower or "ringkas" in query_lower
        )

        if is_summary:
            from app.rag.vectorstore import get_all_session_chunks, has_session_document
            context_chunks = get_all_session_chunks(chat_id=chat.id, limit=15)
            session_has_document = has_session_document(chat_id=chat.id)
            retrieval_confidence = None  # "ringkas semua" ambil seluruh chunk apa adanya, tidak ada skor relevansi yang jujur untuk dihitung
        else:
            from app.rag.vectorstore import has_session_document, extract_query_identifiers
            context_chunks, retrieval_confidence = retrieve_context(
                search_query, chat_id=chat.id, collection_name="kb_general", top_k=10, user_divisi=user.divisi,
                weight_hint=intent,
            )
            session_has_document = has_session_document(chat_id=chat.id)

            # ── 2026-08-31: penjagaan divisi asing, DETERMINISTIK ────────────
            # Filter divisi di KbDivisiRetriever sudah benar -- dokumen SDI
            # tidak pernah sampai ke prompt kalau penanya PTI. Tapi baris
            # tabel yang lolos filter tidak menyebut nama divisinya sendiri
            # ("Batas persetujuan anggaran Kepala Divisi | Rp250.000.000",
            # tanpa kata "PTI" di mana pun), dan build_prompt() cuma
            # mengirim teks chunk, tidak pernah filename/divisi.
            #
            # Akibatnya: ditanya "berapa batas anggaran divisi SDI" oleh user
            # PTI, satu-satunya angka di konteks (milik PTI, karena SDI
            # memang tidak pernah terambil) ditempelkan ke nama SDI. BUKAN
            # kebocoran data -- isi SDI yang sebenarnya tidak pernah bocor --
            # tapi pelabelan keliru yang meyakinkan dengan angka spesifik.
            #
            # Diperiksa DI SINI, sebelum penjagaan identifier: kalau divisi
            # yang ditanya memang tidak bisa diakses, tidak ada gunanya
            # memeriksa identifier di dalamnya sama sekali.
            from app.rag.vectorstore import extract_query_divisi
            divisi_disebut = extract_query_divisi(search_query, set(Divisi.ALL))
            divisi_asing = sorted(divisi_disebut - {user.divisi} if user.divisi else divisi_disebut)

            # ── 2026-08-26: penjagaan identifier, DETERMINISTIK ──────────────
            # Dua kegagalan nyata yang tidak bisa ditutup instruksi prompt,
            # sudah dicoba dua kali (instruksi 6, lalu GROUNDING_RULE di ujung
            # prompt -- lihat llm/router.py):
            #   * "jelaskan req ID FR-14" -> FR-14 TIDAK ADA di dokumen (FR
            #     berhenti di FR-12), tapi model menjawab panjang lebar tentang
            #     NFR-PERF-03. Bukan sekadar gagal menolak: dia menjawab item
            #     yang sama sekali lain.
            #   * "berapa prioritas NFR-PERF-03" -> dijawab "Must Have".
            #     Tabel NFR (hal. 8) tidak punya kolom Priority sama sekali;
            #     nilai itu disalin dari tabel FR hal. 7 yang ikut masuk
            #     konteks. Pertanyaan LANGSUNG tentang field yang tidak ada
            #     ternyata jauh lebih menggoda model daripada sekadar
            #     menyebutkannya tanpa diminta.
            #
            # Keduanya berakar pada satu hal: model tidak pernah memeriksa
            # bahwa item yang ditanya benar-benar ada di konteks. Itu
            # pemeriksaan yang bisa dilakukan kode secara pasti, jadi tidak
            # perlu dititipkan ke model 7B.
            # Identifier di dalam divisi tidak berarti apa pun kalau
            # divisinya sendiri tidak bisa diakses -- lihat penjagaan di
            # atas. Diperiksa cuma kalau divisi_asing kosong.
            if not divisi_asing:
                query_ids = extract_query_identifiers(search_query)
                if query_ids:
                    # Pertanyaan menyebut item terkatalog -> jawabannya WAJIB
                    # bersumber dari konteks. Tanpa ini instruksi prompt yang
                    # aktif justru menyuruh model mengisi dari pengetahuan
                    # umum, dan satu kalimat SOP-02 yang asli dikembangkan
                    # jadi SOP karangan lengkap. Lihat build_prompt().
                    answer_must_be_grounded = True

                    id_chunks = [c for c in context_chunks if c.get("id_match")]
                    if not id_chunks:
                        # Tidak satu pun chunk menyebut identifier ini. Bukan
                        # "retrieval-nya lemah" -- korpusnya memang tidak memuatnya.
                        identifier_missing = sorted(i.upper() for i in query_ids)
                    else:
                        # Kunci konteks ke chunk yang benar-benar membahas item
                        # yang ditanya. Tabel tetangga tidak lagi ikut terkirim,
                        # jadi tidak ada nilai field yang bisa disalin.
                        #
                        # Kasus sintesis multi-dokumen (FR-12) tidak dirugikan:
                        # pertanyaan sintesis tidak menyebut identifier tunggal
                        # ("bandingkan benefit Platinum dan Gold"), jadi query_ids
                        # kosong dan cabang ini tidak aktif sama sekali.
                        # Tabel diindeks dalam DUA bentuk (chunk_text): utuh dan
                        # per baris. Karena query ini menyebut identifier, yang
                        # dibutuhkan cuma barisnya sendiri — chunk tabel utuh
                        # membawa serta baris tetangga yang nilainya bisa disalin,
                        # dan itu justru bug yang sedang ditutup.
                        #
                        # Prosa (0 baris tabel) tetap dipertahankan: penjelasan
                        # naratif tentang item yang sama tetap berguna.
                        baris = [c for c in id_chunks if c.get("table_body_rows") == 1]
                        if baris:
                            id_chunks = baris + [
                                c for c in id_chunks if not c.get("table_body_rows")
                            ]

                        context_chunks = id_chunks

                        # ── identifier yang cuma hidup di dalam contoh ──────────
                        # Kegagalan ketiga, beda dari dua di atas. Ditanya
                        # "jelaskan DOC-FEE-2026", sistem menjawab seolah itu
                        # dokumen sungguhan, lengkap dengan "skor 0.892
                        # menunjukkan kesamaan tinggi antara kueri Anda dan
                        # dokumen ini". DOC-FEE-2026 sebenarnya cuma nama
                        # tempelan di dalam CONTOH respons API (hal. 9), dan
                        # 0.892 angka mati yang diketik penulis dokumen.
                        #
                        # Saringan id_match di atas tidak bisa menangkapnya:
                        # dia menanyakan "apakah string ini muncul", dan memang
                        # muncul. Yang kurang adalah MUNCUL SEBAGAI APA.
                        #
                        # Ini terjadi di Groq — model komersial yang jauh lebih
                        # besar dari on-prem mana pun yang kita pakai — jadi
                        # menaikkan ukuran model bukan jawabannya.
                        if all(c.get("id_in_example") for c in id_chunks):
                            identifier_in_example = sorted(i.upper() for i in query_ids)

    if divisi_asing:
        # Jawab tanpa memanggil LLM sama sekali, dan sebelum penjagaan
        # identifier — kalau divisinya sendiri tidak bisa diakses, tidak ada
        # gunanya memeriksa identifier di dalamnya. context_chunks dikosongkan
        # meski isinya (kalau ada) semuanya milik divisi user sendiri —
        # bukan itu yang ditanyakan, jadi mengutipnya cuma menyesatkan.
        context_chunks = []
        retrieval_confidence = None
        daftar = ", ".join(divisi_asing)
        milik = f"divisi {user.divisi} dan Company Wide" if user.divisi else "Company Wide"
        result = LLMResult(
            reply=(
                f"Saya hanya bisa mengakses informasi {milik}. Divisi {daftar} "
                "tidak dapat diakses dari akun ini, jadi saya tidak bisa menjawab "
                "pertanyaan itu. Hubungi admin divisi terkait atau IT admin kalau "
                "Anda memang berwenang melihatnya."
            ),
            llm_used="guardrail (divisi tidak dapat diakses)",
            is_sensitive=False,
            confidence_score=None,
            pii_detected=bool(user_pii_entities),
            pii_entities=user_pii_entities or [],
        )
    elif identifier_missing:
        # Jawab tanpa memanggil LLM sama sekali. Menyerahkan penolakan ini ke
        # model justru sudah terbukti gagal dua kali, dan tidak ada yang perlu
        # digenerasi: pertanyaannya menyebut item yang tidak ada di dokumen.
        # context_chunks dikosongkan supaya tidak ada sitasi yang menempel —
        # mengutip halaman untuk item yang tidak ada di situ justru menyesatkan.
        context_chunks = []
        retrieval_confidence = None
        daftar = ", ".join(identifier_missing)
        result = LLMResult(
            reply=(
                f"Saya tidak menemukan {daftar} di dokumen yang tersedia. "
                "Identifier itu tidak muncul di isi dokumen mana pun yang bisa saya akses, "
                "jadi saya tidak bisa menjelaskannya tanpa mengarang. "
                "Coba periksa lagi penulisannya, atau sebutkan dokumen yang memuatnya."
            ),
            llm_used="guardrail (identifier tidak ditemukan)",
            is_sensitive=False,
            confidence_score=None,
            pii_detected=bool(user_pii_entities),
            pii_entities=user_pii_entities or [],
        )
    else:
        try:
            result = await route_and_generate(
                payload.content, context_chunks, chat_history, effective_provider,
                pii_entities=user_pii_entities,
                session_has_document=session_has_document,
                retrieval_confidence=retrieval_confidence,
                identifier_in_example=identifier_in_example,
                answer_must_be_grounded=answer_must_be_grounded,
            )
        except CommercialLLMError as e:
            raise HTTPException(status_code=502, detail=str(e))

        if identifier_in_example:
            # Peringatannya ditempelkan KODE, bukan diminta lewat prompt.
            # EXAMPLE_RULE di router.py memang ikut dikirim, tapi kepatuhan
            # model terhadap aturan prompt sudah gagal berkali-kali di sesi
            # ini — sedangkan pertanyaan "apakah item ini nyata" sudah
            # dijawab pasti oleh kode. Jadi jawabannya tidak boleh bergantung
            # pada model mau menuruti atau tidak.
            daftar = ", ".join(identifier_in_example)
            result.reply = (
                f"Catatan: {daftar} bukan dokumen atau item yang benar-benar ada. "
                "Namanya cuma muncul sebagai contoh di dalam cuplikan "
                "(payload API, blok kode, atau template), jadi nilai apa pun "
                "yang menyertainya — skor, nominal, tanggal — adalah angka "
                "ilustrasi, bukan hasil pengukuran.\n\n"
            ) + result.reply

    # ---------- Audit log untuk kejadian F2-04 di dalam alur LLM ----------
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

    stored_ai_content, ai_pii_mapping = _mask_for_storage(result.reply)  # teks baru hasil generate, deteksi PII-nya dihitung sendiri di sini

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

    # SRS poin 7: sistem MENAWARKAN eskalasi (bukan auto-create tiket); confidence None (general chat) sengaja tidak pernah memicu ini
    escalation_offered = (
        result.confidence_score is not None
        and result.confidence_score < settings.escalation_confidence_threshold
    )

    new_title = None
    if chat.title == "Percakapan Baru" and not commercial_llm_disabled:  # auto-title selalu pakai call_commercial_llm() langsung, perlu di-skip manual
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
    """Ekspor riwayat percakapan ke PDF — F2-08, role yang diizinkan dikonfigurasi runtime lewat SystemSettings.export_allowed_roles (admin/routes.py)."""
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

    log_guardrail_event(db, user.id, EventType.CHAT_EXPORTED, detail=f"chat_id={chat.id}, title={chat.title}")  # jalur potensial kebocoran data, dicatat

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="chat_{chat_id}.pdf"'}
    )
