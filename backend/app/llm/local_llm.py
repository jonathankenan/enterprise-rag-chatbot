"""
[PENANGGUNG JAWAB: Anggota A]
Konektor ke LLM "on-premise" — dijalankan lokal via Ollama (gratis, jalan di komputer sendiri).
Ini mensimulasikan "Foundation Model on-prem" dari dokumen SRS aslinya.

Prasyarat: install Ollama (https://ollama.com) lalu jalankan:
    ollama pull llama3
    ollama serve
"""
import httpx

from app.config import settings


async def call_local_llm(prompt: str) -> str:
    """Kirim prompt ke Ollama yang jalan lokal, kembalikan jawaban teks."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()
