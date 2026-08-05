"""
[PENANGGUNG JAWAB: Anggota B]
Guardrail dasar (F1-04) — filter kata terlarang berbasis daftar kata (regex sederhana).
Ini lapisan pertama sebelum prompt diproses lebih lanjut oleh guardrail lanjutan (F2-04).
"""
import re

# Daftar kata/frasa yang diblokir sepenuhnya — dikelompokkan per kategori
# supaya mudah ditelusuri dan ditambah tanpa mengacaukan daftar yang sudah ada.
BLOCKED_KEYWORDS = {
    "kekerasan_senjata": [
        "bom", "senjata ilegal", "rakit senjata", "bahan peledak",
    ],
    "narkoba": [
        "narkoba", "sabu", "ekstasi", "cara membuat narkoba",
    ],
    "sara_kebencian": [
        "ujaran kebencian",
    ],
    "self_harm": [
        "cara bunuh diri", "cara menyakiti diri",
    ],
}


def _flatten_keywords() -> list[str]:
    return [kw for group in BLOCKED_KEYWORDS.values() for kw in group]


_ALL_KEYWORDS = _flatten_keywords()


def is_prompt_blocked(text: str) -> bool:
    """
    Cek apakah teks mengandung kata/frasa yang diblokir.
    Pencarian case-insensitive dan menangani variasi spasi sederhana.
    """
    lowered = text.lower()
    return any(keyword in lowered for keyword in _ALL_KEYWORDS)


def get_blocked_category(text: str) -> str | None:
    """
    Kembalikan nama kategori yang memicu blokir (untuk keperluan logging/audit),
    atau None kalau tidak ada yang cocok.
    """
    lowered = text.lower()
    for category, keywords in BLOCKED_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return category
    return None