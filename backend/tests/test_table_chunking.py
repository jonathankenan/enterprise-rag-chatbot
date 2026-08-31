"""
Tabel markdown diindeks UTUH sekaligus PER BARIS (chunk_text di vectorstore.py).

Satu baris tabel adalah satu record. Digabung dalam satu chunk, record-record
itu berebut di dalam satu vektor dan model melihat tetangga yang nilainya bisa
disalin. Tapi memotong HANYA per baris merusak pertanyaan sintesis: percobaan
pertama (6dbdc18, di-revert lewat 0313bae) menjatuhkan E1 dari 3/3 fakta ke
2/3 karena tiga angka yang dibutuhkan tinggal di baris berbeda dan yang ketiga
kalah bersaing masuk top-10.

Jadi keduanya diindeks, dan saringan identifier yang memilih. Tes ini menjaga
ketiga sisinya: baris ada, tabel utuh ada, dan yang bukan tabel record tidak
ikut tercerai-berai.
"""
from app.rag.vectorstore import (
    chunk_text, count_table_body_rows,
    TABLE_ROW_MIN_COLUMNS, TABLE_ROW_MIN_ROWS,
)

# Verbatim dari Project NEXUS halaman 7, apa adanya hasil pymupdf4llm.
TABLE_ONLY = """|Req<br>ID|Category|Detailed Requirement Description|Priority|
|---|---|---|---|
|**FR-01**|Retrieval<br>Accuracy|The RAG module shall achieve a minimum semantic retrieval accuracy of 92%<br>(MRR@5).|**Must**<br>**Have**|
|**FR-02**|Source Citation|Every response must include precise inline citations.|**Must**<br>**Have**|
|**FR-03**|Fee Schedule<br>Verification|The Overdraft Fee for Consumer Checking accounts is $35.00 per occurrence.|**Must**<br>**Have**|
"""

# Tabel 2 kolom: daftar definisi, bukan tabel record.
API_TABLE = """#### 7.2 Endpoint Specifications

|Endpoint URL:|https://api.nexus.gfsc.internal/v1/retrieval/query|
|---|---|
|**HTTP Method:**|`POST`|
|**Headers:**|`Authorization: Bearer [JWT_TOKEN]`|
"""


def _with(chunks, ident):
    return [c for c in chunks if ident in c]


def _rows_only(chunks):
    return [c for c in chunks if count_table_body_rows(c) == 1]


def _whole(chunks):
    return [c for c in chunks if count_table_body_rows(c) > 1]


# --------------------------------------------------------------------------
# Kedua bentuk harus dihasilkan
# --------------------------------------------------------------------------

def test_menghasilkan_chunk_baris_dan_chunk_tabel_utuh():
    chunks = chunk_text(TABLE_ONLY)
    assert len(_rows_only(chunks)) == 3, "harus ada satu chunk per baris isi"
    assert len(_whole(chunks)) == 1, "harus ada satu chunk tabel utuh"


def test_chunk_baris_tidak_membawa_baris_lain():
    """
    Inti perbaikannya, dan alasan chunk baris ada sama sekali. Diukur pada
    pertanyaan "apa prioritas FR-11": konteks lama memuat FR-08/09/10/12
    dengan ENAM nilai priority sekaligus; dengan chunk baris cuma tersisa satu.
    """
    fr01 = [c for c in _rows_only(chunk_text(TABLE_ONLY)) if "FR-01" in c]
    assert len(fr01) == 1
    assert "FR-02" not in fr01[0]
    assert "FR-03" not in fr01[0]


def test_chunk_tabel_utuh_memuat_semua_baris():
    """
    Alasan chunk tabel utuh tetap ada: pertanyaan sintesis butuh angka dari
    beberapa baris sekaligus, dan sebagai chunk terpisah baris-baris itu bisa
    kalah bersaing masuk top-10.
    """
    utuh = _whole(chunk_text(TABLE_ONLY))[0]
    for ident in ("FR-01", "FR-02", "FR-03"):
        assert ident in utuh


def test_setiap_bentuk_membawa_header_tabel():
    """Tanpa header, angka di baris kehilangan nama kolomnya."""
    for c in chunk_text(TABLE_ONLY):
        if count_table_body_rows(c) >= 1:
            assert "Priority" in c and "Category" in c


def test_tidak_ada_isi_yang_hilang():
    gabungan = "\n".join(chunk_text(TABLE_ONLY))
    for ident in ("FR-01", "FR-02", "FR-03", "92%", "$35.00"):
        assert ident in gabungan


# --------------------------------------------------------------------------
# count_table_body_rows -- dasar pemilihan chunk paling spesifik
# --------------------------------------------------------------------------

def test_hitung_baris_isi_mengabaikan_header_dan_pemisah():
    assert count_table_body_rows(TABLE_ONLY) == 3


def test_hitung_baris_isi_prosa_nol():
    assert count_table_body_rows("Paragraf biasa tanpa tabel.") == 0


def test_hitung_baris_isi_chunk_satu_baris():
    for c in _rows_only(chunk_text(TABLE_ONLY)):
        assert count_table_body_rows(c) == 1


# --------------------------------------------------------------------------
# Judul bagian: hanya kalau benar-benar memperkenalkan tabelnya
# --------------------------------------------------------------------------

def test_judul_ikut_kalau_langsung_memperkenalkan_tabel():
    chunks = chunk_text("#### 6.1 Performance SLAs\n" + TABLE_ONLY)
    assert all("6.1 Performance SLAs" in c for c in _rows_only(chunks))


def test_judul_dibuang_kalau_ada_prosa_menyela():
    """
    Diukur pada Project NEXUS halaman 8: pymupdf4llm menaruh pipe-table NFR
    SETELAH judul "6.2 Security", padahal isinya milik "6.1 Performance".
    Label bagian yang SALAH lebih merugikan daripada tidak ada label.
    """
    teks = ("#### 6.2 Security, Privacy & Regulatory Compliance\n\n"
            "As a financial system handling personal wealth data, NEXUS must conform.\n\n"
            + TABLE_ONLY)
    fr01 = [c for c in _rows_only(chunk_text(teks)) if "FR-01" in c][0]
    assert "6.2 Security" not in fr01
    assert "FR-01" in fr01 and "Priority" in fr01


def test_judul_tidak_dipakai_ulang_tabel_berikutnya():
    teks = ("#### 4.1 Bagian Pertama\n" + TABLE_ONLY
            + "\n|X|Y|Z|\n|---|---|---|\n|RSK-01|a|b|\n|RSK-02|c|d|\n")
    rsk = [c for c in _rows_only(chunk_text(teks)) if "RSK-01" in c][0]
    assert "4.1 Bagian Pertama" not in rsk


# --------------------------------------------------------------------------
# Yang tidak boleh ikut dipotong
# --------------------------------------------------------------------------

def test_tabel_dua_kolom_dibiarkan_utuh():
    """Daftar definisi tidak boleh tercerai-berai jadi kepingan kunci-nilai."""
    memuat = [c for c in chunk_text(API_TABLE) if "HTTP Method" in c]
    assert len(memuat) == 1
    assert "Endpoint URL" in memuat[0]


def test_tabel_satu_baris_dibiarkan_utuh():
    assert len(chunk_text("|A|B|C|\n|---|---|---|\n|satu|dua|tiga|\n")) == 1


def test_prosa_tanpa_tabel_tidak_berubah():
    chunks = chunk_text("## Judul\n\nSatu paragraf biasa tanpa tabel sama sekali.\n")
    assert len(chunks) == 1
    assert "Satu paragraf biasa" in chunks[0]


def test_prosa_sebelum_dan_sesudah_tabel_tetap_ada():
    teks = "## Judul\n\nParagraf pembuka.\n\n" + TABLE_ONLY + "\nParagraf penutup.\n"
    gabungan = "\n".join(chunk_text(teks))
    assert "Paragraf pembuka" in gabungan
    assert "Paragraf penutup" in gabungan


def test_prosa_tidak_tercampur_ke_chunk_baris():
    teks = "## Judul\n\nParagraf pembuka.\n\n" + TABLE_ONLY
    for c in _rows_only(chunk_text(teks)):
        assert "Paragraf pembuka" not in c


# --------------------------------------------------------------------------
# Ambang batas
# --------------------------------------------------------------------------

def test_ambang_kolom_dihormati():
    n = TABLE_ROW_MIN_COLUMNS - 1
    kolom = "|".join(f"K{i}" for i in range(n))
    sep = "|".join("---" for _ in range(n))
    isi = "\n".join("|" + "|".join(f"v{i}{j}" for j in range(n)) + "|" for i in range(2))
    assert len(chunk_text(f"|{kolom}|\n|{sep}|\n{isi}\n")) == 1


def test_ambang_baris_dihormati():
    assert TABLE_ROW_MIN_ROWS >= 2, (
        "memotong tabel berbaris tunggal tidak ada gunanya -- tidak ada "
        "tetangga yang bisa bocor, dan chunk utuh + chunk baris jadi kembar"
    )


def test_teks_kosong_aman():
    assert chunk_text("") == []
    assert chunk_text("\n\n\n") == []
    assert count_table_body_rows("") == 0
