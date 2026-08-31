"""
Pemotongan tabel markdown per baris (chunk_text di rag/vectorstore.py).

Satu baris tabel adalah satu record. Digabung dalam satu chunk, record-record
itu berebut di dalam satu vektor dan model melihat tetangga yang nilainya bisa
disalin. Tes ini menjaga tiga hal sekaligus:

  * baris jadi chunk sendiri-sendiri
  * tiap baris tetap bisa dibaca (bawa header tabelnya)
  * yang BUKAN tabel record tidak ikut tercerai-berai
"""
from app.rag.vectorstore import chunk_text, TABLE_ROW_MIN_COLUMNS, TABLE_ROW_MIN_ROWS

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


def _rows(chunks, ident):
    return [c for c in chunks if ident in c]


# --------------------------------------------------------------------------
# Baris jadi chunk sendiri
# --------------------------------------------------------------------------

def test_tiap_baris_jadi_chunk_terpisah():
    chunks = chunk_text(TABLE_ONLY)
    for ident in ("FR-01", "FR-02", "FR-03"):
        assert len(_rows(chunks, ident)) == 1, f"{ident} tidak persis satu chunk"


def test_baris_tidak_membawa_baris_lain():
    """Inti perbaikannya. Chunk FR-01 tidak boleh memuat FR-02 atau FR-03."""
    fr01 = _rows(chunk_text(TABLE_ONLY), "FR-01")[0]
    assert "FR-02" not in fr01
    assert "FR-03" not in fr01


def test_baris_membawa_header_tabel():
    """Tanpa header, angka di baris kehilangan nama kolomnya."""
    fr03 = _rows(chunk_text(TABLE_ONLY), "FR-03")[0]
    for kolom in ("Category", "Detailed Requirement Description", "Priority"):
        assert kolom in fr03, f"kolom {kolom!r} hilang dari chunk baris"


def test_isi_baris_utuh():
    fr03 = _rows(chunk_text(TABLE_ONLY), "FR-03")[0]
    assert "$35.00 per occurrence" in fr03


def test_tidak_ada_isi_yang_hilang():
    """Setiap identifier harus tetap ada di suatu tempat setelah dipotong."""
    gabungan = "\n".join(chunk_text(TABLE_ONLY))
    for ident in ("FR-01", "FR-02", "FR-03", "92%", "$35.00"):
        assert ident in gabungan


# --------------------------------------------------------------------------
# Judul bagian: hanya kalau benar-benar memperkenalkan tabelnya
# --------------------------------------------------------------------------

def test_judul_ikut_kalau_langsung_memperkenalkan_tabel():
    teks = "#### 6.1 Performance SLAs\n" + TABLE_ONLY
    fr01 = _rows(chunk_text(teks), "FR-01")[0]
    assert "6.1 Performance SLAs" in fr01


def test_judul_dibuang_kalau_ada_prosa_menyela():
    """
    Diukur pada Project NEXUS halaman 8: pymupdf4llm menaruh pipe-table NFR
    SETELAH judul "6.2 Security", padahal isinya milik "6.1 Performance".
    Judul terdekat yang dipisah prosa TIDAK boleh dipercaya -- label bagian
    yang SALAH lebih merugikan daripada tidak ada label sama sekali.
    """
    teks = (
        "#### 6.2 Security, Privacy & Regulatory Compliance\n\n"
        "As a financial system handling personal wealth data, NEXUS must conform.\n\n"
        + TABLE_ONLY
    )
    fr01 = _rows(chunk_text(teks), "FR-01")[0]
    assert "6.2 Security" not in fr01, "judul yang salah ikut menempel ke baris"
    assert "FR-01" in fr01 and "Priority" in fr01, "isi barisnya harus tetap utuh"


def test_judul_tidak_dipakai_ulang_tabel_berikutnya():
    teks = (
        "#### 4.1 Bagian Pertama\n"
        + TABLE_ONLY
        + "\n|X|Y|Z|\n|---|---|---|\n|RSK-01|a|b|\n|RSK-02|c|d|\n"
    )
    rsk = _rows(chunk_text(teks), "RSK-01")[0]
    assert "4.1 Bagian Pertama" not in rsk


# --------------------------------------------------------------------------
# Yang tidak boleh ikut dipotong
# --------------------------------------------------------------------------

def test_tabel_dua_kolom_dibiarkan_utuh():
    """
    Daftar definisi seperti spesifikasi endpoint tidak boleh tercerai-berai
    jadi kepingan kunci-nilai.
    """
    memuat = [c for c in chunk_text(API_TABLE) if "HTTP Method" in c]
    assert len(memuat) == 1
    assert "Endpoint URL" in memuat[0], "spesifikasi terpotong dari judulnya"


def test_tabel_satu_baris_dibiarkan_utuh():
    chunks = chunk_text("|A|B|C|\n|---|---|---|\n|satu|dua|tiga|\n")
    assert len(chunks) == 1


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
    fr01 = _rows(chunk_text(teks), "FR-01")[0]
    assert "Paragraf pembuka" not in fr01


# --------------------------------------------------------------------------
# Ambang batas
# --------------------------------------------------------------------------

def test_ambang_kolom_dihormati():
    n = TABLE_ROW_MIN_COLUMNS - 1
    kolom = "|".join(f"K{i}" for i in range(n))
    sep = "|".join("---" for _ in range(n))
    isi = "\n".join("|" + "|".join(f"v{i}{j}" for j in range(n)) + "|" for i in range(2))
    chunks = chunk_text(f"|{kolom}|\n|{sep}|\n{isi}\n")
    assert len(chunks) == 1, "tabel di bawah ambang kolom ikut dipotong"


def test_ambang_baris_dihormati():
    assert TABLE_ROW_MIN_ROWS >= 2, (
        "memotong tabel berbaris tunggal tidak ada gunanya -- tidak ada "
        "tetangga yang bisa bocor"
    )


def test_teks_kosong_aman():
    assert chunk_text("") == []
    assert chunk_text("\n\n\n") == []
