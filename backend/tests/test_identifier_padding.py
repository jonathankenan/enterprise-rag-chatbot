"""
Angka berpadding pada identifier (_canonical_identifier di vectorstore.py).

Dokumen menulis identifier dipadatkan dua digit ("SOP-02"). Ditanya persis
"SOP-2" (tanda hubung, tidak dipadatkan -- bentuk yang justru lebih wajar
diketik orang), saringan identifier lama mencocokkan STRING PERSIS: "sop-2"
!= "sop-02", tidak ada chunk yang cocok, dan pertanyaan tentang item yang
sebetulnya ADA ditolak sebagai "tidak ditemukan". "SOP 2" (spasi, bukan
identifier sama sekali di mata regex) kebetulan tetap terjawab lewat
retrieval semantik biasa -- itu yang menutupi bug ini sampai laporan
2026-08-31.
"""
from app.rag.vectorstore import (
    _canonical_identifier, extract_query_identifiers, text_mentions_identifier,
    identifier_only_in_example,
)


# --------------------------------------------------------------------------
# _canonical_identifier
# --------------------------------------------------------------------------

def test_nol_di_depan_dibuang():
    assert _canonical_identifier("sop-02") == "sop-2"
    assert _canonical_identifier("fr-01") == "fr-1"


def test_tanpa_nol_di_depan_tidak_berubah():
    assert _canonical_identifier("sop-2") == "sop-2"


def test_tahun_tidak_ikut_terpotong():
    """Nol cuma dibuang kalau digit PERTAMANYA memang '0' -- 2026 bukan."""
    assert _canonical_identifier("doc-fee-2026") == "doc-fee-2026"


def test_identifier_dua_segmen_kedua_segmen_dipadatkan():
    assert _canonical_identifier("nfr-perf-01") == "nfr-perf-1"


def test_banyak_nol_di_depan_tetap_terpadatkan():
    assert _canonical_identifier("sop-002") == "sop-2"


# --------------------------------------------------------------------------
# extract_query_identifiers -- kanonis sejak diekstrak
# --------------------------------------------------------------------------

def test_ekstraksi_query_menghasilkan_bentuk_kanonis():
    assert extract_query_identifiers("apa isi SOP-2") == {"sop-2"}
    assert extract_query_identifiers("apa isi SOP-02") == {"sop-2"}


# --------------------------------------------------------------------------
# text_mentions_identifier -- inti perbaikannya
# --------------------------------------------------------------------------

def test_query_tanpa_padding_menemukan_dokumen_berpadding():
    dok = "SOP-02 Permintaan Akses Sistem memerlukan persetujuan dua tingkat."
    assert text_mentions_identifier(dok, {"sop-2"})


def test_query_berpadding_menemukan_dokumen_tanpa_padding():
    dok = "SOP-2 Permintaan Akses Sistem memerlukan persetujuan dua tingkat."
    assert text_mentions_identifier(dok, {"sop-2"})


def test_nomor_berbeda_tidak_ikut_cocok():
    """sop-2 tidak boleh mencocoki sop-20 atau sop-12."""
    assert not text_mentions_identifier("SOP-20 tentang lain", {"sop-2"})
    assert not text_mentions_identifier("SOP-12 tentang lain", {"sop-2"})


def test_dokumen_tanpa_identifier_tidak_cocok():
    assert not text_mentions_identifier("paragraf biasa tanpa kode apa pun", {"sop-2"})


# --------------------------------------------------------------------------
# identifier_only_in_example -- arah pencarian terbalik (kanonis -> mentah)
# --------------------------------------------------------------------------

def test_contoh_berpadding_tetap_terdeteksi_dari_query_tanpa_padding():
    contoh = '{ "doc_id": "SOP-02", "status": "ok" }'
    assert identifier_only_in_example(contoh, {"sop-2"})


def test_baris_tabel_berpadding_tetap_terbaca_sebagai_nyata():
    """Item nyata (bukan contoh) tidak boleh ikut salah tertandai gara-gara padding."""
    baris = "|SOP-02|Permintaan Akses|Ketentuan lengkap di sini|"
    assert not identifier_only_in_example(baris, {"sop-2"})
