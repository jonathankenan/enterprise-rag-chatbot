"""
[PENANGGUNG JAWAB: Anggota B]
Intent Classification — SRS FCR-003 hal. 17, poin 9: "Sistem melakukan:
a) Intent classification, b) Role validation, c) Filtering guardrail".
Role validation (RBAC) dan Filtering guardrail (filters.py/prompt_injection.py)
sudah ada; ini menutup poin (a).

DUA LAPIS, bukan cuma satu (versi sebelumnya cuma lapis 1):

Lapis 1 — ATURAN (regex, DI SINI). Cuma jawab pertanyaan sempit "perlu
diproses lebih jauh sama sekali atau tidak" — GREETING/CHITCHAT murni.
Gratis & instan, tidak nambah 1 pun pemanggilan LLM.

Lapis 2 — LLM (lihat llm/router.py: analyze_query()), NEBENG ke
pemanggilan LLM yang SUDAH ADA buat merangkai ulang query pencarian
(dulu bernama get_standalone_query) — bukan pemanggilan LLM baru
terpisah. Klasifikasi lebih kaya (DOCUMENT_QUERY/FAQ_LOOKUP/dst) makan
biaya kalau berdiri sendiri; nebeng di sini artinya HARGANYA SAMA
dengan sebelum ada intent classification sama sekali (pemanggilan itu
sudah wajib ada buat re-phrase query, kita cuma minta 1 field ekstra
dari hasil yang sama).

Kategori lapis 2 dipakai buat menyesuaikan BOBOT ensemble retrieval
(lihat rag/vectorstore.py: retrieve_context(weight_hint=...)) — bukan
cuma label kosong. "escalation_request" SENGAJA TIDAK ADA di sini lagi
(sempat direncanakan, lalu dibatalkan) — eskalasi berbasis deteksi niat
via LLM punya masalah discoverability (user yang tidak tahu "kalimat
sakti" tidak akan pernah ketemu fitur eskalasi). Diganti tombol "Hubungi
Admin" yang SELALU terlihat di chat/page.jsx — deterministik, tidak
bergantung interpretasi AI sama sekali.
"""
import re


class Intent:
    # ---------- Lapis 1 (regex) ----------
    GREETING = "greeting"        # "halo", "selamat pagi", dst — sapaan pembuka
    CHITCHAT = "chitchat"        # "makasih", "oke", "sip" — basa-basi, bukan pertanyaan

    # ---------- Lapis 2 (LLM, cuma dipakai kalau lolos lapis 1) ----------
    DOCUMENT_QUERY = "document_query"  # nanya isi dokumen yang di-upload KE CHAT ini
    FAQ_LOOKUP = "faq_lookup"          # pertanyaan umum/prosedural (kandidat cocok FAQ/KB divisi)
    SUMMARY_REQUEST = "summary_request"  # minta ringkasan SELURUH dokumen chat (bukan pencarian semantik)
    GENERAL_CHAT = "general_chat"      # obrolan yang butuh dijawab tapi bukan pencarian informasi

    QUESTION = "question"  # fallback generik — dipakai kalau LLM classification gagal/tidak jalan


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

# Kategori lapis 2 yang VALID — dipakai buat validasi output LLM (llm/router.py)
# supaya kalau LLM "berhalusinasi" ngasih kategori yang tidak ada di daftar
# ini, sistem jatuh ke QUESTION (fallback aman), bukan dipakai mentah-mentah.
LAYER2_INTENTS = frozenset({
    Intent.DOCUMENT_QUERY, Intent.FAQ_LOOKUP, Intent.SUMMARY_REQUEST,
    Intent.GENERAL_CHAT, Intent.QUESTION,
})


def classify_intent_rule_based(text: str) -> str | None:
    """
    Lapis 1 SAJA. Kembalikan None (bukan Intent.QUESTION) kalau tidak cocok
    greeting/chitchat — None berarti "lanjut ke lapis 2", beda makna dari
    Intent.QUESTION yang berarti "sudah pasti fallback lapis 2 gagal".
    """
    stripped = text.strip()
    if any(p.match(stripped) for p in _GREETING_PATTERNS):
        return Intent.GREETING
    if any(p.match(stripped) for p in _CHITCHAT_PATTERNS):
        return Intent.CHITCHAT
    return None


def classify_intent(text: str) -> str:
    """
    Dipertahankan untuk kompatibilitas mundur (dipanggil chat/routes.py
    SEBELUM tahu apakah bakal lanjut ke lapis 2 atau tidak) — kalau lapis 1
    tidak cocok, kembalikan Intent.QUESTION sebagai placeholder sementara;
    chat/routes.py akan TIMPA nilai ini dengan hasil lapis 2 (analyze_query())
    kalau pesannya memang lanjut diproses LLM.
    """
    return classify_intent_rule_based(text) or Intent.QUESTION
