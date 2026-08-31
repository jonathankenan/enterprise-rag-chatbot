"""Intent Classification (SRS FCR-003 poin 9a) — 2 lapis: regex (gratis) lalu LLM (nebeng analyze_query, lihat llm/router.py)."""
import re


class Intent:
    # ---------- Lapis 1 (regex) ----------
    GREETING = "greeting"        # sapaan pembuka
    CHITCHAT = "chitchat"        # basa-basi, bukan pertanyaan

    # ---------- Lapis 2 (LLM) ----------
    DOCUMENT_QUERY = "document_query"    # nanya isi dokumen chat ini
    FAQ_LOOKUP = "faq_lookup"            # pertanyaan umum/prosedural
    SUMMARY_REQUEST = "summary_request"  # minta ringkasan semua dokumen
    GENERAL_CHAT = "general_chat"        # obrolan, bukan pencarian informasi

    QUESTION = "question"  # fallback kalau klasifikasi LLM gagal


# Pola \A...\Z (cocok utuh) — pesan panjang yang cuma DIAWALI "halo" tetap lanjut RAG.
_GREETING_PATTERNS = [re.compile(p, re.I) for p in [
    r"\A(hai|halo|hello|hi|hey)[!.\s]*\Z",
    r"\Aselamat (pagi|siang|sore|malam)[!.\s]*\Z",
    r"\Aassalamu[a-z]*\s*(alaikum)?[!.\s]*\Z",
]]

_CHITCHAT_PATTERNS = [re.compile(p, re.I) for p in [
    r"\A(makasih|terima kasih|thanks|thank you|thx)[!.\s]*\Z",
    r"\A(oke|ok|okay|baik|sip|mantap|siap)[!.\s]*\Z",
    r"\A(ya|iya|yoi|yup|noted)[!.\s]*\Z",
    r"\A(sampai jumpa|bye|dadah|see you)[!.\s]*\Z",
]]

SKIP_RETRIEVAL_INTENTS = frozenset({Intent.GREETING, Intent.CHITCHAT})  # skip RAG total

LAYER2_INTENTS = frozenset({  # daftar putih output LLM, cegah kategori halusinasi
    Intent.DOCUMENT_QUERY, Intent.FAQ_LOOKUP, Intent.SUMMARY_REQUEST,
    Intent.GENERAL_CHAT, Intent.QUESTION,
})


def classify_intent_rule_based(text: str) -> str | None:
    """Lapis 1 saja — None berarti "lanjut ke lapis 2", beda dari QUESTION (fallback gagal)."""
    stripped = text.strip()
    if any(p.match(stripped) for p in _GREETING_PATTERNS):
        return Intent.GREETING
    if any(p.match(stripped) for p in _CHITCHAT_PATTERNS):
        return Intent.CHITCHAT
    return None


def classify_intent(text: str) -> str:
    """Placeholder sebelum lapis 2 — chat/routes.py menimpa hasil ini kalau lanjut ke LLM."""
    return classify_intent_rule_based(text) or Intent.QUESTION
