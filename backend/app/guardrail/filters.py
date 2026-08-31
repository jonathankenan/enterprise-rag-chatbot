"""Guardrail dasar (F1-04) — filter kata/frasa terlarang berbasis regex per kategori, lapisan pertama sebelum F2-04 (prompt_injection.py, pii_detector.py, output_filter.py). Kategori mengikuti SRS hal. 15 poin 3.b/3.l."""
import re

BLOCKED_KEYWORDS: dict[str, list[str]] = {
    "kekerasan": [
        r"\bbom\b", r"senjata ilegal", r"rakit senjata", r"bahan peledak",
        r"\bbomb\b", r"\bexplosive\b", r"assault rifle", r"\bfirearms?\b",
        r"cara (membuat|merakit) (bom|senjata|bahan peledak)",
        r"cara (membunuh|menyiksa) (orang|manusia)",
        r"how to (make|build) (a bomb|explosive|weapon)",
        r"how to (kill|torture) (someone|a person)",
        r"\bterorisme\b", r"\bterrorism\b",
    ],
    "narkoba": [
        r"\bnarkoba\b", r"\bsabu\b", r"\bekstasi\b", r"cara membuat narkoba",
        r"\bganja\b", r"\bkokain\b", r"\bheroin\b", r"\bsabu-sabu\b",
        r"cara (membuat|meracik) (sabu|ekstasi|narkoba)",
        r"\bdrugs?\b", r"\bcocaine\b", r"\bmethamphetamine\b", r"\bheroin\b",
        r"how to (make|synthesize) (meth|drugs|cocaine)",
    ],
    "sara": [
        r"(ras|suku|agama)\s+\w+\s+(lebih|paling)\s+(rendah|buruk|jahat)",
        r"(orang|kaum)\s+\w+\s+(memang\s+)?(selalu\s+)?(bodoh|jahat|buruk)",
        r"(basmi|usir|enyahkan)\s+(semua\s+)?(orang|kaum|umat)\s+\w+",
        r"\bras\s+\w+\s+(inferior|unggul)\b",
        r"\b(race|ethnicity)\s+\w+\s+(is|are)\s+(inferior|superior)\b",
    ],
    "ujaran_kebencian": [
        r"ujaran kebencian", r"\bhate speech\b",
        r"(saya|kami)\s+benci\s+(semua\s+)?(orang|kaum|umat)\s+\w+",
        r"\b(i|we)\s+hate\s+all\s+\w+\s+(people)?\b",
        r"tulis(kan)?\s+(ujaran|kalimat)\s+kebencian\s+(terhadap|tentang)",
        r"write\s+(a\s+)?hateful\s+(message|statement)\s+about",
    ],
    "pornografi": [
        r"konten (pornografi|porno)", r"materi (pornografi|porno)",
        r"\bpornograph(y|ic)\b", r"explicit sexual content",
        r"(foto|video|gambar) (telanjang|bugil|porno)",
        r"deskripsi (adegan|konten) seksual eksplisit",
        r"(nude|naked) (photo|video|picture)s?\b",
        r"child (pornography|sexual)", r"\bcsam\b",
    ],
    "instruksi_ilegal_lainnya": [
        r"cara (meretas|hack) (akun|sistem|jaringan).{0,25}(orang lain|tanpa izin)",
        r"how to hack (into|someone)",
        r"cara (memalsukan|membuat palsu) (ktp|dokumen|identitas|ijazah|npwp)",
        r"how to forge (a )?(document|id|passport)",
        r"cara (melakukan )?phishing", r"buatkan (email|pesan) phishing",
        r"cara mencuri (identitas|kartu kredit) orang lain",
        r"how to steal (someone'?s )?(identity|credit card)",
    ],
    "self_harm": [
        r"cara bunuh diri", r"cara menyakiti diri", r"cara mengakhiri hidup",
        r"how to (kill myself|end my life|self-harm)",
        r"metode (bunuh diri|menyakiti diri) yang (efektif|tidak sakit)",
    ],
    "serangan_teknis": [
        # fokus ke framing niat jahat, bukan sekadar istilah teknis (aktor sistem termasuk divisi PTI/IT)
        r"\brm\s+-rf\s+/",
        r"buatkan (script|kode|program) (untuk )?(menghapus semua|memformat|merusak) (file|harddisk|sistem)",
        r"write (a script|code) to (delete all|wipe|destroy) (files|the system)",
        r"<script>.*</script>",
        r"\beval\(\s*(request|input)\b",
        r"\bDROP\s+TABLE\b.{0,20}--",
        r"\bUNION\s+SELECT\b.{0,20}(password|user)",
        r"\breverse shell\b", r"\bshell\s+injection\b",
        r"bypass (antivirus|edr|firewall)",
        r"buatkan (malware|virus|ransomware)", r"write (a )?(malware|virus|ransomware)",
    ],
}

_COMPILED: dict[str, list[re.Pattern]] = {
    category: [re.compile(pattern, re.I) for pattern in patterns]
    for category, patterns in BLOCKED_KEYWORDS.items()
}


def is_prompt_blocked(text: str) -> bool:
    """Cek apakah teks mengandung pola yang diblokir (case-insensitive, word-boundary aware)."""
    return any(p.search(text) for patterns in _COMPILED.values() for p in patterns)


def get_blocked_category(text: str) -> str | None:
    """Kembalikan nama kategori yang memicu blokir (untuk logging/audit), atau None kalau tidak ada yang cocok."""
    for category, patterns in _COMPILED.items():
        if any(p.search(text) for p in patterns):
            return category
    return None
