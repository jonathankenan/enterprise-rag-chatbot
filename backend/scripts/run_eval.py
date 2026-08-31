"""
Jalankan eval set Project NEXUS terhadap satu atau beberapa model on-prem.

    cd backend
    python -m scripts.run_eval                          # model dari .env
    python -m scripts.run_eval qwen2.5:7b qwen3:4b      # bandingkan
    python -m scripts.run_eval qwen3:4b --think         # aktifkan thinking mode
    python -m scripts.run_eval --runs 3                 # 3x per soal, lapor konsistensi

Prasyarat: Project_NEXUS_Business_Requirements_Document.pdf sudah pernah
diunggah lewat UI (script mencari chat_id yang punya chunk-nya di Chroma).

Yang diuji SPESIFIK: kualitas jawaban model atas konteks yang sudah diambil.
Query rewriting SENGAJA dilewati -- tiap soal memakai search_query bahasa
Inggris yang tetap, kira-kira seperti keluaran get_standalone_query(). Kalau
rewriting ikut dijalankan, hasilnya jadi campuran dua variabel dan tidak bisa
dipakai membandingkan model.

Jawaban acuan diambil verbatim dari PDF-nya (lihat catatan vault "Project
NEXUS RAG Test Fixture"). Pemeriksa sengaja LONGGAR soal kalimat dan KETAT
soal angka: yang dinilai apakah faktanya benar, bukan gaya bahasanya.
"""
import argparse
import asyncio
import re
import sys
from collections import Counter

import httpx

from app.config import settings
from app.llm.router import build_prompt
from app.rag.vectorstore import (
    retrieve_context, extract_query_identifiers, get_collection,
)


def _norm(text: str) -> str:
    """
    Rekatkan pemisah DI DALAM angka lalu turunkan ke huruf kecil, supaya satu
    pola bisa mencocokkan semua penulisan yang sah:
        "98.5"  "98,5"  ->  "985"
        "1,200" "1.200" "1 200" -> "1200"

    Versi pertama fungsi ini mengubah [\\s,.] jadi spasi -- justru MEMBUANG
    pemisah yang dicari polanya, jadi tiap jawaban berkoma desimal (penulisan
    normal bahasa Indonesia) dihitung salah. Lima dari 22 soal gagal karena
    ini, bukan karena modelnya keliru.

    Perbaikan itu sendiri lalu melahirkan bug kedua: desimal nol ikut
    direkatkan, jadi "$35.00" berubah jadi "3500" dan pola \\b35\\b tidak
    pernah cocok. Nilai mata uang di Project NEXUS memang ditulis lengkap
    dengan sennya. Jadi ".00"/",0" di ujung angka dibuang LEBIH DULU:

        "$35.00" -> "35"      "45.0"  -> "45"
        "1.000"  -> "1000"    (nol ribuan TIDAK ikut terbuang)
    """
    t = re.sub(r"(?<=\d)[.,]0{1,2}\b", "", text.lower())
    t = re.sub(r"(?<=\d)[.,\s](?=\d)", "", t)
    return re.sub(r"\s+", " ", t)


def _has(*terms):
    """Semua term harus muncul pada teks yang sudah dinormalkan."""
    def check(r):
        n = _norm(r)
        return all(re.search(t, n) for t in terms)
    return check


def _refuses(*forbidden):
    """
    Menolak menjawab, dan tidak menyebut nilai terlarang apa pun.

    Daftar "deny" harus longgar terhadap PILIHAN KATA. Versi pertama memakai
    tidak (ada|ter\\w+|men\\w+|di\\w+) dan meleset pada "tidak MEMILIKI
    informasi" -- penolakan yang benar-benar sah -- karena awalan "mem-"
    tidak ada di daftar. Penolakan qwen2.5:7b di B1 dihitung salah gara-gara
    itu.
    """
    deny = r"(tidak (ada|ter\w+|men\w+|mem\w+|di\w+)|belum|bukan|no such|does not|not (found|available|specif|contain))"
    def check(r):
        n = _norm(r)
        if any(re.search(f, n) for f in forbidden):
            return False
        return bool(re.search(deny, n))
    return check


# (id, kategori, pertanyaan user, search_query, pemeriksa)
CASES = [
    # --- A. angka eksak ---
    ("A1", "angka", "berapa akurasi retrieval minimum yang harus dicapai modul RAG?",
     "Requirement FR-01 retrieval accuracy", _has(r"\b92\b", r"mrr")),
    ("A2", "angka", "berapa overdraft fee consumer checking dan berapa cap hariannya?",
     "Requirement FR-03 overdraft fee consumer checking", _has(r"\b35\b", r"\b105\b")),
    ("A3", "angka", "berapa target TTFT dan batas maksimumnya?",
     "Requirement NFR-PERF-01 time to first token", _has(r"\b600\b", r"\b1200\b")),
    ("A4", "angka", "berapa chunk size dan overlap di kebijakan ingestion?",
     "document chunking strategy chunk size overlap tokens", _has(r"\b512\b", r"\b64\b")),
    ("A5", "angka", "berapa parameter M dan efConstruction pada index HNSW?",
     "Milvus HNSW index M efConstruction parameters", _has(r"\b16\b", r"\b200\b")),
    ("A6", "angka", "berapa threshold Faithfulness dan Context Precision?",
     "RAG test validation faithfulness context precision threshold", _has(r"\b985\b", r"\b900\b")),

    # --- B. item tidak ada -> harus menolak ---
    ("B1", "tolak", "jelaskan req ID FR-14",
     "Requirement FR-14 specifics", _refuses(r"fr-14 (adalah|mengacu|mengenai)")),
    ("B2", "tolak", "apa mitigasi untuk RSK-07?",
     "Risk RSK-07 mitigation strategy", _refuses(r"rsk-07 (adalah|mengacu|mengenai)")),
    ("B3", "tolak", "berapa target NFR-PERF-09?",
     "Requirement NFR-PERF-09 target threshold", _refuses(r"nfr-perf-09 (adalah|mengacu)")),
    ("B4", "tolak", "siapa document owner untuk DOC-FEE-2026?",
     "DOC-FEE-2026 document owner", _refuses(r"owner\w*\s*(nya)?\s*(adalah|is)\s+\w+")),

    # --- C. batas field ---
    ("C1", "field", "berapa prioritas NFR-PERF-03?",
     "Priority of NFR-PERF-03", _refuses(r"(must|should|could) have", r"prioritas\w*[^.]{0,30}\d")),
    ("C2", "field", "apa Impact dan Probability untuk RSK-02?",
     "Risk RSK-02 impact probability", _has(r"high")),
    ("C3", "field", "apa prioritas FR-11?",
     "Priority of Requirement FR-11", _has(r"could have")),

    # --- D. kondisional / caveat ---
    ("D1", "caveat", "apakah chatbot boleh mengeksekusi wire transfer?",
     "out of scope direct wire transfer execution", _has(r"\b1000\b", r"(tidak|not|portal)")),
    # Term dipisah supaya tidak menuntut kata benda tertentu menempel pada
    # angkanya. "two consecutive turns" punya banyak terjemahan yang sama
    # benarnya -- "dua putaran obrolan berurutan", "dua giliran berturut-turut"
    # -- dan versi pertama pemeriksa ini cuma menerima yang menempel langsung,
    # jadi kedua model dihitung salah padahal jawabannya persis benar.
    ("D2", "caveat", "kapan sistem menawarkan eskalasi ke supervisor manusia?",
     "Requirement FR-07 sentiment routing escalation",
     _has(r"\b085\b", r"\b(dua|two|2)\b", r"(berturut|berurutan|consecutive|turn|giliran|putaran)")),
    ("D3", "caveat", "berapa grace period kartu kredit?",
     "Requirement FR-10 credit card grace period", _has(r"\b21\b", r"(statement|penutupan|closing)")),
    ("D4", "caveat", "apa yang terjadi setelah 3 kali salah passcode?",
     "Requirement FR-08 account lockout rule failed passcode", _has(r"\b24\b", r"(cabang|branch)")),

    # --- E. sintesis multi-chunk ---
    ("E1", "sintesis", "bandingkan baseline dan target untuk FCR dan waktu tunggu chat",
     "quantitative baseline metrics first contact resolution customer wait time target",
     _has(r"\b48\b", r"\b78\b", r"\b45\b", r"(detik|second)")),
    ("E2", "sintesis", "sebutkan semua dokumen sumber beserta update frequency-nya",
     "document source inventory update frequency access level",
     _has(r"month", r"quarter", r"bi-?weekly", r"annual")),
    ("E3", "sintesis", "apa saja yang out-of-scope di Phase 1?",
     "out of scope capabilities phase 1 boundaries",
     _has(r"(loan|pinjaman)", r"(wire|transfer)", r"(voice|ivr|suara)", r"(third.?party|plaid|aggregat)")),

    # --- F. presisi, rawan dibulatkan ---
    ("F1", "presisi", "berapa target uptime SLA dan batas minimum yang diizinkan?",
     "Requirement NFR-PERF-04 system availability uptime SLA", _has(r"\b9995\b", r"\b9990\b")),
    ("F2", "presisi", "berapa similarity_threshold di contoh payload API retrieval?",
     "RAG context retrieval API sample payload similarity threshold", _has(r"\b078\b")),
]


def _find_chat_id() -> str:
    col = get_collection("kb_general")
    metas = col.get(include=["metadatas"]).get("metadatas") or []
    nexus = [m for m in metas if "NEXUS" in str(m.get("filename", ""))]
    if not nexus:
        sys.exit("Dokumen Project NEXUS belum terindeks. Unggah dulu lewat UI.")
    counts = Counter(m.get("chat_id") for m in nexus if m.get("chat_id"))
    # 39 chunk = satu dokumen utuh; kalau tidak ada, ambil chat dengan chunk terbanyak
    exact = [c for c, n in counts.items() if n == 39]
    return exact[0] if exact else counts.most_common(1)[0][0]


async def _generate(model: str, prompt: str, think: bool) -> str:
    body = {
        "model": model, "prompt": prompt, "stream": False,
        "options": {"num_ctx": settings.ollama_num_ctx,
                    "temperature": settings.ollama_temperature},
    }
    if think is not None:
        body["think"] = think
    async with httpx.AsyncClient(timeout=600.0) as c:
        r = await c.post(f"{settings.ollama_base_url}/api/generate", json=body)
        r.raise_for_status()
        return (r.json().get("response") or "").strip()


async def run_model(model: str, chat_id: str, runs: int, think) -> dict:
    print(f"\n{'='*78}\n  {model}" + (f"   think={think}" if think is not None else "") + f"\n{'='*78}")
    by_cat: dict[str, list[int]] = {}
    failures = []
    for cid, cat, question, sq, check in CASES:
        chunks, _conf = retrieve_context(sq, chat_id=chat_id, top_k=10)
        ids = extract_query_identifiers(sq)
        ctx = [c for c in chunks if c.get("id_match")] if ids else chunks
        prompt = build_prompt(question, ctx, None, session_has_document=True)

        hits, last_bad = 0, ""
        for _ in range(runs):
            reply = await _generate(model, prompt, think)
            # buang blok <think> supaya tidak ikut dinilai
            reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.S).strip()
            if check(reply):
                hits += 1
            else:
                last_bad = reply.replace("\n", " ")[:110]
        by_cat.setdefault(cat, []).append(hits)
        mark = "OK  " if hits == runs else ("~   " if hits else "FAIL")
        print(f"  {mark} {cid} [{cat:8}] {hits}/{runs}  {question[:52]}")
        if last_bad:
            failures.append((cid, last_bad))

    total = sum(sum(v) for v in by_cat.values())
    possible = len(CASES) * runs
    print(f"\n  ---- {model}: {total}/{possible} ({100*total/possible:.0f}%) ----")
    for cat, vals in by_cat.items():
        print(f"     {cat:9} {sum(vals)}/{len(vals)*runs}")
    if failures:
        print("\n  jawaban salah terakhir:")
        for cid, bad in failures:
            print(f"     {cid}: " + bad.encode("ascii", "replace").decode())
    return {"model": model, "score": total, "possible": possible}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", default=[])
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--chat-id", dest="chat_id", default=None,
                    help="Pakai chat_id tertentu, bukan hasil _find_chat_id(). "
                         "Dipakai untuk membandingkan dua strategi chunking "
                         "atas dokumen yang sama.")
    ap.add_argument("--think", dest="think", action="store_true", default=None)
    ap.add_argument("--no-think", dest="think", action="store_false")
    args = ap.parse_args()

    models = args.models or [settings.ollama_model]
    chat_id = args.chat_id or _find_chat_id()
    print(f"chat_id  : {chat_id}\nnum_ctx  : {settings.ollama_num_ctx}"
          f"\ntemp     : {settings.ollama_temperature}\nsoal     : {len(CASES)} x {args.runs} run")

    results = [await run_model(m, chat_id, args.runs, args.think) for m in models]

    if len(results) > 1:
        print(f"\n{'='*78}\n  RINGKASAN\n{'='*78}")
        for r in sorted(results, key=lambda x: -x["score"]):
            print(f"  {r['model']:22} {r['score']:3}/{r['possible']}  ({100*r['score']/r['possible']:.0f}%)")


if __name__ == "__main__":
    asyncio.run(main())
