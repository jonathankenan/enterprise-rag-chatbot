"""
[PENANGGUNG JAWAB: Anggota A]
Konektor ke berbagai LLM "commercial" (API pihak ketiga).
Dipakai untuk data yang TIDAK sensitif (lihat logika switching di router.py).

Provider yang didukung: groq, gemini, mistral, cloudflare
"""
import httpx

from app.config import settings


class CommercialLLMError(Exception):
    """Dilempar kalau pemanggilan LLM commercial gagal, dengan pesan yang jelas untuk ditampilkan ke user."""
    pass


# ============================================================
# GEMINI (format khusus Google, bukan OpenAI-compatible)
# ============================================================

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
        raise CommercialLLMError(
            data.get("error", {}).get("message", "Gagal mengecek daftar model Gemini")
        )

    models = [
        m for m in data.get("models", [])
        if capability in m.get("supportedGenerationMethods", [])
    ]
    if not models:
        raise CommercialLLMError(f"Tidak ada model Gemini yang mendukung '{capability}' untuk API key ini")

    # Prioritaskan model "gemini-flash-latest" yang stabil untuk menghindari error 404
    # pada model-model eksperimental atau belum dirilis.
    model = next(
        (m for m in models if "gemini-flash-latest" in m["name"]),
        None
    )
    if not model:
        # Fallback ke model gemma jika flash tidak tersedia
        model = next(
            (m for m in models if "gemma" in m["name"]),
            models[0]
        )

    _gemini_model_cache = model["name"]  # contoh: "models/gemini-flash-latest"
    return _gemini_model_cache


async def _call_gemini(prompt: str) -> str:
    try:
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

    except httpx.HTTPStatusError as e:
        raise CommercialLLMError(
            f"Gemini API menolak permintaan (kode {e.response.status_code})."
        ) from e
    except httpx.RequestError as e:
        raise CommercialLLMError(f"Gagal terhubung ke Gemini API: {e}") from e


# ============================================================
# HELPER UMUM — untuk provider yang formatnya OpenAI-compatible
# (Groq, Mistral pakai pola ini)
# ============================================================

async def _call_openai_compatible(
    provider_name: str,
    url: str,
    api_key: str,
    model: str,
    prompt: str,
    extra_headers: dict | None = None,
) -> str:
    if not api_key:
        raise CommercialLLMError(f"{provider_name}: API key belum diisi di .env")

    headers = {"Authorization": f"Bearer {api_key}"}
    if extra_headers:
        headers.update(extra_headers)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        raise CommercialLLMError(
            f"{provider_name} menolak permintaan (kode {e.response.status_code})."
        ) from e
    except httpx.RequestError as e:
        raise CommercialLLMError(f"Gagal terhubung ke {provider_name}: {e}") from e


# ============================================================
# GROQ
# ============================================================

async def _call_groq(prompt: str) -> str:
    return await _call_openai_compatible(
        provider_name="Groq",
        url="https://api.groq.com/openai/v1/chat/completions",
        api_key=settings.groq_api_key,
        model="openai/gpt-oss-120b",
        prompt=prompt,
    )


# ============================================================
# MISTRAL
# ============================================================

async def _call_mistral(prompt: str) -> str:
    return await _call_openai_compatible(
        provider_name="Mistral",
        url="https://api.mistral.ai/v1/chat/completions",
        api_key=settings.mistral_api_key,
        model="mistral-small-latest",
        prompt=prompt,
    )


# ============================================================
# CLOUDFLARE WORKERS AI (format berbeda — bukan OpenAI-compatible)
# ============================================================

async def _call_cloudflare(prompt: str) -> str:
    if not settings.cloudflare_api_token or not settings.cloudflare_account_id:
        raise CommercialLLMError("Cloudflare: API token atau Account ID belum diisi di .env")

    model = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    url = f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/ai/run/{model}"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.cloudflare_api_token}"},
                json={"messages": [{"role": "user", "content": prompt}]},
            )
            response.raise_for_status()
            data = response.json()
            if not data.get("success"):
                raise CommercialLLMError(f"Cloudflare menolak permintaan: {data.get('errors')}")
            return data["result"]["response"].strip()
    except httpx.HTTPStatusError as e:
        raise CommercialLLMError(f"Cloudflare menolak permintaan (kode {e.response.status_code}).") from e
    except httpx.RequestError as e:
        raise CommercialLLMError(f"Gagal terhubung ke Cloudflare: {e}") from e


# ============================================================
# ROUTER UTAMA
# ============================================================

_PROVIDER_MAP = {
    "gemini": _call_gemini,
    "groq": _call_groq,
    "mistral": _call_mistral,
    "cloudflare": _call_cloudflare,
}


async def call_commercial_llm(prompt: str, provider: str | None = None) -> str:
    """
    Router internal untuk LLM commercial.
    provider: salah satu dari _PROVIDER_MAP, atau None -> pakai default dari .env
    """
    chosen = provider or settings.commercial_provider
    handler = _PROVIDER_MAP.get(chosen)
    if not handler:
        raise CommercialLLMError(f"Provider '{chosen}' tidak dikenali")
    return await handler(prompt)