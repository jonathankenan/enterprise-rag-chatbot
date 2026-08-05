"""
[PENANGGUNG JAWAB: Anggota B]
Deteksi PII (Personally Identifiable Information) — bagian dari F2-04.
Pendekatan berbasis regex untuk pola data pribadi umum di Indonesia,
bukan NLP model besar — lebih ringan dan cukup akurat untuk pola terstruktur.
"""
import re

# Setiap pola dipasangkan dengan nama kategorinya, untuk keperluan logging/audit
PII_PATTERNS = {
    "NIK/KTP": re.compile(r"\b\d{16}\b"),
    "NPWP": re.compile(r"\b\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3}\b|\b\d{15}\b"),
    "Kartu Kredit": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "Nomor Telepon": re.compile(r"\b(?:\+62|62|0)8\d{8,11}\b"),
    "Email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
}


def detect_pii_types(text: str) -> list[str]:
    """
    Kembalikan daftar KATEGORI PII yang terdeteksi dalam teks
    (bisa lebih dari satu kategori sekaligus).
    """
    found = []
    for category, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            found.append(category)
    return found


def contains_pii(text: str) -> bool:
    """Cek cepat: apakah teks mengandung PII apa pun."""
    return len(detect_pii_types(text)) > 0