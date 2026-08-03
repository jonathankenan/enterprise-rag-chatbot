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


@dataclass
class LLMResult:
    reply: str
    llm_used: str       # "on-prem" | "commercial"
    is_sensitive: bool


def detect_sensitive(text: str) -> bool:
    """
    Deteksi sederhana: cek apakah prompt mengandung kata kunci sensitif.
    (Versi Tingkat 2 nanti diganti dengan PII detector yang lebih andal.)
    """
    lowered = text.lower()
    return any(keyword in lowered for keyword in settings.sensitive_keyword_list)


def build_prompt(user_message: str, context_chunks: list[str]) -> str:
    """Gabungkan hasil retrieval (RAG) dengan pertanyaan user jadi satu prompt."""
    if not context_chunks:
        return user_message

    context_text = "\n\n".join(f"- {c}" for c in context_chunks)
    return (
        "Gunakan konteks berikut untuk menjawab pertanyaan. "
        "Jika konteks tidak relevan, jawab berdasarkan pengetahuan umum.\n\n"
        f"KONTEKS:\n{context_text}\n\n"
        f"PERTANYAAN: {user_message}\n\n"
        "JAWABAN:"
    )


async def route_and_generate(user_message: str, context_chunks: list[str]) -> LLMResult:
    """
    Fungsi utama yang dipanggil oleh endpoint chat.
    1. Deteksi apakah prompt sensitif
    2. Susun prompt akhir (gabung dengan hasil RAG)
    3. Pilih LLM yang sesuai dan panggil
    """
    is_sensitive = detect_sensitive(user_message)
    final_prompt = build_prompt(user_message, context_chunks)

    if is_sensitive:
        reply = await call_local_llm(final_prompt)
        llm_used = "on-prem"
    else:
        reply = await call_commercial_llm(final_prompt)
        llm_used = "commercial"

    return LLMResult(reply=reply, llm_used=llm_used, is_sensitive=is_sensitive)
