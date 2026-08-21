"""
[PENANGGUNG JAWAB: Anggota B]
Intent Classification — SRS FCR-003 hal. 17, poin 9: "Sistem melakukan:
a) Intent classification, b) Role validation, c) Filtering guardrail".
Role validation (RBAC) dan Filtering guardrail (filters.py/prompt_injection.py)
sudah ada; ini menutup poin (a) yang sebelumnya belum ada langkah terpisah.

Pendekatan berbasis ATURAN (regex), bukan panggilan LLM tambahan — beda dari
get_standalone_query() yang memang butuh LLM buat merangkai ulang kalimat.
Klasifikasi di sini cuma perlu jawab pertanyaan sempit "perlu RAG atau
tidak", jadi heuristik sudah cukup dan JAUH lebih murah/cepat (tidak nambah
1 pemanggilan LLM lagi di setiap pesan, tidak nambah latency).
"""
import re


class Intent:
    GREETING = "greeting"      # "halo", "selamat pagi", dst — sapaan pembuka
    CHITCHAT = "chitchat"       # "makasih", "oke", "sip" — basa-basi, bukan pertanyaan
    QUESTION = "question"       # default — perlu diproses lewat RAG seperti biasa


# Cuma cocok kalau pesan itu PENDEK dan SELURUHNYA basa-basi — pesan
# panjang yang KEBETULAN diawali "halo" (mis. "Halo, saya mau tanya soal
# audit log...") tetap harus lewat RAG, bukan di-skip cuma karena ada
# kata "halo" di depan. Makanya polanya \A...\Z (cocok utuh, bukan search).
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

# Dipakai chat/routes.py buat memutuskan skip RAG atau tidak — dikumpulkan
# di satu tempat (bukan hardcode {"greeting","chitchat"} di 2 tempat beda)
# supaya kalau nanti nambah kategori baru yang juga harus skip RAG, cukup
# diedit di sini.
SKIP_RETRIEVAL_INTENTS = frozenset({Intent.GREETING, Intent.CHITCHAT})


def classify_intent(text: str) -> str:
    stripped = text.strip()
    if any(p.match(stripped) for p in _GREETING_PATTERNS):
        return Intent.GREETING
    if any(p.match(stripped) for p in _CHITCHAT_PATTERNS):
        return Intent.CHITCHAT
    return Intent.QUESTION
