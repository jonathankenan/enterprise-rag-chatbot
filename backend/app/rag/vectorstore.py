import hashlib
import re
import chromadb
from chromadb.utils import embedding_functions
import fitz
import pymupdf4llm
from langchain_text_splitters import MarkdownTextSplitter
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document as LCDocument
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever

from app.config import settings
from app.guardrail.intent_classifier import Intent

_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

_client = chromadb.PersistentClient(path=settings.chroma_persist_dir)


def get_collection(name: str = "kb_general"):
    return _client.get_or_create_collection(name=name, embedding_function=_embedding_fn)  # type: ignore


def _extract_pages_with_fallback(doc) -> list[dict]:
    """Ekstrak per-halaman (page_chunks=True, nomor halaman dari library) + fallback plain-text kalau markdown-nya kurang lengkap."""
    def _significant_words(text: str) -> set[str]:
        return {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", text)}

    COVERAGE_THRESHOLD = 0.80  # flag kalau markdown halaman cakup < 80% kata plain-text

    md_by_page: dict[int, str] = {}
    try:
        for entry in pymupdf4llm.to_markdown(doc=doc, page_chunks=True):
            pno = (entry.get("metadata") or {}).get("page")
            if pno is not None:
                md_by_page[int(pno)] = entry.get("text") or ""
    except Exception as e:
        print(f"pymupdf4llm per-page extraction failed, using plain text only: {e}")

    pages_out: list[dict] = []
    for page_num, page in enumerate(doc):
        page_no = page_num + 1
        page_text = md_by_page.get(page_no, "")
        plain_text = page.get_text()

        if plain_text.strip():
            page_words = _significant_words(plain_text)
            if page_words:
                covered = page_words & _significant_words(page_text)
                coverage = len(covered) / len(page_words)
                if coverage < COVERAGE_THRESHOLD:
                    clean = plain_text.strip()
                    page_text = (
                        page_text + f"\n\n<!-- plain-text fallback page {page_no}"
                        f" (pymupdf4llm coverage {coverage:.0%}) -->\n{clean}"
                    )

        pages_out.append({"page": page_no, "text": page_text})

    return pages_out


def extract_text_from_pdf(file_bytes) -> str:
    """Ekstrak PDF jadi 1 string flat — dipakai FAQ bulk-import yang tidak butuh atribusi halaman."""
    doc = fitz.Document(stream=file_bytes, filetype="pdf")
    pages = _extract_pages_with_fallback(doc)
    doc.close()
    return "\n\n-----\n\n".join(p["text"] for p in pages)


def extract_pages_from_pdf(file_bytes) -> list[dict]:
    """Sama seperti extract_text_from_pdf() tapi per halaman — dipakai upload dokumen/KB supaya tiap chunk bisa dikutip dengan nomor halaman."""
    doc = fitz.Document(stream=file_bytes, filetype="pdf")
    pages = _extract_pages_with_fallback(doc)
    doc.close()
    return pages




# ── Tabel: diindeks UTUH sekaligus PER BARIS ────────────────────────────────
# Satu baris tabel adalah satu record. Digabung jadi satu chunk bersama
# baris-baris lain, record-record itu berebut di dalam satu vektor dan model
# melihat tetangga yang nilainya bisa disalin -- akar kegagalan "NFR-PERF-03
# prioritasnya Must Have".
#
# Percobaan pertama (commit 6dbdc18, di-revert lewat 0313bae) memotong tabel
# HANYA per baris dan itu SALAH. Terukur pada perbandingan retrieval:
#
#     E1 "bandingkan baseline dan target FCR dan waktu tunggu"
#       tabel utuh   : 48% ADA   78% ADA   45 detik ADA   -> 3/3 fakta
#       hanya baris  : 48% ADA   78% ADA   45 detik HILANG -> 2/3 fakta
#
# Ketiga angka itu tinggal di BARIS BERBEDA dari satu tabel. Sebagai chunk
# utuh ketiganya datang bersama; dipecah, dua baris masuk top-10 dan baris
# ketiga kalah bersaing.
#
# Jadi keduanya diindeks. Yang memilih di antaranya adalah saringan
# identifier di chat/routes.py:
#
#   * Pertanyaan presisi menyebut identifier ("berapa prioritas NFR-PERF-03")
#     -> saringan aktif, ambil chunk BARIS, buang chunk tabel utuh. Tidak ada
#     baris tetangga yang bisa disalin.
#   * Pertanyaan sintesis tidak menyebut identifier ("bandingkan baseline dan
#     target") -> saringan TIDAK aktif sama sekali, chunk tabel utuh tetap
#     tersedia lengkap dengan seluruh barisnya.
#
# Yang terlewat waktu menolak ide ini sebelumnya: saringan identifier bisa
# MEMILIH di antara dua chunk, bukan cuma menyaring keluar.
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|(?:\s*:?-{2,}:?\s*\|)+\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")

# Tabel 2 kolom di Project NEXUS bukan tabel record, melainkan daftar definisi
# ("Endpoint URL:", "HTTP Method:", "Headers:"). Memotongnya per baris justru
# mencerai-beraikan satu spesifikasi jadi kepingan kunci-nilai.
TABLE_ROW_MIN_COLUMNS = 3
TABLE_ROW_MIN_ROWS = 2


def _table_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def table_header_of(text: str) -> str | None:
    """
    Baris header tabel markdown di chunk ini, atau None kalau bukan chunk
    tabel. Dipakai sebagai IDENTITAS tabel: semua chunk baris yang berasal
    dari tabel yang sama membawa baris header yang sama persis.
    """
    lines = text.split("\n")
    for i in range(len(lines) - 1):
        if (_TABLE_ROW_RE.match(lines[i]) and not _TABLE_SEP_RE.match(lines[i])
                and _TABLE_SEP_RE.match(lines[i + 1])):
            return lines[i].strip()
    return None


def count_table_body_rows(text: str) -> int:
    """
    Berapa baris ISI tabel markdown yang dimuat sebuah chunk (header dan garis
    pemisah tidak dihitung). Dipakai chat/routes.py untuk memilih chunk paling
    spesifik: 1 = chunk satu baris, >1 = chunk tabel utuh, 0 = prosa biasa.
    """
    lines = text.split("\n")
    body = 0
    for i, ln in enumerate(lines):
        if not _TABLE_ROW_RE.match(ln) or _TABLE_SEP_RE.match(ln):
            continue
        # baris tepat sebelum garis pemisah adalah header, bukan isi
        if i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
            continue
        body += 1
    return body


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """
    Pecah teks markdown jadi potongan-potongan kecil (chunk).

    Prosa lewat MarkdownTextSplitter seperti sebelumnya. Tabel markdown yang
    cukup lebar dan cukup panjang menghasilkan chunk GANDA: tabel utuh, plus
    satu chunk per baris. Lihat catatan di atas untuk alasannya.
    """
    splitter = MarkdownTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    lines = text.split("\n")
    chunks: list[str] = []
    buffer: list[str] = []
    heading = ""

    def flush_buffer():
        body = "\n".join(buffer).strip()
        buffer.clear()
        if body:
            chunks.extend(c for c in splitter.split_text(body) if c.strip())

    i = 0
    while i < len(lines):
        line = lines[i]
        is_table_head = (
            _TABLE_ROW_RE.match(line)
            and not _TABLE_SEP_RE.match(line)
            and i + 1 < len(lines)
            and _TABLE_SEP_RE.match(lines[i + 1])
        )
        if not is_table_head:
            if _HEADING_RE.match(line):
                heading = line.strip()
            elif line.strip():
                # Ada isi lain menyela: judul itu tidak lagi bisa dianggap
                # memperkenalkan tabel yang menyusul. Lihat catatan judul di bawah.
                heading = ""
            buffer.append(line)
            i += 1
            continue

        header, separator = line, lines[i + 1]
        j = i + 2
        body_rows = []
        while (j < len(lines) and _TABLE_ROW_RE.match(lines[j])
               and not _TABLE_SEP_RE.match(lines[j])):
            body_rows.append(lines[j])
            j += 1

        if (len(_table_cells(header)) < TABLE_ROW_MIN_COLUMNS
                or len(body_rows) < TABLE_ROW_MIN_ROWS):
            buffer.append(line)          # tabel kecil: biarkan mengalir apa adanya
            i += 1
            continue

        # JUDUL BAGIAN cuma ikut kalau LANGSUNG memperkenalkan tabelnya.
        # Aturan "judul terdekat sebelumnya" sempat dicoba dan SALAH:
        # pymupdf4llm mengeluarkan tabel NFR halaman 8 dua kali -- versi teks
        # polos di bawah judul aslinya "6.1 Performance & Latency SLAs", lalu
        # versi pipe-table SETELAH judul "6.2 Security, Privacy & Regulatory
        # Compliance", padahal isinya milik 6.1. Diukur pada Project NEXUS:
        # 3 dari 12 tabel langsung di bawah judulnya (ketiganya benar), 9
        # sisanya dipisah prosa atau tidak berjudul di halaman itu. Label
        # bagian yang SALAH lebih merugikan daripada tidak ada label.
        prefix = [heading] if heading else []
        flush_buffer()                    # prosa sebelum tabel diselesaikan dulu

        table = "\n".join([header.strip(), separator.strip()]
                          + [r.strip() for r in body_rows])
        chunks.append("\n\n".join(prefix + [table]))          # tabel utuh
        for row in body_rows:
            chunks.append("\n\n".join(
                prefix + ["\n".join([header.strip(), separator.strip(), row.strip()])]
            ))                                                 # satu baris

        heading = ""      # sudah terpakai; tabel berikutnya perlu judulnya sendiri
        i = j

    flush_buffer()
    return [c for c in chunks if c.strip()]


def index_document(pages: list[dict], doc_id: str, filename: str, chat_id: str, collection_name: str = "kb_general"):
    """Index dokumen chat, di-chunk PER HALAMAN supaya tiap chunk bisa dikutip dengan nomor halamannya."""
    collection = get_collection(collection_name)
    documents: list[str] = []
    metadatas: list[dict] = []
    for page_info in pages:
        for c in chunk_text(page_info["text"]):
            documents.append(c)
            meta = {"filename": filename, "doc_id": doc_id, "chunk_index": len(documents) - 1, "chat_id": chat_id}
            if page_info["page"] is not None:  # ChromaDB metadata tidak bisa nyimpen None
                meta["page"] = page_info["page"]
            metadatas.append(meta)

    ids = [f"{doc_id}_chunk_{i}" for i in range(len(documents))]
    collection.add(documents=documents, ids=ids, metadatas=metadatas)  # type: ignore
    return len(documents)


FAQ_COLLECTION_NAME = "kb_faq_helpdesk"


def index_faq_entry(faq_id: str, question: str, answer: str):
    """SRS poin 10.b — 1 FAQ = 1 chunk "Q: ...\\nA: ...", company-wide (tidak di-scope chat_id)."""
    collection = get_collection(FAQ_COLLECTION_NAME)
    collection.add(
        documents=[f"Q: {question}\nA: {answer}"],
        ids=[faq_id],
        metadatas=[{"faq_id": faq_id}],
    )


def delete_faq_entry_from_index(faq_id: str):
    collection = get_collection(FAQ_COLLECTION_NAME)
    collection.delete(ids=[faq_id])


KB_DIVISI_COLLECTION_NAME = "kb_divisi"
KB_COMPANY_WIDE_SENTINEL = "company_wide"  # ChromaDB metadata tidak bisa nyimpen None


def content_hash(file_bytes: bytes) -> str:
    """Sidik jari isi berkas, dipakai menolak unggahan ganda ke KB."""
    return hashlib.sha256(file_bytes).hexdigest()


def find_kb_duplicate(hash_isi: str, divisi: str | None) -> str | None:
    """
    doc_id dokumen yang isinya PERSIS SAMA dan berada di divisi yang sama,
    atau None kalau belum ada.

    2026-08-31: dokumen yang sama terindeks dua kali (sekali lewat UI, sekali
    lewat script uji) dan akibatnya tidak terlihat sama sekali dari luar --
    tidak ada error, tidak ada peringatan. Yang berubah cuma daya ambil:
    retrieval mengambil top_k=10, tapi karena tiap chunk punya kembaran, yang
    benar-benar sampai ke model CUMA 5 chunk berbeda. Baris "Jumlah pegawai
    tetap" ada di peringkat 5-6 dan persis terpotong di situ; pertanyaannya
    dijawab "tidak tersedia" padahal datanya ada.

    Dicek per DIVISI, bukan global: berkas yang sama sengaja diunggah ke dua
    divisi adalah hal yang sah (mis. kebijakan yang berlaku di keduanya), dan
    retrieval memang memisahkannya lewat filter divisi.
    """
    collection = get_collection(KB_DIVISI_COLLECTION_NAME)
    hasil = collection.get(
        where={"$and": [{"content_hash": hash_isi},
                        {"divisi": divisi or KB_COMPANY_WIDE_SENTINEL}]},
        include=["metadatas"], limit=1,
    )
    metas = hasil.get("metadatas") or []
    return metas[0].get("doc_id") if metas else None


def index_kb_document(pages: list[dict], doc_id: str, filename: str, divisi: str | None,
                      hash_isi: str | None = None) -> int:
    """Multi-Tenant KB (SRS poin 11) — divisi=None berarti Company Wide, chunk per halaman sama seperti index_document()."""
    collection = get_collection(KB_DIVISI_COLLECTION_NAME)
    divisi_tag = divisi or KB_COMPANY_WIDE_SENTINEL
    documents: list[str] = []
    metadatas: list[dict] = []
    for page_info in pages:
        for c in chunk_text(page_info["text"]):
            documents.append(c)
            meta = {"doc_id": doc_id, "filename": filename, "chunk_index": len(documents) - 1, "divisi": divisi_tag}
            # Disimpan di metadata Chroma, bukan kolom Postgres, supaya
            # pemeriksaan duplikat tidak butuh perubahan skema -- dan karena
            # yang benar-benar rusak akibat duplikat memang indeksnya.
            if hash_isi:
                meta["content_hash"] = hash_isi
            if page_info["page"] is not None:
                meta["page"] = page_info["page"]
            metadatas.append(meta)

    ids = [f"{doc_id}_chunk_{i}" for i in range(len(documents))]
    collection.add(documents=documents, ids=ids, metadatas=metadatas)  # type: ignore
    return len(documents)


def delete_kb_document_from_index(doc_id: str):
    collection = get_collection(KB_DIVISI_COLLECTION_NAME)
    collection.delete(where={"doc_id": doc_id})


class KbDivisiRetriever(BaseRetriever):
    """SRS hal. 14 — filter divisi di level query ChromaDB, dokumen divisi lain tidak pernah sampai ke LLM."""
    allowed_divisi: list[str]
    top_k: int = 5

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[LCDocument]:
        collection = get_collection(KB_DIVISI_COLLECTION_NAME)
        if collection.count() == 0:
            return []
        results = collection.query(
            query_texts=[query],
            n_results=min(self.top_k, collection.count()),
            where={"divisi": {"$in": self.allowed_divisi}},
            include=["documents", "metadatas", "distances"],
        )
        docs = results.get("documents")
        metas = results.get("metadatas")
        distances = results.get("distances")
        docs_list = docs[0] if docs else []
        metas_list = metas[0] if metas else []
        distances_list = distances[0] if distances else []

        out = []
        for d, m, dist in zip(docs_list, metas_list, distances_list):
            meta = dict(m or {})
            meta["_distance"] = dist
            out.append(LCDocument(page_content=d, metadata=meta))
        return out


class FaqChromaRetriever(BaseRetriever):
    """Sama seperti NativeChromaRetriever, tapi TANPA filter chat_id — semua chat berhak menariknya."""
    top_k: int = 5

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[LCDocument]:
        collection = get_collection(FAQ_COLLECTION_NAME)
        if collection.count() == 0:
            return []
        results = collection.query(
            query_texts=[query],
            n_results=min(self.top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        docs = results.get("documents")
        metas = results.get("metadatas")
        distances = results.get("distances")
        docs_list = docs[0] if docs else []
        metas_list = metas[0] if metas else []
        distances_list = distances[0] if distances else []

        out = []
        for d, m, dist in zip(docs_list, metas_list, distances_list):
            meta = dict(m or {})
            meta["_distance"] = dist
            out.append(LCDocument(page_content=d, metadata=meta))
        return out


class NativeChromaRetriever(BaseRetriever):
    chat_id: str
    collection_name: str = "kb_general"
    top_k: int = 10

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[LCDocument]:
        collection = get_collection(self.collection_name)
        if collection.count() == 0:
            return []
        results = collection.query(
            query_texts=[query],
            n_results=min(self.top_k, collection.count()),
            where={"chat_id": self.chat_id},
            include=["documents", "metadatas", "distances"],
        )
        docs = results.get("documents")
        metas = results.get("metadatas")
        distances = results.get("distances")
        docs_list = docs[0] if docs else []
        metas_list = metas[0] if metas else []
        distances_list = distances[0] if distances else []

        out = []
        for d, m, dist in zip(docs_list, metas_list, distances_list):
            meta = dict(m or {})  # "_distance" dipakai belakangan buat hitung confidence tanpa query Chroma kedua
            meta["_distance"] = dist
            out.append(LCDocument(page_content=d, metadata=meta))
        return out


def custom_bm25_tokenizer(text: str) -> list[str]:
    # Lowercase + pertahankan identifier bertanda hubung utuh (mis. 'fr-10')
    return re.findall(r'\b[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*\b', text.lower())


# Identifier bergaya requirement: huruf, lalu bagian angka setelah tanda hubung.
# Cocok: fr-01, nfr-perf-01, rsk-02, doc-fee-2026. TIDAK cocok: 92, 600, 1.200.
#
# 2026-08-26: definisi awal saya "token apa pun yang mengandung angka" SALAH --
# pertanyaan seperti "berapa akurasi 92 persen" akan memperlakukan "92" sebagai
# identifier, lalu menyaring sitasi (dan kini konteks) berdasarkan kehadiran
# string "92". Bukan itu maksudnya. Yang dituju cuma identifier item, karena
# identifier itulah satu-satunya hal yang bisa dicek keberadaannya secara
# deterministik terhadap korpus.
_IDENTIFIER_RE = re.compile(r"[a-z]{2,}(?:-[a-z]+)*-\d+(?:\.\d+)*")


def extract_query_identifiers(text: str) -> set[str]:
    """Identifier item yang disebut sebuah query, sudah lowercase."""
    return {t for t in custom_bm25_tokenizer(text) if _IDENTIFIER_RE.fullmatch(t)}


def text_mentions_identifier(text: str, identifiers: set[str]) -> bool:
    if not identifiers:
        return True
    return bool(identifiers & set(custom_bm25_tokenizer(text)))


# Kode divisi yang disebut BERDAMPINGAN dengan kata penunjuk divisi.
#
# 2026-08-31: filter divisi di KbDivisiRetriever bekerja benar -- dokumen
# divisi lain tidak pernah sampai ke prompt. Tapi baris tabel yang lolos
# filter TIDAK menyebut nama divisinya sendiri (mis. "Batas persetujuan
# anggaran Kepala Divisi | Rp250.000.000" -- tidak ada kata "PTI" di
# situ), dan build_prompt() cuma mengirim c["text"], tidak pernah
# filename/divisi. Ditanya "berapa batas anggaran divisi SDI" oleh user
# PTI, satu-satunya angka di konteks (milik PTI) ditempelkan ke nama SDI --
# bukan kebocoran data (SDI tidak pernah terambil), tapi pelabelan yang
# keliru dan meyakinkan.
#
# Disyaratkan berdampingan dengan "divisi/division/bagian/unit", BUKAN
# kemunculan token telanjang di mana pun: beberapa kode divisi bertabrakan
# dengan kata umum -- WAS ("was" dalam bahasa Inggris), PPT (format berkas
# PowerPoint), OTP (kode verifikasi 2FA). Token telanjang akan memblokir
# kalimat wajar seperti "kirim file PPT" atau "masukkan kode OTP".
#
# Trade-off yang diterima sadar: mention divisi TANPA kata penunjuk
# ("apa SLA SDI", tanpa kata "divisi") tidak tertangkap pola ini. Itu
# celah nyata, tapi false-refusal jauh lebih murah daripada false-answer
# di sini -- pola yang sama dipakai di seluruh penjagaan lain sesi ini.
_DIVISI_CONTEXT_WORDS = r"(?:divisi|division|bagian|unit)"


def extract_query_divisi(text: str, known_divisi: set[str]) -> set[str]:
    """Kode divisi (huruf besar, mis. {"PTI", "SDI"}) yang query ini sebut
    berdampingan dengan kata penunjuk divisi. known_divisi harus huruf besar."""
    found = set()
    for code in known_divisi:
        esc = re.escape(code)
        pat = rf"\b{_DIVISI_CONTEXT_WORDS}\s+{esc}\b|\b{esc}\s+{_DIVISI_CONTEXT_WORDS}\b"
        if re.search(pat, text, re.I):
            found.add(code.upper())
    return found


# Wilayah "contoh": blok kode berpagar, kode sebaris, dan pasangan
# "kunci": "nilai" bergaya JSON.
#
# Blok berpagar dan kode sebaris baru dihitung sebagai contoh kalau ISINYA
# berstruktur (memuat ":" atau "{"). Syarat itu ada supaya dokumen yang
# kebetulan menulis identifiernya sebagai kode sebaris -- `FR-01` -- tidak
# ikut dianggap contoh. Yang dicari adalah identifier yang muncul sebagai
# DATA di dalam cuplikan, bukan identifier yang cuma dicetak monospace.
_FENCED_RE = re.compile(r"```.*?```", re.S)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_JSON_PAIR_RE = re.compile(r'"[\w.-]+"\s*:\s*"[^"]*"')


def _example_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for rx in (_FENCED_RE, _INLINE_CODE_RE):
        for m in rx.finditer(text):
            if ":" in m.group(0) or "{" in m.group(0):
                spans.append(m.span())
    for m in _JSON_PAIR_RE.finditer(text):
        spans.append(m.span())
    return spans


def identifier_only_in_example(text: str, identifiers: set[str]) -> bool:
    """
    True kalau SETIAP kemunculan identifier di teks ini berada di dalam
    cuplikan contoh (payload API, blok kode, JSON), bukan di prosa atau baris
    tabel yang membahasnya.

    2026-08-26. Ditanya "jelaskan DOC-FEE-2026", sistem menjawab seolah itu
    dokumen sungguhan -- lengkap dengan "skor 0.892 menunjukkan kesamaan
    tinggi antara kueri Anda dan dokumen ini". Padahal DOC-FEE-2026 di
    Project NEXUS cuma nama tempelan di dalam CONTOH respons API pada
    bagian 7.2:

        Expected Response: { "status": "success", "chunks": [{
          "doc_id": "DOC-FEE-2026", "text": "...", "score": 0.892 }] }

    Dokumen itu tidak ada; 0.892 angka mati yang diketik penulis dokumen.
    Model mengubah ilustrasi statis jadi pengukuran hidup atas kueri user.

    Saringan id_match tidak bisa menangkap ini -- dia menanyakan "apakah
    string ini muncul", dan jawabannya memang ya. Yang kurang adalah
    membedakan MUNCUL SEBAGAI APA. Hal ini juga terjadi di Groq, model yang
    jauh lebih besar dari model on-prem mana pun yang kita pakai, jadi
    menaikkan ukuran model bukan jawabannya.

    Kembalikan False kalau identifiernya tidak muncul sama sekali: "tidak
    ada" adalah urusan text_mentions_identifier, bukan fungsi ini.
    """
    if not identifiers:
        return False
    spans = _example_spans(text)
    lowered = text.lower()
    ketemu = False
    for ident in identifiers:
        for m in re.finditer(re.escape(ident), lowered):
            ketemu = True
            if not any(a <= m.start() < b for a, b in spans):
                return False   # ada kemunculan di luar contoh
    return ketemu


def get_bm25_retriever(chat_id: str, collection_name: str = "kb_general", top_k: int = 10):
    collection = get_collection(collection_name)
    if collection.count() == 0:
        return None
    results = collection.get(where={"chat_id": chat_id}, include=["documents", "metadatas"])
    docs = results.get("documents")
    metas = results.get("metadatas")

    docs_list = docs if docs else []
    metas_list = metas if metas else []

    lc_docs = [LCDocument(page_content=d, metadata=m or {}) for d, m in zip(docs_list, metas_list)]
    if not lc_docs:
        return None

    retriever = BM25Retriever.from_documents(
        documents=lc_docs,
        preprocess_func=custom_bm25_tokenizer
    )
    return retriever

def _distance_to_similarity_percent(distance: float) -> float:
    """Konversi L2-squared distance -> cosine similarity, valid karena embedding model menghasilkan vektor ternormalisasi."""
    return max(0.0, min(1.0, 1 - (distance / 2)))


_DEFAULT_WEIGHTS = (0.35, 0.2, 0.25)  # urutan tetap: (chroma_dokumen_chat, faq, kb_divisi); sisa 1.0 buat BM25
_WEIGHT_PROFILES = {
    Intent.DOCUMENT_QUERY: (0.55, 0.15, 0.15),  # nanya dokumen sendiri -> leg chroma dominan
    Intent.FAQ_LOOKUP: (0.15, 0.55, 0.15),      # pertanyaan umum -> leg FAQ dominan
    Intent.GENERAL_CHAT: (0.3, 0.25, 0.25),     # tidak jelas arahnya -> bobot rata
}
_BM25_SHARE = 0.3  # porsi tetap buat leg BM25, tidak berubah oleh weight_hint


def _resolve_weights(weight_hint: str | None, has_bm25: bool) -> list[float]:
    """Skalakan bobot 3-leg dasar (menjaga rasio antar-leg) supaya BM25 selalu dapat porsi tetap kalau ada."""
    base = _WEIGHT_PROFILES.get(weight_hint, _DEFAULT_WEIGHTS)
    if not has_bm25:
        return list(base)
    total = sum(base)
    remaining = 1.0 - _BM25_SHARE
    scaled = [round(w / total * remaining, 4) for w in base]
    return scaled + [_BM25_SHARE]


# Berapa baris dari satu tabel harus muncul di hasil sebelum sisanya ikut
# ditarik. Satu baris saja BUKAN sinyal tabelnya relevan -- itu justru pola
# pertanyaan presisi, dan menariknya jadi seluruh tabel malah mengembalikan
# baris tetangga yang susah payah dibuang.
TABLE_EXPANSION_MIN_HITS = 2
# Pagar supaya tabel raksasa tidak menelan seluruh jendela konteks (dipotong
# di 15.000 karakter oleh build_prompt).
TABLE_EXPANSION_MAX_ROWS = 30


def _expand_table_rows(docs: list, chat_id: str, collection_name: str) -> list:
    """Lengkapi baris tabel yang sudah terwakili di hasil. Lihat pemanggilnya."""
    from collections import defaultdict

    hits: dict[str, int] = defaultdict(int)
    for d in docs:
        if count_table_body_rows(d.page_content) == 1:
            header = table_header_of(d.page_content)
            if header:
                hits[header] += 1
    wanted = {h for h, n in hits.items() if n >= TABLE_EXPANSION_MIN_HITS}
    if not wanted:
        return docs

    collection = get_collection(collection_name)
    stored = collection.get(where={"chat_id": chat_id}, include=["documents", "metadatas"])
    seen = {d.page_content for d in docs}
    extra = []
    for text, meta in zip(stored.get("documents") or [], stored.get("metadatas") or []):
        if text in seen or count_table_body_rows(text) != 1:
            continue
        header = table_header_of(text)
        if header not in wanted or hits[header] >= TABLE_EXPANSION_MAX_ROWS:
            continue
        hits[header] += 1
        # Sengaja TANPA "_distance": baris ini tidak lolos pencarian, dia
        # ditarik karena tabelnya relevan. Membubuhkan skor palsu akan
        # mencemari confidence dan pemilihan citation.
        extra.append(LCDocument(page_content=text, metadata=dict(meta or {})))
    return docs + extra


def retrieve_context(
    search_query: str, chat_id: str, collection_name: str = "kb_general", top_k: int = 10,
    user_divisi: str | None = None, weight_hint: str | None = None,
) -> tuple[list[dict], int | None]:
    """Ensemble retrieval (dokumen chat + FAQ + KB divisi + BM25 opsional), bobot disesuaikan weight_hint, confidence dari top-match saja."""
    chroma_retriever = NativeChromaRetriever(chat_id=chat_id, collection_name=collection_name, top_k=top_k)
    faq_retriever = FaqChromaRetriever(top_k=top_k)
    allowed_divisi = [KB_COMPANY_WIDE_SENTINEL] + ([user_divisi] if user_divisi else [])
    kb_retriever = KbDivisiRetriever(allowed_divisi=allowed_divisi, top_k=top_k)
    bm25_retriever = get_bm25_retriever(chat_id=chat_id, collection_name=collection_name, top_k=top_k)

    retrievers = [chroma_retriever, faq_retriever, kb_retriever]
    weights = _resolve_weights(weight_hint, has_bm25=bm25_retriever is not None)
    if bm25_retriever:
        retrievers.append(bm25_retriever)

    ensemble = EnsembleRetriever(retrievers=retrievers, weights=weights)
    docs = ensemble.invoke(search_query)

    docs = docs[:top_k]

    # ── 2026-08-31: lengkapi baris tabel untuk pertanyaan sintesis ──────────
    # Ditanya "functional requirement", jawaban cuma memuat 5 dari 12 FR dan
    # menyajikannya seolah lengkap. Chunk tabel FR utuh ADA di indeks (12
    # baris, 2913 karakter) tapi tidak masuk 20 besar sama sekali.
    #
    # Penyebabnya bukan peringkat, melainkan batas model embedding:
    # all-MiniLM-L6-v2 punya max_seq_length 256 token (~1.024 karakter). Chunk
    # 2.913 karakter DIPOTONG -- dua pertiga isinya tidak pernah ikut
    # membentuk vektornya, dan sisanya jadi rata-rata 12 topik sehingga tumpul
    # untuk kueri pendek. Sementara 12 chunk satu-baris masing-masing pendek,
    # fokus, dan semuanya memuat header yang sama, jadi mereka menyapu bersih
    # peringkat atas. Menaikkan top_k TIDAK menolong: chunk utuhnya tidak
    # pernah masuk peringkat berapa pun.
    #
    # Jadi kelengkapan tidak bisa digantungkan pada chunk raksasa. Yang dipakai
    # adalah sinyal yang sudah ada: kalau beberapa baris dari tabel yang SAMA
    # ikut terambil, tabel itu jelas relevan -- sisanya tinggal dilengkapi
    # secara deterministik.
    #
    # Aturannya jadi simetris dengan penjagaan identifier di chat/routes.py:
    #   kueri menyebut identifier  -> SATU baris   (yang paling spesifik)
    #   kueri sintesis             -> SEMUA baris  (yang paling lengkap)
    #
    # Batasan yang diketahui: cuma melengkapi dari dokumen chat ini
    # (kb_general + chat_id). Tabel di KB divisi belum ikut.
    if not extract_query_identifiers(search_query):
        docs = _expand_table_rows(docs, chat_id, collection_name)

    # Distance cuma ada di dokumen leg vector (chat/FAQ/KB divisi) -- BM25 tidak punya angka yang sebanding
    distance_by_index = {i: d.metadata["_distance"] for i, d in enumerate(docs) if "_distance" in d.metadata}

    # Peringkat diambil dari urutan ensemble (RRF gabungan), bukan distance mentah -- supaya chunk yang cuma ditemukan BM25 tetap bisa terkutip
    TOP_MATCHES = 3
    ranked = list(range(min(TOP_MATCHES, len(docs))))

    # Relevance floor relatif ke peringkat 1 -- peringkat 2-3 cuma ikut terkutip kalau similarity-nya masih dekat dari peringkat 1
    CITATION_SIMILARITY_GAP = settings.citation_similarity_gap

    def _similarity(i):
        if i not in distance_by_index:
            return None
        return _distance_to_similarity_percent(distance_by_index[i]) * 100

    # ── 2026-08-26: saringan LEKSIKAL sebelum floor similarity ──────────────
    # Floor di bawah ternyata tidak pernah menyaring apa pun pada korpus satu
    # dokumen. Diukur langsung pada "Requirement FR-01 specifics" terhadap
    # Project_NEXUS (39 chunk): SELURUH top-10 membentang cuma 74.69%..66.59%
    # -- 8 poin -- sementara CITATION_SIMILARITY_GAP=15 menaruh floor di
    # 59.69%. Semua chunk lolos. Penyebabnya bukan angka gap-nya keliru, tapi
    # all-MiniLM-L6-v2 pada korpus yang seluruh isinya membahas proyek yang
    # sama memang menghasilkan pita similarity sempit -- ambang berbasis
    # SELISIH POIN tidak punya daya pisah di situ.
    #
    # Yang benar-benar diskriminatif untuk pertanyaan ber-identifier adalah
    # leksikal: chunk yang dikutip HARUS memuat identifier yang ditanyakan.
    # Dua kasus nyata yang ditutup aturan ini (dilaporkan 2026-08-26, citation
    # "FR-01" menyebut hal. 1, 3, 7):
    #   * hal. 1 = halaman sampul, tidak memuat "FR-01" sama sekali -- masuk
    #     lewat kemiripan topik umum, bukan karena membahas FR-01.
    #   * hal. 3 = Daftar Isi, memuat "FR-01" tapi cuma sebagai baris navigasi
    #     ("Detailed Functional Requirements (FR-01 to FR-15) ..... Page 6").
    #     Aturan identifier saja tidak cukup membuangnya, makanya _is_toc().
    #
    # Keduanya masuk lewat celah `sim is None` di bawah: chunk yang HANYA
    # ditemukan BM25 tidak punya "_distance", jadi dulu dikutip TANPA SYARAT
    # sekuat/selemah apa pun. BM25 sengaja diberi hak kutip (2026-08-25, chunk
    # hal. 7 yang benar cuma ketemu lewat kecocokan string eksak) -- hak itu
    # dipertahankan, tapi sekarang bersyarat.
    #
    # Query TANPA identifier (mis. "ringkas kebijakan biaya") tidak terkena:
    # query_ids kosong -> _has_query_id() selalu True -> perilaku lama utuh,
    # termasuk kasus sintesis multi-dokumen FR-12.
    query_ids = extract_query_identifiers(search_query)

    def _has_query_id(i):
        return text_mentions_identifier(docs[i].page_content, query_ids)

    def _is_toc(i):
        # Baris Daftar Isi dikenali dari dot leader ("Bab ......... Page 6").
        # Ambang 3 supaya tabel/teks biasa yang kebetulan punya satu elipsis
        # panjang tidak ikut terbuang.
        return len(re.findall(r"\.{4,}", docs[i].page_content)) >= 3

    best_indices: set[int] = set()
    if ranked:
        first = ranked[0]
        best_indices.add(first)
        reference = _similarity(first)
        if reference is None:
            reference = 100.0
        floor = reference - CITATION_SIMILARITY_GAP
        for i in ranked[1:]:
            if _is_toc(i) or not _has_query_id(i):
                continue
            sim = _similarity(i)
            if sim is None or sim >= floor:
                best_indices.add(i)

    # Confidence dihitung dari chunk yang BENAR-BENAR dikutip (best_indices), bukan semua top_k
    scored = [distance_by_index[i] for i in sorted(best_indices) if i in distance_by_index]
    if scored:
        similarities = [_distance_to_similarity_percent(dist) for dist in scored]
        confidence = round((sum(similarities) / len(similarities)) * 100)
    else:
        confidence = None  # tidak ada chunk terkutip yang punya distance -- lebih jujur kosong daripada angka menyesatkan

    # SRS poin 12.a: bawa metadata (filename/page/source_type) sampai ke ChatReplyResponse.sources, bukan cuma teksnya
    chunks = []
    for i, d in enumerate(docs):
        meta = d.metadata
        if "faq_id" in meta:
            source_type = "faq"
        elif "divisi" in meta:
            source_type = "kb_divisi"
        else:
            source_type = "chat_document"
        chunks.append({
            "text": d.page_content,
            "filename": meta.get("filename"),
            "chunk_index": meta.get("chunk_index"),
            "page": meta.get("page"),
            "source_type": source_type,
            "is_top_match": i in best_indices,
            # Apakah chunk ini benar-benar menyebut identifier yang ditanya.
            # True untuk SEMUA chunk kalau query memang tidak menyebut
            # identifier apa pun (query_ids kosong) -- lihat
            # text_mentions_identifier(). Dipakai chat/routes.py untuk dua hal
            # yang tidak bisa dipercayakan ke model kecil: menolak identifier
            # yang tidak ada di korpus, dan menjaga konteks tetap pada item
            # yang ditanya. Lihat komentar di sana.
            "id_match": text_mentions_identifier(d.page_content, query_ids),
            # Identifiernya ADA di chunk ini, tapi cuma sebagai data di dalam
            # cuplikan contoh -- lihat identifier_only_in_example().
            "id_in_example": identifier_only_in_example(d.page_content, query_ids),
            # Berapa baris isi tabel dimuat chunk ini: 1 = chunk satu baris,
            # >1 = chunk tabel utuh, 0 = prosa. Tabel diindeks dalam dua
            # bentuk (lihat chunk_text), dan angka inilah yang dipakai
            # chat/routes.py untuk memilih yang paling spesifik.
            "table_body_rows": count_table_body_rows(d.page_content),
        })
    return chunks, confidence

def has_session_document(chat_id: str, collection_name: str = "kb_general") -> bool:
    collection = get_collection(collection_name)
    if collection.count() == 0:
        return False
    results = collection.get(where={"chat_id": chat_id}, limit=1)
    ids = results.get("ids")
    return bool(ids and len(ids) > 0)

def get_all_session_chunks(chat_id: str, limit: int = 15, collection_name: str = "kb_general") -> list[dict]:
    collection = get_collection(collection_name)
    if collection.count() == 0:
        return []
    results = collection.get(where={"chat_id": chat_id}, limit=limit, include=["documents", "metadatas"])
    docs = results.get("documents")
    metas = results.get("metadatas")
    docs_list = docs if docs else []
    metas_list = metas if metas else []
    return [  # chat-scoped saja, selalu "chat_document"
        {
            "text": d, "filename": (m or {}).get("filename"), "chunk_index": (m or {}).get("chunk_index"),
            "page": (m or {}).get("page"), "source_type": "chat_document",
        }
        for d, m in zip(docs_list, metas_list)
    ]
