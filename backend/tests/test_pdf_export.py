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
