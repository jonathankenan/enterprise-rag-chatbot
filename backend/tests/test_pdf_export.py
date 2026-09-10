"""
Tests for chat PDF export (F2-08) — specifically the "■" glyph bug.

Reported live: exported PDFs showed "SOP■01" and "19.00■22.00" wherever the
model emitted typographic Unicode punctuation (non-breaking hyphen, en dash)
instead of plain ASCII. xhtml2pdf's default font has no glyph for these, and
neither does the best available embedded alternative (Bitstream Vera Sans,
bundled with reportlab — it covers en dash but not non-breaking hyphen). Fix
is a text-level sanitizer, not a font swap, so it's not testable by font
inspection — this needs to render an actual PDF and read back what character
ended up in it.

No Postgres, no Ollama, no API keys.
"""
import fitz  # PyMuPDF, already a project dependency (used for KB/document ingestion)

from app.chat.pdf_export import generate_pdf, _pdf_safe


def _extract_text(pdf_bytes: bytes) -> str:
    doc = fitz.Document(stream=pdf_bytes, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text


def test_pdf_safe_replaces_known_typographic_punctuation():
    assert _pdf_safe("SOP‑01") == "SOP-01"  # non-breaking hyphen — the reported bug
    assert _pdf_safe("19.00–22.00") == "19.00-22.00"  # en dash — the other reported bug
    assert _pdf_safe("kata—sisipan") == "kata--sisipan"  # em dash
    assert _pdf_safe("‘quoted’") == "'quoted'"
    assert _pdf_safe("“quoted”") == '"quoted"'
    assert _pdf_safe("wait…") == "wait..."
    assert _pdf_safe("non breaking") == "non breaking"


def test_pdf_safe_leaves_plain_ascii_untouched():
    plain = "SOP-01 berlaku 19.00-22.00 WIB, tanpa karakter aneh."
    assert _pdf_safe(plain) == plain


def test_pdf_safe_handles_empty_and_none():
    assert _pdf_safe("") == ""
    assert _pdf_safe(None) is None


def test_generated_pdf_does_not_contain_the_reported_characters():
    """End-to-end: render a real PDF with the exact reported input and read
    the text back out. Confirms the fix survives the whole Jinja ->
    xhtml2pdf pipeline, not just the sanitizer function in isolation."""
    messages = [
        {"role": "user", "content": "jelaskan SOP‑01"},
        {"role": "assistant", "content": "Rilis hanya boleh dijalankan pukul 19.00–22.00 WIB."},
    ]
    pdf_bytes = generate_pdf(session_title="Sesi Uji", messages=messages, model_used="on-prem")
    text = _extract_text(pdf_bytes)

    assert "‑" not in text, "non-breaking hyphen must not reach the PDF"
    assert "–" not in text, "en dash must not reach the PDF"
    assert "SOP-01" in text
    assert "19.00-22.00" in text


def test_generated_pdf_preserves_plain_ascii_content():
    messages = [{"role": "assistant", "content": "Jawaban biasa tanpa karakter khusus."}]
    pdf_bytes = generate_pdf(session_title="Sesi Biasa", messages=messages)
    text = _extract_text(pdf_bytes)
    assert "Jawaban biasa tanpa karakter khusus." in text


# ── 2026-09-10: output model tidak boleh dirender sebagai markup ──────────────
# Dilaporkan dari transkrip nyata: user minta "kasih kode html untuk website
# sederhana", model menjawab dengan <h1>/<p>, dan PDF-nya menampilkan HEADING
# BETULAN alih-alih teks kode -- transkrip jadi salah menggambarkan apa yang
# dijawab bot. Penyebabnya jinja2.Template() yang default-nya autoescape=False.


def test_model_html_appears_as_literal_text_not_rendered_markup():
    messages = [{
        "role": "assistant",
        "content": "<h1>Keindahan Indonesia</h1><p>Indonesia negara kepulauan.</p>",
    }]
    text = _extract_text(generate_pdf(session_title="Sesi HTML", messages=messages))

    # Tag harus terbaca apa adanya di transkrip. Kalau autoescape mati, tag-nya
    # dikonsumsi renderer dan yang tersisa cuma teks di dalamnya.
    assert "<h1>" in text
    assert "</p>" in text
    assert "Keindahan Indonesia" in text


def test_html_in_session_title_is_escaped_too():
    """Judul chat ikut di-generate model (auto-title), jadi jalurnya sama."""
    text = _extract_text(generate_pdf(
        session_title="<b>Judul</b>", messages=[{"role": "user", "content": "halo"}]))
    assert "<b>Judul</b>" in text


def test_newlines_in_the_answer_survive_into_the_pdf():
    """Daftar berpoin dulu mengalir jadi satu paragraf. `white-space: pre-wrap`
    tidak bisa dipakai -- xhtml2pdf mengabaikannya (diuji), jadi newline
    diubah jadi <br/> setelah escaping."""
    messages = [{"role": "assistant", "content":
                 "- REG-01: Keterbukaan Informasi\n- REG-02: Pencatatan Saham\n- REG-03: Tata Kelola AI"}]
    text = _extract_text(generate_pdf(session_title="Sesi Daftar", messages=messages))
    assert "- REG-01: Keterbukaan Informasi\n- REG-02: Pencatatan Saham" in text


def test_newline_handling_does_not_reopen_the_escaping_hole():
    """Penjaga urutan: escape() HARUS jalan sebelum <br/> disisipkan. Kalau
    dibalik, tag dari model hidup lagi dan autoescape jadi sia-sia."""
    messages = [{"role": "assistant", "content": "<h1>Judul</h1>\nbaris kedua"}]
    text = _extract_text(generate_pdf(session_title="Sesi Campur", messages=messages))
    assert "<h1>Judul</h1>" in text, "tag model harus tetap teks mati"
    assert "\nbaris kedua" in text, "newline harus tetap hidup"


def test_literal_br_from_the_model_is_not_turned_into_a_line_break():
    """Model kadang menulis <br> sebagai teks. Itu harus tampil apa adanya,
    bukan jadi baris baru -- bukti escaping mendahului penyisipan."""
    messages = [{"role": "assistant", "content": "Bursa Efek<br>Indonesia"}]
    assert "Bursa Efek<br>Indonesia" in _extract_text(
        generate_pdf(session_title="Sesi BR", messages=messages))


def test_none_content_does_not_render_the_word_none():
    assert "None" not in _extract_text(generate_pdf(
        session_title="Sesi Kosong", messages=[{"role": "assistant", "content": None}]))


def test_unclosed_tag_from_model_does_not_break_the_export():
    """Tag menggantung dulu bisa membuat pisa.CreatePDF() gagal -> tombol
    export melempar 500. Dengan escaping, itu cuma teks biasa."""
    messages = [{"role": "assistant", "content": "Contoh: <div><span>tanpa penutup"}]
    pdf_bytes = generate_pdf(session_title="Sesi Rusak", messages=messages)
    assert pdf_bytes[:4] == b"%PDF"
    assert "<div>" in _extract_text(pdf_bytes)
