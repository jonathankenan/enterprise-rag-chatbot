"""
[PENANGGUNG JAWAB: Anggota A]
INI FUNGSI UTAMA F1-05: LLM Switching (On-Prem vs Commercial).

Logika:
1. Kalau prompt terindikasi sensitif (kata kunci ATAU PII, F2-04) -> PAKSA on-prem,
   apa pun pilihan user (ini prioritas keamanan, tidak bisa dilewati user).
2. Kalau tidak sensitif -> ikuti pilihan user.
"""
import re
from dataclasses import dataclass

from app.config import settings
from app.llm.local_llm import call_local_llm
from app.llm.commercial_llm import call_commercial_llm
from app.guardrail.pii_detector import contains_pii

COMMERCIAL_PROVIDERS = {"groq", "gemini", "mistral", "cloudflare"}


@dataclass
class LLMResult:
    reply: str
    llm_used: str
    is_sensitive: bool
    confidence_score: int | None = None


def detect_sensitive(text: str) -> bool:
    """
    Prompt dianggap sensitif kalau salah satu dari dua kondisi terpenuhi:
    1. Mengandung kata kunci sensitif (misal "rahasia", "internal")
    2. Mengandung PII (NIK, NPWP, kartu kredit, dll) — F2-04
    """
    lowered = text.lower()
    has_keyword = any(keyword in lowered for keyword in settings.sensitive_keyword_list)
    has_pii = contains_pii(text)
    return has_keyword or has_pii


def build_prompt(user_message: str, context_chunks: list[str], chat_history: list = None) -> str:
    history_text = ""
    if chat_history:
        history_text = "CONVERSATION HISTORY:\n"
        for msg in chat_history:
            sender = "User" if msg.sender.value == "user" else "Assistant"
            history_text += f"{sender}: {msg.content}\n"
        history_text += "\n"

    if not context_chunks:
        # General Conversation Prompt (No Documents)
        return (
            "You are a helpful and conversational AI assistant.\n"
            "You will be provided with a CONVERSATION HISTORY.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Answer the user's questions clearly and concisely using your general knowledge.\n"
            "2. You MUST respond in the exact same language that the user used in their latest message.\n"
            "3. NEVER parrot or simply repeat what the user said. You must actually respond to it.\n\n"
            f"{history_text}"
            f"USER LATEST MESSAGE: {user_message}\n\n"
            "YOUR RESPONSE:"
        )

    # RAG Prompt (Documents Present)
    raw_context = "\n\n".join(f"- {c}" for c in context_chunks)
    if len(raw_context) > 15000:
        raw_context = raw_context[:15000] + "\n...[CONTEXT TRUNCATED]"
    context_text = "PROVIDED CONTEXT:\n" + raw_context + "\n\n"

    return (
        "You are a helpful and conversational AI assistant.\n"
        "You will be provided with a CONVERSATION HISTORY and some PROVIDED CONTEXT.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. If the provided context contains the answer, use it to answer the question.\n"
        "2. Answer naturally using the provided context. If you cannot answer based on the context, politely state 'I don't have enough information to answer that.' Do NOT mention terms like 'document', 'context', or 'system prompt' to the user.\n"
        "3. You MUST respond in the exact same language that the user used in their latest message.\n"
        "4. NEVER parrot or simply repeat what the user said. You must actually respond to it.\n"
        "5. IMPORTANT: You must self-evaluate your confidence in the answer. Your confidence score MUST reflect ONLY how helpful the provided context was. If you had to state that you don't have enough information, your confidence score MUST be very low (e.g., 0-10). Append your confidence score at the very end of your response EXACTLY in this format: [CONFIDENCE: 85]. Do not add any extra text inside or around the brackets.\n\n"
        f"{history_text}"
        f"{context_text}"
        f"USER LATEST MESSAGE: {user_message}\n\n"
        "YOUR RESPONSE:"
    )


def _extract_confidence(reply: str) -> tuple[str, int | None]:
    confidence_score = None
    match = re.search(r"\[CONFIDENCE:\s*(\d+)\]", reply, re.IGNORECASE)
    if match:
        confidence_score = int(match.group(1))
        reply = re.sub(r"\[CONFIDENCE:\s*\d+\]", "", reply, flags=re.IGNORECASE).strip()
    return reply, confidence_score


async def route_and_generate(
    user_message: str,
    context_chunks: list[str],
    chat_history: list = None,
    preferred_provider: str = "on-prem",
) -> LLMResult:
    """
    Fungsi utama yang dipanggil oleh endpoint chat.
    preferred_provider: "on-prem" | "groq" | "gemini" | "mistral" | "cloudflare"
    """
    is_sensitive = detect_sensitive(user_message)
    final_prompt = build_prompt(user_message, context_chunks, chat_history)

    if is_sensitive:
        reply = await call_local_llm(final_prompt)
        reply, confidence_score = _extract_confidence(reply)
        if not context_chunks:
            confidence_score = None
        return LLMResult(
            reply=reply, llm_used="on-prem (data sensitif)", is_sensitive=True,
            confidence_score=confidence_score,
        )

    if preferred_provider == "on-prem":
        reply = await call_local_llm(final_prompt)
        reply, confidence_score = _extract_confidence(reply)
        if not context_chunks:
            confidence_score = None
        return LLMResult(
            reply=reply, llm_used="on-prem", is_sensitive=False,
            confidence_score=confidence_score,
        )

    if preferred_provider in COMMERCIAL_PROVIDERS:
        reply = await call_commercial_llm(final_prompt, provider=preferred_provider)
        reply, confidence_score = _extract_confidence(reply)
        if not context_chunks:
            confidence_score = None
        return LLMResult(
            reply=reply, llm_used=f"commercial ({preferred_provider})", is_sensitive=False,
            confidence_score=confidence_score,
        )

    reply = await call_local_llm(final_prompt)
    reply, confidence_score = _extract_confidence(reply)
    if not context_chunks:
        confidence_score = None
    return LLMResult(
        reply=reply, llm_used="on-prem (fallback)", is_sensitive=False,
        confidence_score=confidence_score,
    )


async def get_standalone_query(user_message: str, chat_history: list, preferred_provider: str = "on-prem") -> str:
    """
    Condense chat history and latest user message into a standalone search query.
    Strips conversational filler for better vector retrieval.
    """
    history_text = ""
    for msg in chat_history:
        sender = "User" if msg.sender.value == "user" else "Assistant"
        history_text += f"{sender}: {msg.content}\n"

    prompt = f"""
Given the following conversation and a follow-up question, rephrase the follow-up question to be a standalone search query. 
Strip conversational filler like 'here it is', 'thanks', or 'can you tell me now'.
Respond ONLY with the standalone query, nothing else.

Chat History:
{history_text}

Follow-up Input: {user_message}
Standalone Query:"""

    if preferred_provider in COMMERCIAL_PROVIDERS:
        try:
            query = await call_commercial_llm(prompt, provider=preferred_provider)
            return query.strip()
        except Exception:
            pass
            
    try:
        query = await call_local_llm(prompt)
        return query.strip()
    except Exception:
        pass
        
    return user_message