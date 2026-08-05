"""
[PENANGGUNG JAWAB: Anggota A]
INI FUNGSI UTAMA F1-05: LLM Switching (On-Prem vs Commercial).

Logika: kalau prompt terindikasi mengandung data sensitif -> paksa pakai
on-prem (Ollama, tidak pernah keluar server). Kalau tidak, boleh pakai
commercial (Gemini/Groq) yang biasanya lebih cepat/berkualitas.

Untuk Tingkat 1, deteksi sensitivitas masih sederhana (keyword matching).
Di Tingkat 2 baru diperhalus pakai PII detector (Presidio, dsb).
"""
from dataclasses import dataclass

from app.config import settings
from app.llm.local_llm import call_local_llm
from app.llm.commercial_llm import call_commercial_llm


import re

@dataclass
class LLMResult:
    reply: str
    llm_used: str       # "on-prem" | "commercial"
    is_sensitive: bool
    confidence_score: int | None = None


def detect_sensitive(text: str) -> bool:
    """
    Deteksi sederhana: cek apakah prompt mengandung kata kunci sensitif.
    (Versi Tingkat 2 nanti diganti dengan PII detector yang lebih andal.)
    """
    lowered = text.lower()
    return any(keyword in lowered for keyword in settings.sensitive_keyword_list)


def build_prompt(user_message: str, context_chunks: list[str], chat_history: list = None) -> str:
    """Gabungkan hasil retrieval (RAG) dengan pertanyaan user jadi satu prompt."""
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
        "1. If the context information provided below contains the answer, use it to answer the question.\n"
        "2. If the context is irrelevant or missing, you MUST still answer the user's question using your own internal knowledge as a general AI.\n"
        "3. NEVER mention the words 'context', 'provided context', 'document', or explain how you got the answer. Just give the answer naturally.\n"
        "4. You MUST respond in the exact same language that the user used in their latest message.\n"
        "5. NEVER parrot or simply repeat what the user said. You must actually respond to it.\n"
        "6. IMPORTANT: You must self-evaluate your confidence in the answer. Your confidence score MUST reflect ONLY how helpful the provided context was. If you had to use your internal knowledge because the context was useless, your confidence score MUST be very low (e.g., 0-10). Append your confidence score at the very end of your response EXACTLY in this format: [CONFIDENCE: 85]. Do not add any extra text inside or around the brackets.\n\n"
        f"{history_text}"
        f"{context_text}"
        f"USER LATEST MESSAGE: {user_message}\n\n"
        "YOUR RESPONSE:"
    )


async def route_and_generate(user_message: str, context_chunks: list[str], chat_history: list = None) -> LLMResult:
    """
    Fungsi utama yang dipanggil oleh endpoint chat.
    1. Deteksi apakah prompt sensitif
    2. Susun prompt akhir (gabung dengan hasil RAG)
    3. Pilih LLM yang sesuai dan panggil
    """
    is_sensitive = detect_sensitive(user_message)
    final_prompt = build_prompt(user_message, context_chunks, chat_history)

    if is_sensitive:
        reply = await call_local_llm(final_prompt)
        llm_used = "on-prem"
    else:
        reply = await call_commercial_llm(final_prompt)
        llm_used = "commercial"

    confidence_score = None
    match = re.search(r"\[CONFIDENCE:\s*(\d+)\]", reply, re.IGNORECASE)
    if match:
        confidence_score = int(match.group(1))
        reply = re.sub(r"\[CONFIDENCE:\s*\d+\]", "", reply, flags=re.IGNORECASE).strip()

    return LLMResult(reply=reply, llm_used=llm_used, is_sensitive=is_sensitive, confidence_score=confidence_score)
