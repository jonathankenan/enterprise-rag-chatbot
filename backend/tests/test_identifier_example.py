"""
Identifier yang ADA di korpus tapi cuma sebagai data di dalam cuplikan contoh.

Kasus asalnya: "jelaskan DOC-FEE-2026". Nama itu memang tertulis di Project
NEXUS, tapi hanya di dalam contoh respons API pada bagian 7.2. Sistem
menjawabnya seolah dokumen sungguhan, termasuk menafsirkan angka 0.892 di
contoh itu sebagai skor kemiripan terhadap kueri user.

Yang dijaga di sini: contoh terdeteksi sebagai contoh, DAN item nyata tidak
ikut tertandai.
"""
import pytest

from app.rag.vectorstore import identifier_only_in_example, text_mentions_identifier

NEXUS_API = (
    'Expected Response: { "status": "success", "chunks": [{ "doc_id": '
    '"DOC-FEE-2026", "text": "Premier account holders receive 2 free SWIFT '
    'transfers per month, then $45 per wire.", "score": 0.892 }] }'
)
NEXUS_MD = (
    '|**Expected Response:**|`{ "status": "success", "chunks": [{ "doc_id": '
    '"DOC-FEE-2026",`<br>`"score": 0.892 }] }`|'
)
FR_ROW = (
    "|**FR-11**|Card Replacement|The system must explain the replacement "
    "process for lost cards.|**Could**<br>**Have**|"
)


def test_payload_teks_polos_terdeteksi_contoh():
    assert identifier_only_in_example(NEXUS_API, {"doc-fee-2026"})


def test_payload_dalam_tabel_markdown_terdeteksi_contoh():
    assert identifier_only_in_example(NEXUS_MD, {"doc-fee-2026"})


def test_payload_dalam_blok_berpagar_terdeteksi_contoh():
    teks = "```\n" + NEXUS_API + "\n```"
    assert identifier_only_in_example(teks, {"doc-fee-2026"})


def test_baris_tabel_requirement_bukan_contoh():
    """Item nyata tidak boleh ikut tertandai — ini yang paling berbahaya kalau salah."""
    assert text_mentions_identifier(FR_ROW, {"fr-11"})
    assert not identifier_only_in_example(FR_ROW, {"fr-11"})


def test_identifier_bergaya_kode_bukan_contoh():
    """
    Dokumen kadang mencetak ID-nya monospace. Backtick saja TIDAK boleh
    dianggap contoh — isinya harus berstruktur (ada ":" atau "{").
    """
    teks = "Requirement `FR-01` mensyaratkan akurasi retrieval minimum 92%."
    assert not identifier_only_in_example(teks, {"fr-01"})


def test_disebut_di_prosa_dan_di_contoh_bukan_contoh_saja():
    """Satu kemunculan di luar cuplikan sudah cukup membuatnya nyata."""
    teks = "DOC-FEE-2026 terdaftar di inventaris dokumen.\n\n" + NEXUS_API
    assert not identifier_only_in_example(teks, {"doc-fee-2026"})


def test_identifier_tidak_muncul_bukan_urusan_fungsi_ini():
    """Ketiadaan ditangani text_mentions_identifier, bukan di sini."""
    assert not identifier_only_in_example(FR_ROW, {"fr-14"})
    assert not identifier_only_in_example("", {"fr-14"})


def test_tanpa_identifier_selalu_false():
    assert not identifier_only_in_example(NEXUS_API, set())


def test_aturan_prompt_hanya_muncul_saat_dibutuhkan():
    from app.llm.router import build_prompt
    chunks = [{"text": NEXUS_API}]
    tanpa = build_prompt("jelaskan DOC-FEE-2026", chunks, None, session_has_document=True)
    dengan = build_prompt("jelaskan DOC-FEE-2026", chunks, None, session_has_document=True,
                          identifier_in_example=["DOC-FEE-2026"])
    assert "EXAMPLE, NOT A REAL RECORD" not in tanpa
    assert "EXAMPLE, NOT A REAL RECORD" in dengan
    assert "DOC-FEE-2026" in dengan


def test_aturan_bahasa_tetap_paling_akhir():
    """
    Posisi LANGUAGE_RULE di ujung adalah yang memperbaiki bug bahasa; aturan
    baru tidak boleh menggesernya.
    """
    from app.llm.router import build_prompt
    p = build_prompt("jelaskan DOC-FEE-2026", [{"text": NEXUS_API}], None,
                     session_has_document=True, identifier_in_example=["DOC-FEE-2026"])
    assert p.index("IMPORTANT — LANGUAGE") > p.index("EXAMPLE, NOT A REAL RECORD")
    assert p.rstrip().endswith("YOUR RESPONSE:")
