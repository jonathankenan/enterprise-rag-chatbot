"""Ekstrak pasangan tanya-jawab dari teks PDF buat bulk-import FAQ — strategi Q:/A: eksplisit dicoba dulu, baru fallback heuristik "?"."""
import re

_QA_MARKER_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:Q|Pertanyaan)\s*[:.]\s*(.+?)\s*\n+\s*(?:A|Jawaban)\s*[:.]\s*(.+?)"
    r"(?=\n\s*(?:Q|Pertanyaan)\s*[:.]|\Z)",
    re.IGNORECASE | re.DOTALL,
)

_QUESTION_LINE_PATTERN = re.compile(r"^(.+\?)\s*$", re.MULTILINE)


def _clean(text: str) -> str:
    # Buang penanda batas halaman "-----" dari extract_text_from_pdf(), kalau tidak dibuang ikut ke-tangkap sebagai bagian jawaban terakhir
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

    # Fallback: heuristik baris tanya-tanda-tanya
    matches = list(_QUESTION_LINE_PATTERN.finditer(text))
    for i, m in enumerate(matches):
        question = _clean(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        answer = _clean(text[start:end])
        if question and answer:
            pairs.append((question, answer))
    return pairs
