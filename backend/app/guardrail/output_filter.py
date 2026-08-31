"""Guardrail AFTER LLM (F2-04) — cek jawaban AI sebelum ditampilkan, kategori mengikuti SRS FCR-003 content restriction."""
import re

_RESTRICTED_PATTERNS: dict[str, list[re.Pattern]] = {
    "saran_hukum": [
        re.compile(r"secara hukum,? (anda|kamu) (bisa|dapat|berhak)", re.I),
        re.compile(r"menurut (pasal|undang-undang|uu) (no\.?|nomor)?\s*\d*", re.I),
        re.compile(r"sebagai (nasihat|saran) hukum", re.I),
        re.compile(r"anda (dapat|bisa) (menuntut|melaporkan|menggugat)", re.I),
        re.compile(r"as legal advice", re.I),
        re.compile(r"under (the )?law,? you (can|may|are entitled)", re.I),
    ],
    "saran_medis": [
        re.compile(r"(minum|konsumsi) obat \w+ (setiap|tiap)", re.I),
        re.compile(r"dosis (yang )?(dianjurkan|disarankan|tepat)", re.I),
        re.compile(r"diagnosis (anda|kamu) adalah", re.I),
        re.compile(r"anda (menderita|mengidap|terkena)", re.I),
        re.compile(r"as medical advice", re.I),
        re.compile(r"recommended dosage", re.I),
        re.compile(r"you (have|are diagnosed with)", re.I),
    ],
    "saran_finansial_spesifik": [
        re.compile(r"(beli|jual) saham \w+ sekarang", re.I),
        re.compile(r"investasikan (uang|dana) (anda|kamu) (di|pada|ke)", re.I),
        re.compile(r"(pasti|dijamin) (untung|profit)", re.I),
        re.compile(r"guaranteed (profit|return)", re.I),
    ],
    "sara_diskriminasi": [
        re.compile(r"(ras|suku|agama) \w+ (lebih|paling) (rendah|buruk|jahat)", re.I),
        re.compile(r"(orang|kaum) \w+ (memang|selalu) (bodoh|jahat|buruk)", re.I),
    ],
    "instruksi_ilegal": [
        re.compile(r"cara (membuat|merakit) (bom|senjata|bahan peledak)", re.I),
        re.compile(r"cara (meretas|hack) (akun|sistem|jaringan) (orang lain|tanpa izin)", re.I),
        re.compile(r"how to (make|build) (a bomb|explosive|weapon)", re.I),
        re.compile(r"how to hack (into|someone)", re.I),
    ],
    "self_harm_guidance": [
        re.compile(r"cara (mengakhiri hidup|bunuh diri)", re.I),
        re.compile(r"cara (menyakiti|melukai) diri", re.I),
        re.compile(r"how to (end your life|kill yourself|self-harm)", re.I),
    ],
    "konten_seksual_eksplisit": [
        re.compile(r"deskripsi (adegan|konten) seksual eksplisit", re.I),
        re.compile(r"explicit sexual (content|description)", re.I),
    ],
}

STANDARD_REFUSAL_MESSAGE = (
    "Maaf, saya tidak dapat memberikan informasi terkait hal tersebut. "
    "Untuk kebutuhan spesifik, silakan konsultasikan dengan pihak/profesional yang berwenang."
)

SELF_HARM_REDIRECT_MESSAGE = (
    "Saya tidak dapat membantu dengan permintaan ini. Jika Anda atau seseorang yang Anda kenal "
    "sedang mengalami masa sulit, silakan hubungi layanan dukungan seperti "
    "Kementerian Kesehatan RI di 119 ext. 8, atau tenaga profesional terdekat."
)


def check_output_restricted(text: str) -> str | None:
    """Kembalikan nama kategori kalau jawaban AI terdeteksi masuk kategori terlarang, atau None kalau aman."""
    lowered = text.lower()
    for category, patterns in _RESTRICTED_PATTERNS.items():
        if any(p.search(lowered) for p in patterns):
            return category
    return None


def get_refusal_message(category: str) -> str:
    """Pilih pesan penolakan yang sesuai — self-harm dapat pesan khusus dengan arahan bantuan."""
    if category == "self_harm_guidance":
        return SELF_HARM_REDIRECT_MESSAGE
    return STANDARD_REFUSAL_MESSAGE
