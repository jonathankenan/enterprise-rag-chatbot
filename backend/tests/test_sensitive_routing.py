"""
Deteksi data sensitif -> pemaksaan LLM on-prem (SRS F1-05).

Temuan uji terima E5 (2026-09-13): satu typo melumpuhkan kontrol ini
sepenuhnya. "dokumen rahasi" tidak memuat substring "rahasia", jadi tidak
pernah ditandai sensitif. Dikonfirmasi langsung, bukan diduga: dengan
provider komersial terpilih, pertanyaan itu keluar sebagai
llm_used="commercial (groq)".

Perbaikan pertama yang dicoba -- ikut memeriksa standalone_query hasil
analyze_query(), yang memang punya instruksi memperbaiki typo -- DITOLAK
sebagai jaring utama: pemanggilan ulang yang sama mengembalikan typo-nya apa
adanya. Typo-fixing itu keputusan LLM, jadi non-deterministik. Jaring utamanya
sekarang deterministik (substring persis + toleransi satu edit per kata), dan
rewrite tinggal jadi lapis tambahan.

Daftar kata kunci dibaca dari settings, BUKAN disalin sebagai literal -- kalau
SENSITIVE_KEYWORDS di .env diubah, test ini harus menguji nilai yang
benar-benar berlaku, bukan nilai yang kebetulan ada saat test ditulis.

No Postgres, no Ollama, no API keys.
"""
import pytest

from app.config import settings
from app.llm.router import detect_sensitive, _within_one_edit, _FUZZY_MIN_LEN

KEYWORDS = settings.sensitive_keyword_list
FUZZY_KEYWORDS = [k for k in KEYWORDS if len(k) >= _FUZZY_MIN_LEN and " " not in k]
SHORT_KEYWORDS = [k for k in KEYWORDS if len(k) < _FUZZY_MIN_LEN]

PII = [{"type": "KTP", "value": "3171234567890002"}]


# ---------------------------------------------------------------- dasar

def test_kata_kunci_di_teks_mentah_tetap_terdeteksi():
    """Perilaku dasar, tidak boleh berubah oleh perbaikan apa pun."""
    for kw in KEYWORDS:
        assert detect_sensitive(f"tolong jelaskan dokumen {kw} ini", []) is True


def test_kata_kunci_menempel_akhiran_tetap_terdeteksi():
    """Yang ditangkap pencocokan substring, bukan jarak edit."""
    for kw in FUZZY_KEYWORDS:
        assert detect_sensitive(f"dokumen {kw}nya mana", []) is True


def test_teks_bersih_tidak_terdeteksi():
    assert detect_sensitive("berapa target SLA divisi", []) is False


def test_pii_saja_sudah_cukup():
    assert detect_sensitive("nomor saya 3171234567890002", PII) is True


# ------------------------------------------------- inti perbaikan E5

@pytest.mark.skipif(not FUZZY_KEYWORDS, reason="tidak ada kata kunci yang cukup panjang untuk fuzzy")
def test_typo_huruf_hilang_tertangkap_tanpa_bantuan_rewrite():
    """
    Kasus E5 apa adanya ("rahasia" -> "rahasi"), dan ini harus jalan TANPA
    mengandalkan rewrite -- itu seluruh alasan jaring deterministik ini ada.
    """
    for kw in FUZZY_KEYWORDS:
        assert detect_sensitive(f"dokumen {kw[:-1]}", []) is True


@pytest.mark.skipif(not FUZZY_KEYWORDS, reason="tidak ada kata kunci yang cukup panjang untuk fuzzy")
def test_typo_huruf_tertukar_dan_kelebihan_huruf_tertangkap():
    for kw in FUZZY_KEYWORDS:
        tertukar = kw[:-2] + kw[-1] + kw[-2]      # dua huruf terakhir tertukar
        kelebihan = kw + kw[-1]                    # huruf terakhir dobel
        assert detect_sensitive(f"dokumen {tertukar}", []) is True, kw
        assert detect_sensitive(f"dokumen {kelebihan}", []) is True, kw


@pytest.mark.skipif(not SHORT_KEYWORDS, reason="tidak ada kata kunci pendek di konfigurasi")
def test_kata_kunci_pendek_tidak_dicocokkan_fuzzy():
    """
    Batas _FUZZY_MIN_LEN ada supaya "ktp" tidak menyeret "kta"/"ktm"/"ktu".
    Kalau kata kunci pendek ikut fuzzy, hampir semua singkatan tiga huruf
    akan memaksa on-prem.
    """
    for kw in SHORT_KEYWORDS:
        assert detect_sensitive(f"nomor {kw}", []) is True, "yang persis tetap harus kena"
        assert detect_sensitive(f"nomor {kw[:-1]}x", []) is False, kw


def test_kata_panjang_yang_jelas_beda_tidak_terpicu():
    """Beda lebih dari satu edit -> tidak boleh kena (mis. 'internasional')."""
    for q in ("kirim laporan internasional", "jadwal maintenance server",
              "berapa ambang batas transaksi", "rapat triwulanan divisi"):
        assert detect_sensitive(q, []) is False, q


def test_false_positive_yang_diterima_sadar():
    """
    Biaya yang disadari dari toleransi satu edit: kata wajar yang kebetulan
    berjarak satu substitusi dari kata kunci ikut terpicu -- "interval" vs
    "internal" (n->v). Akibatnya pertanyaan tak sensitif dipaksa ke on-prem.
    Diterima karena arahnya melindungi (bukan membocorkan), dan alternatifnya
    -- allow-list kata aman -- akan basi begitu SENSITIVE_KEYWORDS di .env
    diubah. Test ini ada supaya biayanya tercatat, bukan ditemukan ulang saat
    demo.
    """
    if "internal" not in KEYWORDS:
        pytest.skip("contoh ini spesifik untuk kata kunci 'internal'")
    assert detect_sensitive("berapa interval backup harian", []) is True


# --------------------------------------------- rewrite sebagai lapis tambahan

@pytest.mark.skipif(not FUZZY_KEYWORDS, reason="tidak ada kata kunci yang cukup panjang untuk fuzzy")
def test_rewrite_tetap_dipakai_sebagai_lapis_tambahan():
    """
    Menangkap yang jarak edit tidak bisa: teks mentah sama sekali tidak
    menyebut kata kuncinya, tapi rewrite memunculkannya.
    """
    kw = FUZZY_KEYWORDS[0]
    assert detect_sensitive("dokumen itu apa isinya", []) is False
    assert detect_sensitive("dokumen itu apa isinya", [], rewritten=f"isi dokumen {kw}") is True


def test_rewrite_hanya_bisa_menambah_sensitivitas_tidak_menghilangkan():
    """
    Arah kegagalan sengaja satu arah. Kalau rewrite membuang kata kuncinya
    (LLM salah tafsir, atau memang meringkas), status sensitif dari teks
    mentah TIDAK boleh ikut hilang.
    """
    kw = KEYWORDS[0]
    assert detect_sensitive(f"dokumen {kw}", [], rewritten="dokumen operasional") is True


def test_rewrite_none_sama_dengan_perilaku_pemanggil_lama():
    kw = KEYWORDS[0]
    assert detect_sensitive(f"dokumen {kw}", [], rewritten=None) is True
    assert detect_sensitive("dokumen operasional", [], rewritten=None) is False


def test_keduanya_bersih_tetap_tidak_sensitif():
    assert detect_sensitive("target SLA divisi", [], rewritten="division SLA target") is False


# ------------------------------------------------------- unit _within_one_edit

def test_within_one_edit_menerima_satu_perubahan():
    assert _within_one_edit("rahasia", "rahasia") is True   # identik
    assert _within_one_edit("rahasi", "rahasia") is True    # satu huruf hilang
    assert _within_one_edit("rahasiaa", "rahasia") is True  # satu huruf lebih
    assert _within_one_edit("rahasiq", "rahasia") is True   # satu huruf beda
    assert _within_one_edit("rahsia", "rahasia") is True    # satu huruf hilang di tengah
    assert _within_one_edit("rahasai", "rahasia") is True   # dua huruf tertukar (Damerau)
    assert _within_one_edit("arhasia", "rahasia") is True   # tertukar di awal


def test_within_one_edit_menolak_dua_perubahan_atau_lebih():
    assert _within_one_edit("rhasa", "rahasia") is False
    assert _within_one_edit("internasional", "internal") is False
    assert _within_one_edit("", "rahasia") is False
    assert _within_one_edit("xyz", "rahasia") is False


def test_within_one_edit_simetris():
    """Urutan argumen tidak boleh mengubah hasil."""
    for a, b in (("rahasi", "rahasia"), ("rahasiaa", "rahasia"), ("rhasa", "rahasia")):
        assert _within_one_edit(a, b) == _within_one_edit(b, a), (a, b)
