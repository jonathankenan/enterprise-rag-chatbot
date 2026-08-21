"""
[PENANGGUNG JAWAB: Anggota B]
Ekstrak pasangan tanya-jawab dari teks PDF supaya IT Admin bisa bulk-import
FAQ (upload 1 file, banyak entri langsung dibuat) — dibanding harus ketik
manual satu-satu lewat form di admin/faq/page.jsx.

Dua strategi, dicoba berurutan (fallback bertingkat, bukan pilih salah satu
secara acak — strategi 1 lebih presisi, jadi selalu dicoba duluan):

1. Format eksplisit "Q: .../A: ..." atau "Pertanyaan: .../Jawaban: ..."
   (case-insensitive) — paling presisi karena penandanya jelas.
2. Fallback heuristik: baris yang diakhiri "?" dianggap pertanyaan, semua
   teks sampai baris "?" berikutnya dianggap jawabannya. Dipakai kalau
   strategi 1 tidak menemukan apa-apa (PDF-nya tidak diformat pakai
   penanda Q:/A: eksplisit, tapi masih berbentuk daftar tanya-jawab wajar).
"""
import re

_QA_MARKER_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:Q|Pertanyaan)\s*[:.]\s*(.+?)\s*\n+\s*(?:A|Jawaban)\s*[:.]\s*(.+?)"
    r"(?=\n\s*(?:Q|Pertanyaan)\s*[:.]|\Z)",
    re.IGNORECASE | re.DOTALL,
)

_QUESTION_LINE_PATTERN = re.compile(r"^(.+\?)\s*$", re.MULTILINE)


def _clean(text: str) -> str:
    # Buang penanda batas halaman yang disisipkan extract_text_from_pdf()
    # (markdown page-break dari pymupdf4llm, format "-----") — kalau tidak
    # dibuang, dia ikut ke-tangkap sebagai bagian jawaban TERAKHIR di tiap
    # dokumen (capture group regex di atas berhenti di "Q:" berikutnya ATAU
    # akhir teks, dan penanda ini selalu muncul di akhir teks).
    text = re.sub(r"-{3,}", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_faq_pairs(text: str) -> list[tuple[str, str]]:
    """Kembalikan list (question, answer). List kosong kalau tidak ada pola yang cocok sama sekali."""
    pairs = [
        (_clean(q), _clean(a))
        for q, a in _QA_MARKER_PATTERN.findall(text)
        if _clean(q) and _clean(a)
    ]
    if pairs:
        return pairs

    # ---------- Fallback: heuristik baris tanya-tanda-tanya ----------
    matches = list(_QUESTION_LINE_PATTERN.finditer(text))
    for i, m in enumerate(matches):
        question = _clean(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        answer = _clean(text[start:end])
        if question and answer:
            pairs.append((question, answer))
    return pairs
