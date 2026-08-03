"""
[PENANGGUNG JAWAB: Anggota B]
Guardrail sederhana untuk Tingkat 1 — filter kata terlarang berbasis daftar kata.
(Versi Tingkat 2 nanti ditingkatkan dengan deteksi PII & prompt injection.)
"""

BLOCKED_KEYWORDS = [
    # TODO: sesuaikan daftar ini sesuai kebijakan tim
    "bom", "senjata ilegal", "narkoba",
]


def is_prompt_blocked(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in BLOCKED_KEYWORDS)
