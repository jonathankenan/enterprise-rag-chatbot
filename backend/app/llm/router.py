"""
[PENANGGUNG JAWAB: Anggota A]
INI FUNGSI UTAMA F1-05: LLM Switching (On-Prem vs Commercial).

Logika:
1. Kalau prompt terindikasi sensitif -> PAKSA on-prem, apa pun pilihan user
   (ini prioritas keamanan, tidak bisa dilewati user).
2. Kalau tidak sensitif -> ikuti pilihan user.
"""
from dataclasses import dataclass

from app.config import settings
from app.llm.local_llm import call_local_llm
from app.llm.commercial_llm import call_commercial_llm

# Provider commercial yang valid dipilih user (di luar "on-prem")
COMMERCIAL_PROVIDERS = {"groq", "gemini", "mistral", "cloudflare"}


@dataclass
class LLMResult:
    reply: str
    llm_used: str
    is_sensitive: bool


def detect_sensitive(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in settings.sensitive_keyword_list)


def build_prompt(user_message: str, context_chunks: list[str], chat_history: list = None) -> str:
    history_text = ""
    if chat_history:
        history_text = "CONVERSATION HISTORY:\n"
        for msg in chat_history:
            sender = "User" if msg.sender.value == "user" else "Assistant"
            history_text += f"{sender}: {msg.content}\n"
        history_text += "\n"

    context_text = ""
    if context_chunks:
        raw_context = "\n\n".join(f"- {c}" for c in context_chunks)
        if len(raw_context) > 15000:
            raw_context = raw_context[:15000] + "\n...[CONTEXT TRUNCATED]"
        context_text = "PROVIDED CONTEXT:\n" + raw_context + "\n\n"

    return (
        "You are a helpful and conversational AI assistant.\n"
        "You will be provided with a CONVERSATION HISTORY and some PROVIDED CONTEXT.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. If the PROVIDED CONTEXT is NOT directly relevant to the user's latest message, you MUST completely ignore it.\n"
        "2. Do NOT mention the context, do NOT offer to help with topics from the context, and do NOT apologize for the context being irrelevant. Just act like the context doesn't exist and answer naturally.\n"
        "3. You MUST respond in the exact same language that the user used in their latest message.\n"
        "4. NEVER parrot or simply repeat what the user said. You must actually respond to it. If the user makes a statement, acknowledge it conversationally.\n"
        "5. When answering based on the PROVIDED CONTEXT, be eloquent, professional, and thorough. Use complete sentences instead of short fragments. For example, instead of '99.5% uptime', say 'According to the provided document, the required system uptime is 99.5%.'\n\n"
        f"{history_text}"
        f"{context_text}"
        f"USER LATEST MESSAGE: {user_message}\n\n"
        "YOUR RESPONSE:"
    )


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

    # ATURAN KEAMANAN: data sensitif WAJIB on-prem, tidak peduli pilihan user
    if is_sensitive:
        reply = await call_local_llm(final_prompt)
        return LLMResult(reply=reply, llm_used="on-prem (data sensitif)", is_sensitive=True)

    if preferred_provider == "on-prem":
        reply = await call_local_llm(final_prompt)
        return LLMResult(reply=reply, llm_used="on-prem", is_sensitive=False)

    if preferred_provider in COMMERCIAL_PROVIDERS:
        reply = await call_commercial_llm(final_prompt, provider=preferred_provider)
        return LLMResult(reply=reply, llm_used=f"commercial ({preferred_provider})", is_sensitive=False)

    # Nilai tidak dikenali -> fallback aman ke on-prem
    reply = await call_local_llm(final_prompt)
    return LLMResult(reply=reply, llm_used="on-prem (fallback)", is_sensitive=False)