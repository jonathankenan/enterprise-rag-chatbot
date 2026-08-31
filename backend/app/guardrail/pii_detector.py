"""Deteksi & masking PII (F2-04) — Microsoft Presidio + recognizer kustom untuk pola data identitas Indonesia."""
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_analyzer.nlp_engine import NlpEngineProvider

_nlp_config = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
}
_nlp_engine = NlpEngineProvider(nlp_configuration=_nlp_config).create_engine()
_analyzer = AnalyzerEngine(nlp_engine=_nlp_engine)

# PERSON sengaja tidak dimasukkan ke _TARGET_ENTITIES -- model NLP Inggris sering salah kira istilah Indonesia sebagai nama orang

_analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="ID_NIK",
    patterns=[Pattern(name="nik", regex=r"\b\d{16}\b", score=0.75)],
    context=["nik", "ktp", "identitas"],
))

# ID_KK sengaja dihapus -- regex-nya identik NIK (16 digit) dan skornya selalu kalah, jadi dead code (pasca-audit)

_analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="ID_NPWP",
    patterns=[
        Pattern(name="npwp_formatted", regex=r"\b\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3}\b", score=0.9),
        Pattern(name="npwp_plain", regex=r"\b\d{15,16}\b", score=0.3),
    ],
    context=["npwp", "pajak", "wajib pajak"],
))

_analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="ID_PHONE",
    patterns=[Pattern(name="id_phone", regex=r"\b(?:\+62|62|0)8\d{8,11}\b", score=0.8)],
))

_analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="ID_SIM",
    patterns=[Pattern(name="sim", regex=r"\b\d{12,14}\b", score=0.3)],
    context=["sim", "surat izin mengemudi"],
))

_analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="ID_PASPOR",
    patterns=[Pattern(name="paspor", regex=r"\b[A-Za-z]{1,2}\d{6,7}\b", score=0.55)],
    context=["paspor", "passport"],
))

_analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="ID_BPJS",
    patterns=[Pattern(name="bpjs", regex=r"\b\d{13}\b", score=0.4)],
    context=["bpjs", "jaminan kesehatan", "jaminan sosial"],
))

_analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="ID_REKENING_BANK",
    patterns=[Pattern(name="rekening", regex=r"\b\d{9,16}\b", score=0.25)],
    context=["rekening", "no rek", "nomor rekening", "bank"],
))

_analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="ID_PLAT_KENDARAAN",
    patterns=[Pattern(
        name="plat_nomor",
        regex=r"\b[A-Z]{1,2}\s?\d{1,4}\s?[A-Z]{1,3}\b",
        score=0.6,
    )],
    context=["plat", "nomor polisi", "kendaraan"],
))

_analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="EMAIL_ADDRESS",
    patterns=[Pattern(
        name="email_custom_high_confidence",
        regex=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        score=0.95,
    )],
))

_TARGET_ENTITIES = [
    "ID_NIK", "ID_NPWP", "ID_PHONE", "ID_SIM", "ID_PASPOR",
    "ID_BPJS", "ID_REKENING_BANK", "ID_PLAT_KENDARAAN",
    "EMAIL_ADDRESS", "CREDIT_CARD", "PHONE_NUMBER", "IP_ADDRESS",
]


def _remove_overlaps(entities):
    """Kalau ada beberapa entitas yang tumpang tindih posisinya, ambil yang skornya tertinggi."""
    sorted_by_score = sorted(entities, key=lambda e: e.score, reverse=True)
    selected = []
    for e in sorted_by_score:
        overlap = any(not (e.end <= s.start or e.start >= s.end) for s in selected)
        if not overlap:
            selected.append(e)
    return selected


def detect_pii_entities(text: str) -> list[dict]:
    """Kembalikan daftar entitas PII terdeteksi (skor >= 0.5) — satu-satunya fungsi yang menjalankan Presidio langsung."""
    raw = _analyzer.analyze(text=text, language="en", entities=_TARGET_ENTITIES)
    clean = _remove_overlaps(raw)
    return [
        {"type": e.entity_type, "start": e.start, "end": e.end, "score": round(e.score, 2)}
        for e in clean
        if e.score >= 0.5
    ]


def mask_pii(text: str, entities: list[dict] | None = None) -> tuple[str, dict[str, str]]:
    """Ganti tiap PII dengan placeholder unik (mis. [ID_NIK_1]), kembalikan teks ter-mask + mapping placeholder->nilai asli."""
    if entities is None:
        entities = detect_pii_entities(text)

    counters: dict[str, int] = {}
    mapping: dict[str, str] = {}
    replacements = []

    for e in sorted(entities, key=lambda x: x["start"]):
        original_value = text[e["start"]:e["end"]]
        counters[e["type"]] = counters.get(e["type"], 0) + 1
        placeholder = f"[{e['type']}_{counters[e['type']]}]"
        mapping[placeholder] = original_value
        replacements.append((e["start"], e["end"], placeholder))

    masked_text = text  # ganti dari belakang ke depan supaya index karakter tidak bergeser
    for start, end, placeholder in sorted(replacements, key=lambda r: r[0], reverse=True):
        masked_text = masked_text[:start] + placeholder + masked_text[end:]

    return masked_text, mapping


def demask(text: str, mapping: dict[str, str]) -> str:
    """Kembalikan semua placeholder [TYPE_n] jadi nilai aslinya."""
    for placeholder, original_value in mapping.items():
        text = text.replace(placeholder, original_value)
    return text
