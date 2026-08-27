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


def build_prompt(user_message: str, context_chunks: list[dict], chat_history: list = None, session_has_document: bool = False) -> str:
    # Aturan bahasa ditaruh PALING AKHIR (dekat "YOUR RESPONSE:") -- model kecil paling condong ke token terdekat, dulu kalah suara saat masih di urutan #4.
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
    """Fungsi utama endpoint chat — mask PII, pilih LLM (on-prem kalau sensitif), cek output terlarang, demask."""
    if pii_entities is None:
        pii_entities = detect_pii_entities(user_message)
    pii_detected = len(pii_entities) > 0

    is_sensitive = detect_sensitive(user_message, pii_entities)

    masked_message, pii_mapping = mask_pii(user_message, entities=pii_entities) if pii_detected else (user_message, {})
    final_prompt = build_prompt(masked_message, context_chunks, chat_history, session_has_document=session_has_document)

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
