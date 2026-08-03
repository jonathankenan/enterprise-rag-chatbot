"""
[PENANGGUNG JAWAB: Anggota A]
Konektor ke LLM "commercial" — API pihak ketiga (Gemini atau Groq).
Dipakai untuk data yang TIDAK sensitif (lihat logika switching di router.py).
"""
import httpx

from app.config import settings


async def _call_gemini(prompt: str) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash:generateContent"
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            params={"key": settings.gemini_api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
        )
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()


async def _call_groq(prompt: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


async def call_commercial_llm(prompt: str) -> str:
    """Router internal — pilih penyedia commercial sesuai konfigurasi .env"""
    if settings.commercial_provider == "groq":
        return await _call_groq(prompt)
    return await _call_gemini(prompt)  # default
