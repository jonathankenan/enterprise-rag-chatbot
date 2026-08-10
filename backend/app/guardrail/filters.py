"""
[PENANGGUNG JAWAB: Anggota B]
Guardrail dasar (F1-04) — filter kata/frasa terlarang berbasis regex,
dikelompokkan per kategori. Ini lapisan pertama (paling murah/cepat)
sebelum guardrail lanjutan (F2-04: prompt_injection.py, pii_detector.py,
output_filter.py).

Kategori berikut disusun mengikuti daftar Content Restriction di SRS
FCR-003 (hal. 15), poin 3.b — "Pemblokiran terhadap": SARA, ujaran
kebencian, pornografi, kekerasan, ilegal instruction & prompt injection
(prompt injection sendiri ditangani terpisah di prompt_injection.py), dan
self-harm guidance. Ditambah kategori "serangan_teknis" untuk menutup
poin 3.l — "Pembatasan pada file yang di upload atau prompt yang di
sampaikan berisikan code execute".

Catatan desain (pasca-audit):
- Token pendek (mis. "sabu", "bom") WAJIB pakai \\b...\\b (word boundary).
  Tanpa ini, dulu ada bug substring match: "sabu" ikut cocok pada kata
  "sabun" yang sama sekali tidak berhubungan, sehingga kalimat sesantai
  "rekomendasi sabun cuci" ikut diblokir sebagai konten narkoba.
- Ditambahkan padanan Bahasa Inggris di semua kategori — prompt user
  tidak selalu Indonesia.
- Kategori "sara" dan "ujaran_kebencian" DIPISAH (sebelumnya digabung
  jadi satu "sara_kebencian" yang isinya cuma frasa META "ujaran
  kebencian" itu sendiri, bukan pola konten kebencian sesungguhnya).
  Untuk daftar kata makian/slur eksplisit per suku/ras/agama, KAMI TIDAK
  menaruhnya langsung sebagai literal di source code ini — selain
  berisiko duplikat/tidak lengkap, menyimpan daftar slur di plaintext
  source control juga berisiko disalahgunakan (mis. di-scrape balik
  sebagai "daftar kata kasar siap pakai"). Praktik produksi yang lebih
  baik: daftar tersebut disimpan terpisah (mis. file konfigurasi yang
  di-load runtime, bukan di-commit ke git) dan dikurasi oleh tim
  trust-and-safety. Di sini kita fokus pada POLA KALIMAT diskriminatif
  yang bisa dideteksi tanpa daftar kata kasar eksplisit.
- Kategori "pornografi" diperluas tapi tetap menghindari kata yang
  berisiko tinggi ambigu dengan idiom (mis. "telanjang kaki" = idiom
  "tanpa alas kaki"), makanya beberapa istilah sengaja dipasangkan
  dengan kata benda media (foto/video/konten) supaya lebih presisi.
- Kategori "instruksi_ilegal_lainnya" menampung permintaan instruksi
  ilegal di luar senjata/narkoba: peretasan, phishing, pemalsuan
  dokumen/identitas, penipuan/scam terstruktur.

Ini tetap pendekatan keyword statis — secara inheren rawan false-negative
(sinonim/parafrase yang belum terdaftar tetap lolos) dan bisa saja masih
punya false-positive pada kasus tepi lain yang belum ditemukan. Ini bukan
lapisan pertahanan satu-satunya, makanya ada F2-04 di belakangnya.
"""
import re

# Daftar pola per kategori. Semua pola dianggap regex (case-insensitive),
# pakai \b untuk token pendek supaya tidak nyangkut di tengah kata lain.
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
        # SRS 3.l: pembatasan pada file/prompt yang berisi code execute
        # atau upaya serangan teknis. SENGAJA tidak menandai penyebutan
        # API/perintah semata (mis. "subprocess.run(" atau "os.system(")
        # karena aktor sistem ini termasuk divisi PTI (IT) yang wajar
        # bertanya soal kode sungguhan — pola di bawah fokus ke FRAMING
        # niat jahat/perusakan, bukan sekadar istilah teknis.
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
    """
    Kembalikan nama kategori yang memicu blokir (untuk keperluan logging/audit),
    atau None kalau tidak ada yang cocok.
    """
    for category, patterns in _COMPILED.items():
        if any(p.search(text) for p in patterns):
            return category
    return None