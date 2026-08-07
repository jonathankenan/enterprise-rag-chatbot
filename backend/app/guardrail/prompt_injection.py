"""
[PENANGGUNG JAWAB: Anggota B]
Deteksi prompt injection (F2-04) — pendekatan multi-sinyal berbasis skor.
Mencakup: instruction override, role-play hijacking, jailbreak framework
terkenal, ekstraksi system prompt, framing hipotetis, dan klaim otoritas palsu.
"""
import re

_INJECTION_SIGNALS: list[tuple[re.Pattern, int]] = [
    # --- Kategori 1: Instruction Override (paling umum) ---
    (re.compile(r"abaikan (semua )?(instruksi|perintah|aturan)", re.I), 3),
    (re.compile(r"lupakan (semua )?(instruksi|perintah|aturan)(\s+(sebelumnya|sistem|di atas))?", re.I), 3),
    (re.compile(r"tidak (perlu|usah) (ikuti|patuhi) (instruksi|aturan)", re.I), 3),
    (re.compile(r"ignore (all |any )?(previous|prior|above|earlier) instructions", re.I), 3),
    (re.compile(r"disregard (all |any )?(previous|prior|above|earlier)", re.I), 3),
    (re.compile(r"forget (all |any )?(your |the )?(instructions|rules|guidelines)", re.I), 3),
    (re.compile(r"override (your |the |previous )?(instructions|programming|rules)", re.I), 3),
    (re.compile(r"new instructions?:?\s", re.I), 2),

    # --- Kategori 2: Role-play / Persona Hijacking ---
    (re.compile(r"kamu (sekarang )?(berperan sebagai|adalah|menjadi)\s+\w+", re.I), 2),
    (re.compile(r"anggap (dirimu|kamu) (sebagai|adalah)", re.I), 2),
    (re.compile(r"mulai sekarang,?\s*(kamu|anda)", re.I), 2),
    (re.compile(r"you are now\s+\w+", re.I), 2),
    (re.compile(r"pretend (you are|to be|that you)", re.I), 2),
    (re.compile(r"act as (if )?(you|a|an)\s+\w+", re.I), 2),
    (re.compile(r"roleplay as", re.I), 2),
    (re.compile(r"from now on,?\s*you", re.I), 2),
    (re.compile(r"simulate (being|a|an)", re.I), 2),

    # --- Kategori 3: Jailbreak Framework Terkenal ---
    (re.compile(r"\bDAN\b.{0,30}(mode|prompt|jailbreak)", re.I), 4),
    (re.compile(r"do anything now", re.I), 4),
    (re.compile(r"\b(STAN|DUDE|AIM|JailBreak)\b.{0,20}(mode|prompt)", re.I), 4),
    (re.compile(r"developer mode", re.I), 3),
    (re.compile(r"jailbreak", re.I), 3),
    (re.compile(r"god mode", re.I), 3),
    (re.compile(r"unlock(ed)? mode", re.I), 2),
    (re.compile(r"evil (twin|version|mode)", re.I), 3),
    (re.compile(r"opposite (day|mode)", re.I), 2),

    # --- Kategori 4: Ekstraksi System Prompt ---
    (re.compile(r"system prompt", re.I), 2),
    (re.compile(r"reveal (your |the )?(system prompt|instructions|guidelines)", re.I), 3),
    (re.compile(r"tunjukkan (instruksi|prompt) (sistem|awal|asli)", re.I), 3),
    (re.compile(r"apa (instruksi|prompt) (sistem|awal) (kamu|anda)", re.I), 3),
    (re.compile(r"repeat (the )?(text|words|instructions) (above|before)", re.I), 2),
    (re.compile(r"what (were|was) you told", re.I), 2),
    (re.compile(r"print (your |the )?(initial|original) (prompt|instructions)", re.I), 3),

    # --- Kategori 5: Klaim Otoritas / Bypass Palsu ---
    (re.compile(r"sebagai (admin|developer|pengembang|pemilik sistem)", re.I), 2),
    (re.compile(r"as (an? )?(admin|developer|system owner)", re.I), 2),
    (re.compile(r"override code:?\s*\w+", re.I), 3),
    (re.compile(r"bypass (your |the )?(rules|restrictions|guardrail|filter)", re.I), 3),
    (re.compile(r"tanpa (batasan|filter|sensor|restriksi)", re.I), 2),
    (re.compile(r"no restrictions?|unfiltered|uncensored", re.I), 2),
    (re.compile(r"disable (your |the )?(safety|filter|guardrail)", re.I), 3),

    # --- Kategori 6: Framing Hipotetis untuk Menghindari Aturan ---
    (re.compile(r"(dalam|pada) (skenario|dunia) hipotetis", re.I), 1),
    (re.compile(r"in a hypothetical (world|scenario)", re.I), 1),
    (re.compile(r"for (a )?fictional (story|purpose)", re.I), 1),
    (re.compile(r"hanya (untuk|sebagai) (fiksi|cerita|hipotesis)", re.I), 1),
    (re.compile(r"this is just a (test|simulation|hypothetical)", re.I), 1),

    # --- Kategori 7: Percobaan Encoding/Obfuscation ---
    (re.compile(r"decode (this )?base64", re.I), 2),
    (re.compile(r"terjemahkan dari (base64|hex|rot13)", re.I), 2),
    (re.compile(r"respond (only )?in (base64|hex|binary)", re.I), 2),
]

INJECTION_SCORE_THRESHOLD = 3


def get_injection_score(text: str) -> int:
    """Hitung total skor kecurigaan berdasarkan semua pola yang cocok."""
    return sum(weight for pattern, weight in _INJECTION_SIGNALS if pattern.search(text))


def get_matched_signals(text: str) -> list[str]:
    """Kembalikan daftar pola (dalam bentuk teks) yang cocok — untuk keperluan audit log."""
    return [pattern.pattern for pattern, _ in _INJECTION_SIGNALS if pattern.search(text)]


def is_prompt_injection(text: str) -> bool:
    return get_injection_score(text) >= INJECTION_SCORE_THRESHOLD