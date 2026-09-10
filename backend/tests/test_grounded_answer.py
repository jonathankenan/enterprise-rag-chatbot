"""
Kapan model boleh menjawab dari pengetahuan umum (build_prompt, router.py).

session_has_document cuma mengecek dokumen yang diunggah ke SESI CHAT ini
(kb_general + chat_id). Dia buta terhadap KB divisi dan FAQ, padahal keduanya
sama-sama korpus perusahaan. Akibatnya untuk user yang bertanya ke KB divisi
tanpa pernah mengunggah apa pun ke chat-nya, instruksi yang aktif adalah versi
longgar -- model DIPERINTAHKAN mengisi dari pengetahuan sendiri:

    "If the context is irrelevant or missing, you MUST still answer the
     user's question using your own internal knowledge as a general AI."

Terukur pada "jelaskan isi SOP-02 WAS": model mengambil satu kalimat asli
SOP-02 milik PTI lalu mengembangkannya jadi SOP karangan lengkap (formulir
permintaan, tingkat otoritas, log audit, MFA, least privilege), dan menafsirkan
"WAS" sendiri sebagai WebSphere Application Server. Diuji ulang lewat konteks
retrieval sungguhan: 806 karakter -> 163 karakter setelah aturan ini aktif.
"""
from app.llm.router import build_prompt

CTX = [{"text": "|Kode SOP|Judul|Ketentuan|\n|---|---|---|\n"
                "|SOP-02|Permintaan Akses Sistem|Akses ke Core Trading Engine "
                "memerlukan persetujuan dua tingkat.|"}]

FALLBACK_UMUM = "internal knowledge as a general AI"
ANTI_KARANGAN = "DO NOT ELABORATE"


# --------------------------------------------------------------------------
# Mode longgar: percakapan umum tidak boleh dikorbankan
# --------------------------------------------------------------------------

def test_default_masih_boleh_jawab_dari_pengetahuan_umum():
    """
    FCR-003 adalah "Generic ChatBot" -- pertanyaan umum yang tidak menyebut
    item korpus tetap harus dijawab, bukan ditolak.
    """
    p = build_prompt("apa itu machine learning", CTX, None)
    assert FALLBACK_UMUM in p
    assert ANTI_KARANGAN not in p


# --------------------------------------------------------------------------
# Mode ketat
# --------------------------------------------------------------------------

def test_pertanyaan_item_korpus_melarang_pengetahuan_umum():
    p = build_prompt("jelaskan isi SOP-02", CTX, None, answer_must_be_grounded=True)
    assert FALLBACK_UMUM not in p
    assert ANTI_KARANGAN in p


def test_dokumen_sesi_juga_mengaktifkan_mode_ketat():
    """Perilaku lama tidak berubah: unggahan ke sesi chat tetap memicu mode ketat."""
    p = build_prompt("jelaskan dokumen ini", CTX, None, session_has_document=True)
    assert FALLBACK_UMUM not in p
    assert ANTI_KARANGAN in p


def test_dua_pemicu_boleh_bersamaan():
    p = build_prompt("jelaskan SOP-02", CTX, None,
                     session_has_document=True, answer_must_be_grounded=True)
    assert FALLBACK_UMUM not in p
    assert ANTI_KARANGAN in p


# --------------------------------------------------------------------------
# Isi aturannya
# --------------------------------------------------------------------------

def test_aturan_menyebut_larangan_memperluas_singkatan():
    """
    "WAS" ditafsirkan model sebagai WebSphere Application Server padahal
    dokumen tidak pernah memperluasnya.
    """
    p = build_prompt("jelaskan SOP-02 WAS", CTX, None, answer_must_be_grounded=True)
    assert "Do NOT expand an abbreviation" in p


def test_aturan_menyatakan_jawaban_pendek_itu_benar():
    """Tanpa ini model menyamakan panjang dengan kualitas dan mengarang isian."""
    p = build_prompt("jelaskan SOP-02", CTX, None, answer_must_be_grounded=True)
    assert "stops where the document stops is CORRECT" in p


# --------------------------------------------------------------------------
# Urutan aturan -- posisi akhir yang sudah terbukti jangan tergeser
# --------------------------------------------------------------------------

def test_aturan_bahasa_tetap_paling_akhir():
    p = build_prompt("jelaskan SOP-02", CTX, None, answer_must_be_grounded=True)
    assert p.rstrip().endswith("YOUR RESPONSE:")
    assert p.index("IMPORTANT — LANGUAGE") > p.index(ANTI_KARANGAN)


def test_anti_karangan_sebelum_grounding_rule():
    """GROUNDING_RULE (jangan karang FIELD) dan aturan ini (jangan karang ISI)
    saling melengkapi; urutannya dikunci supaya tidak tertukar tanpa sadar."""
    p = build_prompt("jelaskan SOP-02", CTX, None, answer_must_be_grounded=True)
    assert p.index(ANTI_KARANGAN) < p.index("DO NOT INVENT FIELDS")
