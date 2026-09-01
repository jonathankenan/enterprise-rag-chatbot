"""LLM Switching (F1-05) + Guardrail Before/After LLM (F2-04): mask PII -> pilih & panggil LLM -> cek output -> demask."""
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
    """Sensitif kalau ada kata kunci sensitif ATAU PII — pii_entities diterima sebagai parameter, tidak dihitung ulang."""
    lowered = text.lower()
    has_keyword = any(keyword in lowered for keyword in settings.sensitive_keyword_list)
    has_pii = len(pii_entities) > 0
    return has_keyword or has_pii


def build_prompt(user_message: str, context_chunks: list[dict], chat_history: list = None, session_has_document: bool = False, identifier_in_example: list[str] | None = None, answer_must_be_grounded: bool = False) -> str:
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
        "USER LATEST MESSAGE.\n"
        # 2026-08-26: model on-prem menerjemahkan "retrieval accuracy" jadi
        # "ketepatan/akurasi PENYIMPANAN" -- penyimpanan itu storage, artinya
        # terbalik dari retrieval. Fatal justru karena retrieval adalah inti
        # sistem ini; kalau muncul saat demo, orang yang paham RAG langsung
        # menangkapnya. Istilah teknis dibiarkan dalam bahasa Inggris saja
        # daripada mengandalkan model kecil menerjemahkannya dengan benar.
        "TECHNICAL TERMS: do NOT translate established technical terms — keep "
        "them in English (retrieval, embedding, chunk, latency, throughput, "
        "uptime, encryption, endpoint, token, prompt, fine-tuning, guardrail). "
        "Translating them produces wrong meanings; 'retrieval' in particular is "
        "NOT 'penyimpanan' (that is storage). Requirement IDs, metric names and "
        # JANGAN pakai "Must Have" sebagai contoh di sini. Pernah dipakai, dan
        # blok ini duduk PERSIS sebelum "YOUR RESPONSE:" -- jadi kata terakhir
        # yang dibaca model sebelum menjawab adalah nilai priority yang justru
        # sedang dilarang dikarang oleh GROUNDING_RULE di atasnya.
        "units stay verbatim too (FR-01, NFR-PERF-01, MRR@5, TTFT, 92%, 600 ms).\n\n"
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
    if len(raw_context) > 15000:
        raw_context = raw_context[:15000] + "\n...[CONTEXT TRUNCATED]"
    context_text = "PROVIDED CONTEXT:\n" + raw_context + "\n\n"

    # ── 2026-08-26: GROUNDING_RULE, sengaja di AKHIR seperti LANGUAGE_RULE ───
    # NFR-PERF-01/02 dijawab "Prioritasnya Wajib Memiliki (Must Have)",
    # padahal tabel NFR (hal. 8) TIDAK punya kolom Priority sama sekali --
    # kolomnya cuma Metric Identifier / Performance Indicator / Target
    # Threshold / Max Allowable Limit. Angkanya benar, field-nya dikarang.
    #
    # Dua sumbernya:
    #   * KONTEKS: context_chunks sengaja tetap penuh sampai top_k (cuma
    #     citation yang dipersempit -- lihat retrieve_context()), jadi chunk
    #     tabel FR hal. 7 yang MEMUAT "Must/Should/Could Have" ikut terkirim,
    #     bahkan di peringkat 0, saat user bertanya soal NFR. Mempersempit
    #     konteks DITOLAK: itu justru yang dibutuhkan kasus sintesis FR-12.
    #   * RIWAYAT: FR-01 dan FR-02 ditanya lebih dulu di chat yang sama, kedua
    #     jawaban berakhir "Prioritasnya adalah ...", model meneruskan pola
    #     jawabannya sendiri.
    #
    # Percobaan pertama menaruh ini sebagai "instruksi 6" di dalam CRITICAL
    # INSTRUCTIONS -- TIDAK BERHASIL, model on-prem tetap mengarang priority.
    # Sama persis dengan bug bahasa di commit 2013249: aturan yang terkubur di
    # tengah prompt kalah oleh pola di konteks dan di riwayat. Yang berhasil
    # di sana adalah memindahkannya ke ujung, dekat titik generasi. Ditaruh
    # SEBELUM LANGUAGE_RULE supaya aturan bahasa tetap jadi yang paling akhir
    # (posisi itu yang sudah terbukti memperbaikinya -- jangan digeser).
    GROUNDING_RULE = (
        "IMPORTANT — DO NOT INVENT FIELDS: The context holds MANY different items "
        "(requirements, table rows, records), each with its own columns. A value "
        "belongs ONLY to the item it is written against.\n"
        "Before stating any attribute — priority, status, owner, category, target, "
        "date — check that it appears in the context ON THE SAME ROW as the item "
        "asked about. If it does not, say nothing about it.\n"
        "In particular: NEVER write \"Must Have\", \"Should Have\", \"Could Have\" or "
        "any priority unless that exact phrase sits on that item's own row. Some "
        "tables have a Priority column and others do not; a neighbouring table "
        "having one is NOT a reason to give this item one.\n"
        "Do not copy the shape of your own earlier answers in this conversation. "
        "An answer that omits a field the item does not have is CORRECT and "
        "complete — do not fill the gap to make it look consistent.\n\n"
    )

    # ── 2026-08-26: identifier yang cuma hidup di dalam contoh ──────────────
    # Dipasang hanya kalau chat/routes.py sudah MEMASTIKAN lewat kode bahwa
    # setiap kemunculan identifier itu ada di dalam cuplikan contoh (lihat
    # identifier_only_in_example() di rag/vectorstore.py). Aturan ini tidak
    # pernah aktif untuk pertanyaan biasa, jadi tidak menambah beban prompt
    # pada 99% permintaan.
    #
    # Peringatan utama untuk user tetap ditempelkan secara deterministik di
    # chat/routes.py. Aturan ini pelengkap: mengurangi kemungkinan model
    # menulis kalimat yang BERTENTANGAN dengan peringatan itu.
    EXAMPLE_RULE = ""
    if identifier_in_example:
        daftar = ", ".join(identifier_in_example)
        EXAMPLE_RULE = (
            f"IMPORTANT — {daftar} IS AN EXAMPLE, NOT A REAL RECORD: it appears in "
            "the context ONLY inside an illustrative snippet (an API sample payload, "
            "a code block, a template). No such item actually exists in this corpus.\n"
            "You may describe what the snippet shows, but you must NOT present it as "
            "a real document, requirement, or record.\n"
            "Every number inside that snippet — scores, amounts, dates, IDs — is a "
            "placeholder typed by the author to illustrate a format. NEVER describe "
            "such a number as a measurement of the user's question, of relevance, or "
            "of anything happening now.\n\n"
        )

    # ── 2026-08-31: kapan boleh menjawab dari pengetahuan umum ──────────────
    # session_has_document cuma mengecek dokumen yang diunggah ke SESI CHAT
    # ini (kb_general + chat_id). Dia buta terhadap KB divisi dan FAQ, padahal
    # keduanya sama-sama korpus perusahaan. Akibatnya untuk user yang bertanya
    # ke KB divisi tanpa pernah mengunggah apa pun ke chat-nya, instruksi yang
    # aktif adalah versi longgar -- model DIPERINTAHKAN mengisi dari
    # pengetahuan sendiri.
    #
    # Terukur: ditanya "jelaskan isi SOP-02 WAS", model mengambil satu kalimat
    # asli SOP-02 milik PTI ("akses ke Core Trading Engine perlu persetujuan
    # dua tingkat, dicabut setelah 90 hari") lalu MENGEMBANGKANNYA jadi SOP
    # lengkap karangan: formulir permintaan, tingkat 1/2 otoritas, log audit,
    # MFA, least privilege, dokumentasi. Tidak satu pun ada di dokumen. Dan
    # "WAS" ditafsirkan sendiri sebagai WebSphere Application Server.
    #
    # answer_must_be_grounded dinyalakan caller (chat/routes.py) saat
    # pertanyaannya menyebut identifier item korpus -- pertanyaan tentang
    # item yang terkatalog TIDAK PERNAH boleh dijawab dari pengetahuan umum.
    # Percakapan umum ("apa itu machine learning") tidak menyebut identifier,
    # jadi tetap lewat jalur longgar dan kemampuan Generic ChatBot (FCR-003)
    # tidak dikorbankan.
    grounded = session_has_document or answer_must_be_grounded

    instruction_2 = "2. If the context is irrelevant or missing, you MUST still answer the user's question using your own internal knowledge as a general AI.\n"
    if grounded:
        instruction_2 = "2. If the PROVIDED CONTEXT says '[NO RELEVANT CONTEXT FOUND]' or does not contain the answer, politely state that the document does not contain the information. You MUST state this refusal in the exact same language the user is speaking.\n"

    # Instruksi 2 versi ketat cuma mengatur kasus konteksnya KOSONG. Yang
    # terjadi di SOP-02 justru sebaliknya: konteksnya ADA tapi cuma satu
    # kalimat, dan model menambahi sisanya sendiri sampai terlihat seperti
    # dokumen lengkap. Jadi butuh aturan terpisah, dan ditaruh di akhir --
    # posisi yang sudah berkali-kali terbukti satu-satunya yang dipatuhi.
    NO_ELABORATION_RULE = ""
    if grounded:
        NO_ELABORATION_RULE = (
            "IMPORTANT — DO NOT ELABORATE: State ONLY what the context actually "
            "says. Do NOT add procedures, steps, roles, controls, or requirements "
            "that the context does not state, even when they are standard practice "
            "for this kind of item and even when the user asks you to 'explain' it.\n"
            "If the context gives one sentence about an item, your answer is one "
            "sentence. An answer that stops where the document stops is CORRECT and "
            "COMPLETE — length is not a measure of quality here.\n"
            "Do NOT expand an abbreviation the context never expands, and do NOT "
            "explain what an unfamiliar term 'usually' means. If the context does "
            "not define it, say it is not specified.\n\n"
        )

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
        f"{EXAMPLE_RULE}"
        f"{NO_ELABORATION_RULE}"
        f"{GROUNDING_RULE}"
        f"{LANGUAGE_RULE}"
        "YOUR RESPONSE:"
    )


async def analyze_query(user_message: str, chat_history: list, preferred_provider: str = "on-prem") -> dict:
    """1 panggilan LLM, 2 tugas: rephrase jadi search query + Intent Classification lapis 2 — tidak pernah raise, selalu fallback aman."""
    fallback = {"standalone_query": user_message, "intent": Intent.QUESTION}
    if not chat_history:
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


# ── 2026-09-01: penjagaan hasil rewrite kueri ───────────────────────────────
# qwen2.5:7b sering MENYALIN KEMBALI kalimat instruksinya alih-alih
# menjalankannya, dan hasilnya masuk ke standalone_query apa adanya:
#
#     "rephrase the follow-up question into a standalone English search query"
#     "rephrase the follow-up question into a standalone English search
#      query: sebutkan isi SOP-02"
#
# Terukur pada 3 kueri x 3 run: on-prem mengembalikan echo instruksi di 7 dari
# 9 percobaan; Groq nol dari 9. Ini BUKAN cuma jelek -- dia meracuni embedding.
# Teks instruksi mendominasi vektornya sampai chunk yang benar terdorong keluar
# top-10, lalu penjaga identifier melapor "tidak ditemukan" untuk item yang
# sebetulnya ADA:
#
#     "contents of SOP-01"                         -> 2 chunk cocok, dijawab
#     "rephrase the follow-up ...: ... SOP-01"     -> 0 chunk cocok, DITOLAK
#
# Itu persis yang terlihat di sesi 2026-09-01: SOP-01 ditolak sementara SOP-02
# dan SOP-03 terjawab, dari korpus yang sama, dalam chat yang sama. Bukan acak
# -- tergantung rewrite mana yang kebetulan bersih.
#
# Frasa di bawah milik prompt analyze_query itu sendiri. Tidak akan muncul di
# kueri pencarian yang wajar, jadi kemunculannya adalah bukti kontaminasi.
_ECHO_MARKERS = (
    "follow-up question",
    "standalone english",
    "search query",
    "conversational filler",
    "json object",
    "respond with only",
    "classify the follow-up",
)


def _is_instruction_echo(text: str) -> bool:
    lowered = text.lower()
    return any(m in lowered for m in _ECHO_MARKERS)


def _lost_identifiers(original: str, rewritten: str) -> bool:
    """
    True kalau pesan asli menyebut identifier item (SOP-02, FR-01, dst.) yang
    hilang dari hasil rewrite. Impor ditaruh di dalam fungsi supaya router
    tidak menarik rag.vectorstore (dan chromadb) saat impor modul.
    """
    from app.rag.vectorstore import extract_query_identifiers
    asli = extract_query_identifiers(original)
    return bool(asli) and not (asli & extract_query_identifiers(rewritten))


def _parse_query_analysis(raw: str, fallback: dict) -> dict:
    """Strip markdown fence kalau ada, validasi intent ke LAYER2_INTENTS, fallback aman kalau parsing gagal."""
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
        query = query or fallback["standalone_query"]

        # Kembali ke pesan asli user kalau rewrite-nya tercemar. Pesan asli
        # (biasanya bahasa Indonesia) bukan pilihan buruk: diukur 2026-08-31
        # pada korpus Indonesia, kueri Indonesia dan Inggris praktis setara
        # (6/8 vs 7/8) -- jauh lebih baik daripada teks instruksi.
        if _is_instruction_echo(query):
            query = fallback["standalone_query"]
        # Rewrite yang MEMBUANG identifier juga merugikan: saringan identifier
        # adalah tulang punggung beberapa penjaga, dan tanpa identifier di
        # search_query semuanya jadi tidak aktif tanpa gejala apa pun.
        elif _lost_identifiers(fallback["standalone_query"], query):
            query = fallback["standalone_query"]

        return {"standalone_query": query, "intent": intent}
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
    identifier_in_example: list[str] | None = None,
    answer_must_be_grounded: bool = False,
) -> LLMResult:
    """Fungsi utama endpoint chat — mask PII, pilih LLM (on-prem kalau sensitif), cek output terlarang, demask."""
    if pii_entities is None:
        pii_entities = detect_pii_entities(user_message)
    pii_detected = len(pii_entities) > 0

    is_sensitive = detect_sensitive(user_message, pii_entities)

    masked_message, pii_mapping = mask_pii(user_message, entities=pii_entities) if pii_detected else (user_message, {})
    final_prompt = build_prompt(masked_message, context_chunks, chat_history,
                               session_has_document=session_has_document,
                               identifier_in_example=identifier_in_example,
                               answer_must_be_grounded=answer_must_be_grounded)

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

    blocked_category = check_output_restricted(reply)
    if blocked_category:
        reply = get_refusal_message(blocked_category)
        confidence_score = None
    else:
        confidence_score = retrieval_confidence  # pass-through dari caller, bukan dihitung di sini
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
