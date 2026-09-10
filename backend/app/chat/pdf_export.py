import io
import jinja2
from markupsafe import Markup, escape  # dependensi jinja2 sendiri, bukan paket baru
from xhtml2pdf import pisa
from datetime import datetime

# 2026-09-09: xhtml2pdf's default font (Helvetica, a PDF base-14 font) renders
# a "missing glyph" box (■) for any character outside WinAnsi/Latin-1 --
# reported live as "SOP■01", "19.00■22.00". The model occasionally emits
# typographic Unicode punctuation (non-breaking hyphen U+2011, en dash
# U+2013, curly quotes) instead of their plain-ASCII equivalents, and none
# of that is under our control -- it comes out of the LLM's own token
# choices, so it will keep recurring with new characters over time.
#
# Tried switching to an embedded TTF instead (Bitstream Vera Sans, bundled
# with reportlab, so no extra download/asset to maintain): it covers en
# dash and curly quotes, but STILL lacks U+2011 specifically (confirmed via
# fontTools' cmap) -- the exact character in the reported bug. Chasing font
# coverage character-by-character is a losing game against whatever the
# model emits next.
#
# Fixed at the source instead: normalize known typographic punctuation to
# plain ASCII before the text ever reaches xhtml2pdf. Plain ASCII is
# guaranteed present in every font, so this closes the whole class of bug
# rather than one reported character at a time.
_PDF_SAFE_REPLACEMENTS = {
    "‐": "-",   # hyphen
    "‑": "-",   # non-breaking hyphen (the reported "SOP■01")
    "‒": "-",   # figure dash
    "–": "-",   # en dash (the reported "19.00■22.00")
    "—": "--",  # em dash
    "‘": "'",   # left single quotation mark
    "’": "'",   # right single quotation mark
    "“": '"',   # left double quotation mark
    "”": '"',   # right double quotation mark
    "…": "...", # horizontal ellipsis
    " ": " ",   # non-breaking space
}


def _pdf_safe(text: str) -> str:
    if not text:
        return text
    for src, dst in _PDF_SAFE_REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text


# 2026-09-10: export PDF tidak pernah mempertahankan baris baru dari jawaban
# model -- daftar berpoin dan blok kode mengalir jadi satu paragraf panjang.
# Dulu tersamar: sebelum autoescape dinyalakan, tag HTML dari model ikut
# terender dan kebetulan memberi struktur visual. Begitu tag itu (benar)
# dimatikan jadi teks, hilangnya newline langsung kelihatan.
#
# `white-space: pre-wrap` SUDAH DICOBA dan xhtml2pdf mengabaikannya total --
# diuji langsung, div ber-pre-wrap dan div biasa sama-sama meratakan newline
# jadi spasi. Jadi newline harus dijadikan <br/> sungguhan.
#
# URUTANNYA TIDAK BOLEH DIBALIK: escape() dulu supaya seluruh isi jawaban jadi
# teks mati, BARU <br/> disisipkan sebagai markup yang kita tahu aman. Kalau
# <br/> ditaruh duluan lalu di-escape, tag-nya ikut mati (tidak ada gunanya)
# DAN kita kembali menyuntikkan string mentah ke HTML -- persis lubang yang
# autoescape baru saja tutup.
def _content_markup(text: str) -> Markup:
    """Isi pesan siap-tempel: sudah ter-escape, newline-nya jadi <br/>."""
    if not text:
        return Markup("")
    return Markup(str(escape(text)).replace("\n", "<br/>"))


PDF_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <style>
        @page { size: A4; margin: 15mm; }
        body { font-family: sans-serif; font-size: 10pt; }
        .header { border-bottom: 2px solid #e2e8f0; margin-bottom: 20px; }
        .message { margin-bottom: 12px; }
        .user { text-align: right; color: #2b6cb0; }
        .assistant { text-align: left; color: #2d3748; background: #f7fafc; padding: 10px; border-radius: 6px; }

        /* Avoid splitting chat bubbles across two pages */
        .chat-bubble, .message-row, .message {
          page-break-inside: avoid !important;
        }

        /* Ensure code blocks and tables format cleanly */
        pre, table {
          page-break-inside: avoid !important;
          max-width: 100%;
          overflow-x: hidden;
        }
    </style>
</head>
<body>
    <div class="header">
        <h2>{{ session_title }}</h2>
        <p>Exported on: {{ export_date }} | Model: {{ model_used }}</p>
    </div>

    {% for msg in messages %}
        <div class="message {{ msg.role }}">
            <strong>{{ msg.role.capitalize() }}:</strong>
            <div>{{ msg.content }}</div>
        </div>
    {% endfor %}
</body>
</html>
"""

def generate_pdf(session_title: str, messages: list, model_used: str = "Various") -> bytes:
    # 2026-09-10: autoescape=True WAJIB di sini. jinja2.Template() default-nya
    # autoescape=False, jadi {{ msg.content }} menyuntikkan output LLM mentah
    # ke badan HTML. Terlihat langsung di transkrip nyata: user minta "kasih
    # kode html untuk website sederhana", model menjawab dengan <h1>/<p>, dan
    # di PDF hasilnya terender sebagai HEADING BETULAN, bukan sebagai teks
    # kode -- transkripnya jadi salah menggambarkan apa yang dijawab bot.
    #
    # Dua akibat lain yang lebih dari kosmetik:
    #   * tag tidak tertutup dari model bisa membuat pisa.CreatePDF() gagal ->
    #     tombol export melempar 500 di depan penonton demo.
    #   * isi dokumen KB ikut menyetir output model, dan output itu masuk ke
    #     PDF tanpa disaring -- jalur injeksi markup yang nyata, meski
    #     dampaknya kecil di PoC.
    #
    # Autoescape cuma menyaring substitusi {{ }}; markup PDF_TEMPLATE sendiri
    # tidak ikut ter-escape, jadi tata letaknya tidak berubah.
    template = jinja2.Template(PDF_TEMPLATE, autoescape=True)
    # Cuma isi pesan yang lewat _content_markup(): judul sesi dan nama model
    # selalu satu baris, jadi cukup di-escape otomatis oleh autoescape.
    safe_messages = [
        {**msg, "content": _content_markup(_pdf_safe(msg.get("content") or ""))}
        for msg in messages
    ]
    html_out = template.render(
        session_title=_pdf_safe(session_title),
        export_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        model_used=_pdf_safe(model_used),
        messages=safe_messages
    )

    # Convert HTML to PDF using xhtml2pdf
    pdf_file = io.BytesIO()
    pisa_status = pisa.CreatePDF(html_out, dest=pdf_file)

    if pisa_status.err:
        raise Exception("Error rendering PDF")

    return pdf_file.getvalue()
