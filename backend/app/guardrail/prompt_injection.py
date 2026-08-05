"""
[PENANGGUNG JAWAB: Anggota B]
Deteksi prompt injection sederhana — bagian dari F2-04.
Mendeteksi pola umum percobaan "membajak" instruksi sistem AI,
baik dalam Bahasa Indonesia maupun Inggris.
"""
import re

INJECTION_PATTERNS = [
    r"abaikan (semua )?instruksi (sebelumnya|di atas)",
    r"lupakan (semua )?(instruksi|perintah|aturan) (sebelumnya|sistem)",
    r"kamu (sekarang )?(berperan sebagai|adalah)",
    r"ignore (all )?(previous|prior|above) instructions",
    r"disregard (all )?(previous|prior|above) (instructions|rules)",
    r"you are now",
    r"pretend (you are|to be)",
    r"act as (if )?(you|a)",
    r"system prompt",
    r"developer mode",
    r"jailbreak",
    r"bypass (your |the )?(rules|restrictions|guardrail)",
    r"reveal (your |the )?(system prompt|instructions)",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def is_prompt_injection(text: str) -> bool:
    """Cek apakah teks mengandung pola umum percobaan prompt injection."""
    return any(pattern.search(text) for pattern in _COMPILED_PATTERNS)