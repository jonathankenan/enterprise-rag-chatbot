"""
[PENANGGUNG JAWAB: Anggota A & B]
F1-05 (LLM Switching) + F2-04 (Guardrail Before/After LLM).

Alur guardrail lengkap:
1. BEFORE LLM:
   a. Deteksi PII pada prompt user SEKALI SAJA -> hasilnya dipakai untuk
      keputusan sensitif DAN untuk masking (tidak dihitung ulang)
   b. MASK PII sebelum dikirim ke LLM mana pun
   c. PII atau kata kunci sensitif -> paksa on-prem
2. GENERATE: kirim prompt (sudah di-mask kalau ada PII) ke LLM sesuai pilihan
3. AFTER LLM:
   a. Cek kategori terlarang (saran hukum/medis/dst) -> ganti pesan penolakan
   b. DEMASK jawaban -> kembalikan placeholder PII ke data asli untuk user
"""
import json
from dataclasses import dataclass, field

from app.config import settings
from app.llm.local_llm import call_local_llm
from app.llm.commercial_llm import call_commercial_llm
from app.guardrail.pii_detector import detect_pii_entities, mask_pii, demask
from app.guardrail.output_filter import check_output_restricted, get_refusal_message
from app.guardrail.intent_classifier import Intent, LAYER2_INTENTS

COMMERCIAL_PROVIDERS = {"groq", "gemini", "mistral", "cloudflare"}


@dataclass
class LLMResult:
    reply: str
    llm_used: str
    is_sensitive: bool
    confidence_score: int | None = None
    pii_detected: bool = False
    pii_entities: list[dict] = field(default_factory=list)
    output_blocked_category: str | None = None


def detect_sensitive(text: str, pii_entities: list[dict]) -> bool:
    """
    Prompt dianggap sensitif kalau salah satu dari dua kondisi terpenuhi:
    1. Mengandung kata kunci sensitif (misal "rahasia", "internal")
    2. Mengandung PII (NIK, NPWP, kartu kredit, dll)

    pii_entities diterima sebagai PARAMETER (hasil dari detect_pii_entities()
    yang sudah dihitung di route_and_generate), BUKAN dihitung ulang di sini,
    supaya Presidio tidak dijalankan dua kali untuk teks yang sama.
    """
    lowered = text.lower()
    has_keyword = any(keyword in lowered for keyword in settings.sensitive_keyword_list)
    has_pii = len(pii_entities) > 0
    return has_keyword or has_pii


def build_prompt(user_message: str, context_chunks: list[dict], chat_history: list = None, session_has_document: bool = False) -> str:
    # 2026-08-25: the language rule used to live inside CRITICAL INSTRUCTIONS
    # (as #4 of 6), which lost consistently -- Indonesian questions came back
    # answered in English. Not a model-capability problem (on-prem is
    # qwen2.5:7b, which handles Indonesian fine) and not a missing
    # instruction: it was outvoted by position and volume. Everything after
    # it -- the whole English system prompt and a fully English PROVIDED
    # CONTEXT of up to 15k chars -- pushed the model back toward English, and
    # small models weight the tokens nearest the generation point hardest.
    #
    # So it now sits on its own, as the LAST thing before "YOUR RESPONSE:",
    # and explicitly says to ignore the language of the surrounding prompt
    # rather than just "match the user".
    _lang = settings.response_language
    LANGUAGE_RULE = (
        f"IMPORTANT — LANGUAGE: Write your ENTIRE response in {_lang}. "
        f"(Tulis SELURUH jawaban dalam {_lang}.)\n"
        "The instructions above and the PROVIDED CONTEXT are written in English "
        "for internal reasons. That is NOT a reason to answer in English, and it "
        "is NOT a reason to answer in any other language either.\n"
        f"Only if USER LATEST MESSAGE is itself clearly written in a language "
        f"other than {_lang} should you answer in that language instead. "
        f"Never answer in any language except {_lang} or the language of "
        "USER LATEST MESSAGE.\n\n"
    )

    history_text = ""
    if chat_history:
        history_text = "CONVERSATION HISTORY:\n"
        for msg in chat_history:
            sender = "User" if msg.sender.value == "user" else "Assistant"
            history_text += f"{sender}: {msg.content}\n"
        history_text += "\n"

    if not context_chunks:
        if session_has_document:
            raw_context = "[NO RELEVANT CONTEXT FOUND]"
        else:
            # General Conversation Prompt (No Documents)
            return (
                "You are a helpful and conversational AI assistant.\n"
                "You will be provided with a CONVERSATION HISTORY.\n\n"
                "CRITICAL INSTRUCTIONS:\n"
                "1. Answer the user's questions clearly and concisely using your general knowledge.\n"
                "2. NEVER parrot or simply repeat what the user said. You must actually respond to it.\n\n"
                f"{history_text}"
                f"USER LATEST MESSAGE: {user_message}\n\n"
                f"{LANGUAGE_RULE}"
                "YOUR RESPONSE:"
            )

    # RAG Prompt (Documents Present)
    if context_chunks:
        raw_context = "\n\n".join(f"- {c['text']}" for c in context_chunks)
    # else: raw_context already set to "[NO RELEVANT CONTEXT FOUND]" above
    if len(raw_context) > 15000:
        raw_context = raw_context[:15000] + "\n...[CONTEXT TRUNCATED]"
    context_text = "PROVIDED CONTEXT:\n" + raw_context + "\n\n"

    instruction_2 = "2. If the context is irrelevant or missing, you MUST still answer the user's question using your own internal knowledge as a general AI.\n"
    if session_has_document:
        instruction_2 = "2. If the PROVIDED CONTEXT says '[NO RELEVANT CONTEXT FOUND]' or does not contain the answer, politely state that the document does not contain the information. You MUST state this refusal in the exact same language the user is speaking.\n"

    return (
        "You are a helpful and conversational AI assistant.\n"
        "You will be provided with a CONVERSATION HISTORY and some PROVIDED CONTEXT.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. If the context information provided below contains the answer, use it to answer the question.\n"
        f"{instruction_2}"
        "3. NEVER mention the words 'context', 'provided context', 'document', or explain how you got the answer. Just give the answer naturally.\n"
        "4. NEVER parrot or simply repeat what the user said. You must actually respond to it.\n"
        "5. The user's message may contain placeholders like [ID_NIK_1], [EMAIL_ADDRESS_1], or [PERSON_1]. These represent real personal data that has been hidden for privacy reasons. Treat each placeholder as if it were the actual data it represents, and respond naturally and specifically about it (e.g. confirm you've noted it, or answer questions about it). If you need to refer to that data in your response, use the EXACT placeholder tag (e.g. [ID_NIK_1]) verbatim — do not invent a fake value, do not describe it generically, and do not ignore it.\n\n"
        f"{history_text}"
        f"{context_text}"
        f"USER LATEST MESSAGE: {user_message}\n\n"
        f"{LANGUAGE_RULE}"
        "YOUR RESPONSE:"
    )


async def analyze_query(user_message: str, chat_history: list, preferred_provider: str = "on-prem") -> dict:
    """
    Gabungan 2 tugas dalam SATU pemanggilan LLM (bukan 2 panggilan
    terpisah): (1) rangkai ulang jadi query pencarian mandiri — fungsi asli
    fungsi ini dari awal (dulu bernama get_standalone_query), dan (2) Intent
    Classification lapis 2 (SRS hal. 17, poin 9.a — lihat
    guardrail/intent_classifier.py untuk penjelasan lapis 1 vs lapis 2).

    Digabung SENGAJA supaya intent classification yang lebih kaya (bukan
    cuma "perlu RAG atau tidak" dari lapis 1) TIDAK menambah biaya/latency
    — pemanggilan LLM ini sudah wajib ada buat re-phrase query, kita cuma
    minta 1 field JSON tambahan dari hasil yang sama.

    Return dict SELALU punya kedua key ({"standalone_query": str, "intent":
    str}) — kalau parsing JSON gagal (LLM tidak taat format, jaringan
    timeout, dst), fallback ke user_message apa adanya + Intent.QUESTION,
    TIDAK PERNAH melempar exception ke pemanggil (chat/routes.py tidak perlu
    try/except tambahan cuma buat ini).
    """
    fallback = {"standalone_query": user_message, "intent": Intent.QUESTION}
    if not chat_history:
        # Pesan pertama di chat -- tidak ada riwayat buat di-rangkai ulang,
        # TAPI intent classification tetap perlu jalan (beda dari perilaku
        # lama yang skip total di sini) supaya bobot retrieval tetap bisa
        # disesuaikan sejak pesan pertama, bukan baru mulai di pesan ke-2.
        history_text = "(belum ada riwayat, ini pesan pertama di percakapan ini)\n"
    else:
        history_text = ""
        for msg in chat_history:
            sender = "User" if msg.sender.value == "user" else "Assistant"
            history_text += f"{sender}: {msg.content}\n"

    prompt = f"""Given the following conversation and a follow-up question, do TWO things and respond with ONLY a JSON object (no markdown, no explanation):

1. "standalone_query": rephrase the follow-up question into a standalone ENGLISH search query.
   RULES for standalone_query:
   - Strip all conversational filler ('here it is', 'thanks', 'explain', 'tell me').
   - Fix obvious spelling typos (e.g., 'documen' -> 'document', 'detial' -> 'detail').
   - Always translate to ENGLISH regardless of the input language.
   - If asking about multiple distinct entities/IDs (e.g., 'FR-04 and FR-05'), keep them together, IDs exactly as written.
   - If the follow-up is NOT a real question (e.g. it's just chitchat that slipped through), just clean it up minimally.

2. "intent": classify the follow-up question into EXACTLY ONE of these categories:
   - "document_query": asking about content of a document the user uploaded to THIS chat
   - "faq_lookup": a general/procedural question likely answerable from company FAQ or policy knowledge base
   - "summary_request": explicitly asking to summarize ALL of the uploaded document(s), not search for something specific
   - "general_chat": needs a reply but isn't really an information-seeking question (opinion, casual remark, unclear intent)
   - "question": doesn't clearly fit any category above

Chat History:
{history_text}
Follow-up Input: {user_message}

JSON:"""

    raw = None
    if preferred_provider in COMMERCIAL_PROVIDERS:
        try:
            raw = await call_commercial_llm(prompt, provider=preferred_provider)
        except Exception:
            raw = None
    if raw is None:
        try:
            raw = await call_local_llm(prompt)
        except Exception:
            return fallback

    return _parse_query_analysis(raw, fallback)


def _parse_query_analysis(raw: str, fallback: dict) -> dict:
    """
    LLM kadang membungkus JSON dengan markdown fence (```json ... ```)
    walau sudah diminta "no markdown" -- di-strip dulu sebelum di-parse.
    Validasi intent terhadap LAYER2_INTENTS (bukan dipakai mentah) supaya
    kalau LLM ngarang kategori yang tidak ada di daftar, tetap jatuh ke
    Intent.QUESTION yang aman, bukan string sembarangan yang bisa bikin
    retrieve_context() bingung soal bobot mana yang harus dipakai.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
        query = str(parsed.get("standalone_query") or fallback["standalone_query"]).strip()
        intent = parsed.get("intent")
        if intent not in LAYER2_INTENTS:
            intent = Intent.QUESTION
        return {"standalone_query": query or fallback["standalone_query"], "intent": intent}
    except (json.JSONDecodeError, AttributeError, TypeError):
        return fallback


async def route_and_generate(
    user_message: str,
    context_chunks: list[dict],
    chat_history: list = None,
    preferred_provider: str = "on-prem",
    pii_entities: list[dict] | None = None,
    session_has_document: bool = False,
    retrieval_confidence: int | None = None,
) -> LLMResult:
    """
    Fungsi utama yang dipanggil oleh endpoint chat.
    preferred_provider: "on-prem" | "groq" | "gemini" | "mistral" | "cloudflare"
    pii_entities: kalau caller (chat/routes.py) sudah menjalankan
      detect_pii_entities(user_message) sendiri (mis. untuk keperluan masking
      sebelum simpan ke histori — lihat SRS 3.j), berikan hasilnya di sini
      supaya Presidio TIDAK dijalankan ulang untuk teks yang sama. Kalau None,
      dihitung sendiri seperti sebelumnya (backward compatible).
    retrieval_confidence: skor 0-100 dari compute_retrieval_confidence()
      (vectorstore.py), dihitung caller SEBELUM route_and_generate dipanggil
      (butuh search_query & chat_id yang tidak tersedia di sini). Dulu
      confidence_score ini diminta dari LLM sendiri lewat instruksi prompt
      "[CONFIDENCE: X]" — diganti karena angka self-report LLM tidak
      grounded/tidak konsisten antar-provider (lihat diskusi saat fitur ini
      diubah). Sekarang murni pass-through: fungsi ini TIDAK menghitung
      confidence apa pun sendiri, cuma meneruskan apa yang caller berikan.
    """
    # ---------- Deteksi PII SEKALI SAJA — hasilnya dipakai berulang di bawah ----------
    if pii_entities is None:
        pii_entities = detect_pii_entities(user_message)
    pii_detected = len(pii_entities) > 0

    is_sensitive = detect_sensitive(user_message, pii_entities)

    # ---------- BEFORE LLM: mask PII sebelum masuk ke prompt (pakai entities yang sudah ada) ----------
    masked_message, pii_mapping = mask_pii(user_message, entities=pii_entities) if pii_detected else (user_message, {})
    final_prompt = build_prompt(masked_message, context_chunks, chat_history, session_has_document=session_has_document)

    # ---------- Pilih & panggil LLM ----------
    if is_sensitive:
        reply = await call_local_llm(final_prompt)
        llm_used = "on-prem (data sensitif)"
    elif preferred_provider == "on-prem":
        reply = await call_local_llm(final_prompt)
        llm_used = "on-prem"
    elif preferred_provider in COMMERCIAL_PROVIDERS:
        reply = await call_commercial_llm(final_prompt, provider=preferred_provider)
        llm_used = f"commercial ({preferred_provider})"
    else:
        reply = await call_local_llm(final_prompt)
        llm_used = "on-prem (fallback)"

    # ---------- AFTER LLM: cek kategori terlarang ----------
    blocked_category = check_output_restricted(reply)
    if blocked_category:
        reply = get_refusal_message(blocked_category)
        confidence_score = None
    else:
        # Confidence sekarang murni dari retrieval_confidence (parameter),
        # bukan diekstrak dari teks jawaban LLM lagi. Kalau tidak ada context
        # sama sekali (percakapan umum tanpa RAG), retrieval_confidence sudah
        # otomatis None dari compute_retrieval_confidence() (koleksi kosong)
        # — baris `if not context_chunks` yang dulu ada di sini jadi redundan
        # dan dihapus, bukan dihilangkan diam-diam.
        confidence_score = retrieval_confidence

        # ---------- AFTER LLM: demask PII kembali ke data asli ----------
        if pii_mapping:
            reply = demask(reply, pii_mapping)

    return LLMResult(
        reply=reply,
        llm_used=llm_used,
        is_sensitive=is_sensitive,
        confidence_score=confidence_score,
        pii_detected=pii_detected,
        pii_entities=pii_entities,
        output_blocked_category=blocked_category,
    )
