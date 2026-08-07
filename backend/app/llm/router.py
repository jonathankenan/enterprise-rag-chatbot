"""
[PENANGGUNG JAWAB: Anggota A & B]
F1-05 (LLM Switching) + F2-04 (Guardrail Before/After LLM).

Alur guardrail lengkap:
1. BEFORE LLM:
   a. Deteksi PII pada prompt user SEKALI SAJA -> hasilnya dipakai untuk
      keputusan sensitif DAN untuk masking (tidak dihitung ulang)
   b. MASK PII sebelum dikirim ke LLM mana pun
   c. PII atau kata kunci sensitif -> paksa on-prem
2. GENERATE: kirim prompt (sudah di-mask kalau ada PII) ke LLM sesuai pilihan
3. AFTER LLM:
   a. Cek kategori terlarang (saran hukum/medis/dst) -> ganti pesan penolakan
   b. DEMASK jawaban -> kembalikan placeholder PII ke data asli untuk user
"""
import re
from dataclasses import dataclass, field

from app.config import settings
from app.llm.local_llm import call_local_llm
from app.llm.commercial_llm import call_commercial_llm
from app.guardrail.pii_detector import detect_pii_entities, mask_pii, demask
from app.guardrail.output_filter import check_output_restricted, get_refusal_message

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
    """
    Prompt dianggap sensitif kalau salah satu dari dua kondisi terpenuhi:
    1. Mengandung kata kunci sensitif (misal "rahasia", "internal")
    2. Mengandung PII (NIK, NPWP, kartu kredit, dll)

    pii_entities diterima sebagai PARAMETER (hasil dari detect_pii_entities()
    yang sudah dihitung di route_and_generate), BUKAN dihitung ulang di sini,
    supaya Presidio tidak dijalankan dua kali untuk teks yang sama.
    """
    lowered = text.lower()
    has_keyword = any(keyword in lowered for keyword in settings.sensitive_keyword_list)
    has_pii = len(pii_entities) > 0
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
        "1. If the context information provided below contains the answer, use it to answer the question.\n"
        "2. If the context is irrelevant or missing, you MUST still answer the user's question using your own internal knowledge as a general AI.\n"
        "3. NEVER mention the words 'context', 'provided context', 'document', or explain how you got the answer. Just give the answer naturally.\n"
        "4. You MUST respond in the exact same language that the user used in their latest message.\n"
        "5. NEVER parrot or simply repeat what the user said. You must actually respond to it.\n"
        "6. IMPORTANT: You must self-evaluate your confidence in the answer. Your confidence score MUST reflect ONLY how helpful the provided context was. If you had to use your internal knowledge because the context was useless, your confidence score MUST be very low (e.g., 0-10). Append your confidence score at the very end of your response EXACTLY in this format: [CONFIDENCE: 85]. Do not add any extra text inside or around the brackets.\n"
        "7. The user's message may contain placeholders like [ID_NIK_1], [EMAIL_ADDRESS_1], or [PERSON_1]. These represent real personal data that has been hidden for privacy reasons. Treat each placeholder as if it were the actual data it represents, and respond naturally and specifically about it (e.g. confirm you've noted it, or answer questions about it). If you need to refer to that data in your response, use the EXACT placeholder tag (e.g. [ID_NIK_1]) verbatim — do not invent a fake value, do not describe it generically, and do not ignore it.\n\n"
        f"{history_text}"
        f"{context_text}"
        f"USER LATEST MESSAGE: {user_message}\n\n"
        "YOUR RESPONSE:"
    )


def _extract_confidence(reply: str) -> tuple[str, int | None]:
    """
    Cari tag [CONFIDENCE: X] di akhir teks, ambil angkanya,
    lalu hapus tag itu dari teks yang ditampilkan ke user.
    Kalau model tidak mengikuti instruksi (tidak ada tag), confidence_score jadi None.
    """
    confidence_score = None
    match = re.search(r"\[CONFIDENCE:\s*(\d+)\]", reply, re.IGNORECASE)
    if match:
        confidence_score = int(match.group(1))
        reply = re.sub(r"\[CONFIDENCE:\s*\d+\]", "", reply, flags=re.IGNORECASE).strip()
    return reply, confidence_score


async def get_standalone_query(user_message: str, chat_history: list, preferred_provider: str = "on-prem") -> str:
    """
    [DARI TEMAN ANDA] Kondensasikan riwayat chat + pertanyaan terbaru jadi satu
    query pencarian mandiri. Membuang basa-basi percakapan (mis. "makasih",
    "terus gimana") supaya hasil pencarian vector database lebih akurat.
    """
    if not chat_history:
        return user_message

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
    # ---------- Deteksi PII SEKALI SAJA — hasilnya dipakai berulang di bawah ----------
    pii_entities = detect_pii_entities(user_message)
    pii_detected = len(pii_entities) > 0

    is_sensitive = detect_sensitive(user_message, pii_entities)

    # ---------- BEFORE LLM: mask PII sebelum masuk ke prompt (pakai entities yang sudah ada) ----------
    masked_message, pii_mapping = mask_pii(user_message, entities=pii_entities) if pii_detected else (user_message, {})
    final_prompt = build_prompt(masked_message, context_chunks, chat_history)

    # ---------- Pilih & panggil LLM ----------
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

    # ---------- AFTER LLM: cek kategori terlarang ----------
    blocked_category = check_output_restricted(reply)
    if blocked_category:
        reply = get_refusal_message(blocked_category)
        confidence_score = None
    else:
        reply, confidence_score = _extract_confidence(reply)

        # [DARI TEMAN ANDA] Kalau tidak ada context sama sekali (mis. belum ada
        # dokumen di-upload / retrieval kosong), confidence score tidak relevan
        # untuk ditampilkan -> paksa None supaya badge "Yakin: X%" tidak muncul
        # secara membingungkan pada percakapan santai/umum.
        if not context_chunks:
            confidence_score = None

        # ---------- AFTER LLM: demask PII kembali ke data asli ----------
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
