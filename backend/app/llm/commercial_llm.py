"""
[PENANGGUNG JAWAB: Anggota A]
Konektor ke LLM "commercial" — API pihak ketiga (Gemini atau Groq).
Dipakai untuk data yang TIDAK sensitif (lihat logika switching di router.py).
"""
import httpx

from app.config import settings

# Cache nama model Gemini yang valid, supaya tidak perlu query ulang /models
# setiap kali ada request chat (hemat 1 API call per prompt).
_gemini_model_cache: str | None = None


async def _find_gemini_model(client: httpx.AsyncClient, capability: str = "generateContent") -> str:
    """
    Cari model Gemini yang aktif untuk API key ini dan mendukung 'capability'
    yang diminta (mis. generateContent). Pendekatan ini lebih tahan terhadap
    perubahan nama/versi model dari Google, dibanding hardcode nama model.
    """
    global _gemini_model_cache
    if _gemini_model_cache:
        return _gemini_model_cache

    url = "https://generativelanguage.googleapis.com/v1beta/models"
    response = await client.get(url, params={"key": settings.gemini_api_key})
    data = response.json()

    if not response.is_success:
        raise RuntimeError(data.get("error", {}).get("message", "Gagal mengecek daftar model Gemini"))

    model = next(
        (
            m for m in data.get("models", [])
            if capability in m.get("supportedGenerationMethods", [])
        ),
        None,
    )
    if not model:
        raise RuntimeError(f"Tidak ada model Gemini yang mendukung '{capability}' untuk API key ini")

    _gemini_model_cache = model["name"]  # contoh: "models/gemini-2.5-flash"
    return _gemini_model_cache


async def _call_gemini(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        model_name = await _find_gemini_model(client, capability="generateContent")

        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent"
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


async def call_commercial_llm(prompt: str, provider: str | None = None) -> str:
    """
    Router internal untuk LLM commercial.
    - provider="groq" -> paksa pakai Groq
    - provider="gemini" -> paksa pakai Gemini
    - provider=None -> pakai default dari .env (settings.commercial_provider)
    """
    chosen = provider or settings.commercial_provider
    if chosen == "gemini":
        return await _call_gemini(prompt)
    return await _call_groq(prompt)