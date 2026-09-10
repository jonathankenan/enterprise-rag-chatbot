"""
Penjagaan hasil rewrite kueri (analyze_query di llm/router.py).

qwen2.5:7b sering MENYALIN KEMBALI kalimat instruksinya alih-alih
menjalankannya, dan hasilnya masuk ke standalone_query apa adanya. Terukur
2026-09-01 pada 3 kueri x 3 run: on-prem mengembalikan echo instruksi di 7
dari 9 percobaan, Groq nol dari 9.

Bukan cuma jelek -- teks instruksi mendominasi embedding sampai chunk yang
benar terdorong keluar top-10, lalu penjaga identifier melapor "tidak
ditemukan" untuk item yang sebetulnya ADA:

    "contents of SOP-01"                        -> 2 chunk cocok, dijawab
    "rephrase the follow-up ...: ... SOP-01"    -> 0 chunk cocok, DITOLAK

Gejalanya di UI: SOP-01 ditolak sementara SOP-02 dan SOP-03 terjawab, dari
korpus yang sama dalam chat yang sama.
"""
from app.llm.router import _is_instruction_echo, _lost_identifiers, _parse_query_analysis
import json

FALLBACK = {"standalone_query": "sebutkan isi SOP-01", "intent": "question"}


# --------------------------------------------------------------------------
# Deteksi echo instruksi
# --------------------------------------------------------------------------

def test_echo_polos_terdeteksi():
    assert _is_instruction_echo(
        "rephrase the follow-up question into a standalone English search query")


def test_echo_dengan_kueri_ditempel_terdeteksi():
    """Bentuk yang paling sering muncul: instruksi + pesan asli di belakangnya."""
    assert _is_instruction_echo(
        "rephrase the follow-up question into a standalone English search query: "
        "sebutkan isi SOP-02")


def test_kueri_wajar_tidak_terdeteksi():
    for q in ("contents of SOP-01", "apa isi prosedur akses sistem",
              "division budget approval limit", "risk assessment matrix"):
        assert not _is_instruction_echo(q), q


# --------------------------------------------------------------------------
# Identifier yang hilang saat rewrite
# --------------------------------------------------------------------------

def test_identifier_hilang_terdeteksi():
    assert _lost_identifiers("sebutkan isi SOP-01", "contents of the procedure")


def test_identifier_dipertahankan_tidak_terdeteksi():
    assert not _lost_identifiers("sebutkan isi SOP-01", "contents of SOP-01")


def test_padding_berbeda_tetap_dianggap_sama():
    """Kanonisasi identifier berlaku di sini juga -- SOP-1 dan SOP-01 sama."""
    assert not _lost_identifiers("sebutkan isi SOP-01", "contents of SOP-1")


def test_tanpa_identifier_tidak_pernah_terpicu():
    assert not _lost_identifiers("apa kabar", "how are you")


# --------------------------------------------------------------------------
# Integrasi lewat _parse_query_analysis
# --------------------------------------------------------------------------

def _parse(sq):
    return _parse_query_analysis(
        json.dumps({"standalone_query": sq, "intent": "question"}), FALLBACK)


def test_echo_dikembalikan_ke_pesan_asli():
    hasil = _parse("rephrase the follow-up question into a standalone English search query")
    assert hasil["standalone_query"] == FALLBACK["standalone_query"]


def test_identifier_hilang_dikembalikan_ke_pesan_asli():
    hasil = _parse("contents of the procedure")
    assert hasil["standalone_query"] == FALLBACK["standalone_query"]


def test_rewrite_bersih_dipertahankan():
    """Rewrite yang benar tidak boleh ikut dibuang -- itu gunanya fitur ini."""
    hasil = _parse("contents of SOP-01")
    assert hasil["standalone_query"] == "contents of SOP-01"


def test_json_rusak_tetap_fallback_aman():
    assert _parse_query_analysis("bukan json", FALLBACK) == FALLBACK
