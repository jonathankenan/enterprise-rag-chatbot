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

_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

_client = chromadb.PersistentClient(path=settings.chroma_persist_dir)


def get_collection(name: str = "kb_general"):
    return _client.get_or_create_collection(name=name, embedding_function=_embedding_fn)  # type: ignore


def _extract_pages_with_fallback(doc) -> list[dict]:
    """
    Shared extraction core for extract_text_from_pdf() (flat string, used by
    the FAQ bulk-import path which just wants everything joined -- see
    faq/parser.py) and extract_pages_from_pdf() (per-page, used by
    index_document()/index_kb_document() so each chunk can be tagged with
    the PDF page it came from -- SRS FCR-003 poin 12.a: citations should
    name a page, not just a filename).

    Primary pass: pymupdf4llm.to_markdown(page_chunks=True) provides clean
    markdown formatting (especially for tables), which the MarkdownTextSplitter
    downstream handles well, AND returns one dict per page with
    metadata["page"] (1-indexed) already attached.

    Known issue (confirmed via diagnostic against Project NEXUS BRD, page 6):
    when a table is immediately followed by non-tabular text (bulleted lists,
    plain paragraphs) on the same PDF page, pymupdf4llm silently drops the
    post-table content. Root cause: the table bounding-box detection
    (table_strategy='lines_strict') swallows/overlaps the adjacent text
    region, so it never gets rendered into the markdown output. This affects
    any PDF with this common layout pattern, not just the test document.

    Safety-net pass: for each page we compare the markdown's significant-word
    set against that page's raw plain text from fitz. If a page's markdown
    covers less than COVERAGE_THRESHOLD of the plain-text words, we append the
    raw plain text as a fallback so the content reaches the index.

    Returns a list of {"page": int, "text": str}, one entry per PDF page IN
    ORDER. "page" comes from pymupdf4llm's own per-page metadata, cross-checked
    against fitz's page index, so it is always populated.

    ── 2026-08-25: why this no longer splits on '-----' ─────────────────────
    This used to call to_markdown() for the whole document and split the
    result on '\\n\\n-----\\n\\n' page-break separators, guarding the result with
    `len(md_segments) == len(doc)`. That was wrong in BOTH directions:

      * A normal PDF ends with a trailing separator, so the split produced
        page_count + 1 segments, the guard failed, and every page number was
        discarded (page=None for the whole document). Three of the four
        documents in the dev corpus had zero page citations for this reason.

      * A PDF whose first page yields no markdown (a scanned or image-only
        cover sheet) still got a separator for it, so the leading empty
        segment cancelled out the trailing one. len() then MATCHED
        page_count, the guard PASSED -- while every segment pointed one page
        ahead. Confirmed on Project NEXUS BRD: the FR-01..FR-12 table that
        really sits on page 7 was paired with page 8's markdown, and
        citations named pages 2/3/8 that never mention the requirement asked
        about. The coverage safety net hid this by firing on all 11 pages
        (0-32% coverage) -- it was comparing page N's plain text against page
        N+1's markdown, so of course they barely overlapped.

    The guard compared cardinality, not alignment, so it could not detect the
    second case even in principle. page_chunks=True removes the heuristic:
    page numbers come from the library instead of from list position.
    """
    def _significant_words(text: str) -> set[str]:
        """Lowercase alphabetic words longer than 3 chars (ignores numbers and
        short stop-words that create noise between plain-text and markdown)."""
        return {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", text)}

    COVERAGE_THRESHOLD = 0.80  # flag if page markdown covers < 80% of plain-text words

    # ── Primary pass: per-page markdown, page numbers from the library ──────
    # Keyed by page number from metadata rather than by list position, so a
    # page pymupdf4llm skips entirely cannot shift every page after it.
    md_by_page: dict[int, str] = {}
    try:
        for entry in pymupdf4llm.to_markdown(doc=doc, page_chunks=True):
            pno = (entry.get("metadata") or {}).get("page")
            if pno is not None:
                md_by_page[int(pno)] = entry.get("text") or ""
    except Exception as e:
        # Never fail the upload over markdown formatting. fitz's plain text
        # below is authoritative for page numbers regardless, so the worst
        # case is unformatted (but correctly attributed) text.
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
        # Blank/image-only page: keep its (likely empty) markdown as-is, still
        # numbered -- so later pages don't shift just because an earlier page
        # had nothing extractable. This is exactly the case the old '-----'
        # split got wrong.

        pages_out.append({"page": page_no, "text": page_text})

    return pages_out


def extract_text_from_pdf(file_bytes) -> str:
    """
    Extract PDF to a single flat text string. Used by the FAQ bulk-import
    path (faq/routes.py) which parses Q&A pairs out of the whole document
    and doesn't need per-page attribution -- see extract_pages_from_pdf()
    for the version chat-document/KB-divisi upload uses instead, which DOES
    keep page numbers (for source citations, SRS FCR-003 poin 12.a).
    """
    doc = fitz.Document(stream=file_bytes, filetype="pdf")
    pages = _extract_pages_with_fallback(doc)
    doc.close()
    return "\n\n-----\n\n".join(p["text"] for p in pages)


def extract_pages_from_pdf(file_bytes) -> list[dict]:
    """
    Same extraction as extract_text_from_pdf(), kept PER PAGE instead of
    joined into one string. Used by index_document()/index_kb_document() so
    every chunk can carry the PDF page number it came from. Side effect:
    chunking now happens per-page (chunk_text() is called once per page,
    not once for the whole flattened document), so a chunk can never span
    two different pages anymore -- which is also just more correct for RAG
    in general, not only for citations.
    """
    doc = fitz.Document(stream=file_bytes, filetype="pdf")
    pages = _extract_pages_with_fallback(doc)
    doc.close()
    return pages




def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """
    Pecah teks markdown jadi potongan-potongan kecil (chunk).
    Menggunakan MarkdownTextSplitter agar tidak merusak format markdown
    seperti tabel atau header.
    """
    splitter = MarkdownTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    chunks = splitter.split_text(text)
    return [c for c in chunks if c.strip()]


def index_document(pages: list[dict], doc_id: str, filename: str, chat_id: str, collection_name: str = "kb_general"):
    """
    pages: output of extract_pages_from_pdf() -- list of {"page": int|None, "text": str}.
    Chunked PER PAGE (not on the whole document joined together) so every
    chunk's metadata can carry the page it came from -- see "page" below,
    consumed by retrieve_context() -> chat/routes.py's _build_source_citations()
    for SRS FCR-003 poin 12.a (source references naming a page).
    """
    collection = get_collection(collection_name)
    documents: list[str] = []
    metadatas: list[dict] = []
    for page_info in pages:
        for c in chunk_text(page_info["text"]):
            documents.append(c)
            meta = {"filename": filename, "doc_id": doc_id, "chunk_index": len(documents) - 1, "chat_id": chat_id}
            # ChromaDB metadata tidak bisa nyimpen None (sama seperti alasan
            # KB_COMPANY_WIDE_SENTINEL di bawah untuk `divisi`) -- kalau
            # extract_pages_from_pdf() tidak bisa memetakan halaman dengan
            # aman (page_info["page"] is None), key "page" DIHILANGKAN sama
            # sekali daripada disimpan sebagai None, .get("page") di
            # retrieve_context() sudah aman kembalikan None untuk key yang absen.
            if page_info["page"] is not None:
                meta["page"] = page_info["page"]
            metadatas.append(meta)

    ids = [f"{doc_id}_chunk_{i}" for i in range(len(documents))]
    collection.add(documents=documents, ids=ids, metadatas=metadatas)  # type: ignore
    return len(documents)


FAQ_COLLECTION_NAME = "kb_faq_helpdesk"


def index_faq_entry(faq_id: str, question: str, answer: str):
    """
    SRS poin 10.b: FAQ helpdesk sebagai sumber RAG. Beda dari
    index_document() — SATU FAQ = SATU chunk (tidak dipecah chunk_text()),
    karena FAQ sudah pendek & atomik secara alami, dan digabung
    "Q: ...\\nA: ..." supaya embedding-nya menangkap makna pertanyaan DAN
    jawabannya sekaligus (bukan cuma jawaban tanpa konteks tanya apa).
    Tidak ada metadata "chat_id" — koleksi ini company-wide, ditarik ke
    SEMUA chat, bukan di-scope ke satu percakapan seperti kb_general.
    """
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
KB_COMPANY_WIDE_SENTINEL = "company_wide"  # ChromaDB metadata tidak bisa nyimpen None, jadi dipakai literal string ini


def index_kb_document(pages: list[dict], doc_id: str, filename: str, divisi: str | None) -> int:
    """
    Multi-Tenant Knowledge Base — SRS poin 11 & hal. 68. divisi=None berarti
    dokumen Company Wide (POJK/Peraturan BEI/SK, bisa ditarik SEMUA divisi).
    Beda dari index_faq_entry() (1 FAQ = 1 chunk pendek), dokumen KB divisi
    dipecah chunk_text() sama seperti index_document() biasa karena isinya
    dokumen kebijakan panjang, bukan tanya-jawab atomik.

    pages: output of extract_pages_from_pdf() -- lihat index_document() untuk
    alasan chunking per-halaman (bukan dokumen digabung dulu baru dipecah).
    """
    collection = get_collection(KB_DIVISI_COLLECTION_NAME)
    divisi_tag = divisi or KB_COMPANY_WIDE_SENTINEL
    documents: list[str] = []
    metadatas: list[dict] = []
    for page_info in pages:
        for c in chunk_text(page_info["text"]):
            documents.append(c)
            meta = {"doc_id": doc_id, "filename": filename, "chunk_index": len(documents) - 1, "divisi": divisi_tag}
            # See index_document() -- ChromaDB metadata can't store None.
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
    """
    SRS hal. 14, Rules poin 1: "Data yang di-upload oleh masing-masing
    divisi hanya dapat diakses oleh divisi tersebut" — retriever ini
    TIDAK PERNAH mengembalikan dokumen di luar allowed_divisi (divisi user
    sendiri + Company Wide), bukan cuma "diprioritaskan", betul-betul
    di-filter di level query ChromaDB (where clause), jadi dokumen divisi
    lain tidak pernah sekalipun sampai ke LLM sebagai context.
    """
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
            # "_distance" DISELIPKAN ke metadata, dipakai belakangan oleh
            # retrieve_context() untuk menghitung confidence — supaya tidak
            # perlu query Chroma kedua kali cuma buat ambil angka jarak yang
            # sebenarnya sudah didapat di query yang sama ini. Prefix "_"
            # penanda ini bukan metadata bisnis (bukan filename/doc_id/dst).
            meta = dict(m or {})
            meta["_distance"] = dist
            out.append(LCDocument(page_content=d, metadata=meta))
        return out


def custom_bm25_tokenizer(text: str) -> list[str]:
    # Lowercase and extract alphanumeric words AND hyphenated terms intact (e.g., 'fr-10', 'nfr-perf-01')
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
    """
    Konversi distance Chroma -> cosine similarity (0.0-1.0). Dasar konversi
    (dikonfirmasi EMPIRIS, bukan asumsi): koleksi ini pakai metrik default
    Chroma, L2 SQUARED distance (bukan cosine distance), tapi embedding
    model (all-MiniLM-L6-v2) menghasilkan vektor TERNORMALISASI (norm=1).
    Untuk vektor satuan berlaku identitas matematis:
        L2_squared = 2 - 2*cosine_similarity
        => cosine_similarity = 1 - (L2_squared / 2)
    """
    return max(0.0, min(1.0, 1 - (distance / 2)))


def retrieve_context(
    search_query: str, chat_id: str, collection_name: str = "kb_general", top_k: int = 10,
    user_divisi: str | None = None,
) -> tuple[list[dict], int | None]:
    """
    Kembalikan (potongan_teks, retrieval_confidence). Confidence 0-100
    dihitung dari distance yang didapat SEKALI di dalam NativeChromaRetriever
    di atas (via metadata["_distance"]) — TIDAK ada query Chroma kedua
    terpisah lagi cuma untuk menghitung skor (dulu ada fungsi
    compute_retrieval_confidence() sendiri yang query ulang; sekarang
    dihapus, digabung ke sini).

    Confidence cuma dihitung dari dokumen hasil LEG VECTOR (yang punya
    "_distance" di metadata — chat_id-scoped, FAQ, MAUPUN KB divisi, semua
    vector search) — dokumen dari leg BM25 (keyword match, dipakai kalau
    ensemble retrieval aktif) diabaikan untuk keperluan skor, karena BM25
    tidak punya angka yang sebanding dengan cosine similarity.

    SRS poin 10.b/11: FAQ helpdesk (company-wide) dan KB Multi-Tenant
    (Company Wide + divisi user_divisi SAJA — lihat KbDivisiRetriever)
    SELALU diikutsertakan sebagai leg RETRIEVAL tambahan, bukan cuma kalau
    chat itu sendiri tidak punya dokumen.

    Skor akhir = rata-rata similarity dari 3 chunk TERBAIK (distance
    terkecil) di antara semua kandidat leg vector, BUKAN rata-rata dari
    semua top_k=10 chunk yang diambil buat konteks LLM. Lihat komentar di
    dekat perhitungannya di bawah untuk alasannya.
    """
    chroma_retriever = NativeChromaRetriever(chat_id=chat_id, collection_name=collection_name, top_k=top_k)
    faq_retriever = FaqChromaRetriever(top_k=top_k)
    allowed_divisi = [KB_COMPANY_WIDE_SENTINEL] + ([user_divisi] if user_divisi else [])
    kb_retriever = KbDivisiRetriever(allowed_divisi=allowed_divisi, top_k=top_k)
    bm25_retriever = get_bm25_retriever(chat_id=chat_id, collection_name=collection_name, top_k=top_k)

    retrievers = [chroma_retriever, faq_retriever, kb_retriever]
    # Dokumen chat sendiri diberi bobot sedikit lebih tinggi — asumsinya
    # dokumen yang SENGAJA di-upload user ke chat ini lebih spesifik ke
    # kebutuhannya saat itu, dibanding FAQ/KB divisi yang lebih umum.
    weights = [0.35, 0.2, 0.25]
    if bm25_retriever:
        retrievers.append(bm25_retriever)
        weights = [0.3, 0.15, 0.25, 0.3]

    ensemble = EnsembleRetriever(retrievers=retrievers, weights=weights)
    docs = ensemble.invoke(search_query)

    docs = docs[:top_k]

    # index -> distance, cuma untuk doc yang punya "_distance" (leg vector --
    # chat-scoped/FAQ/KB divisi). Dokumen dari leg BM25 dibangun lewat
    # collection.get() di get_bm25_retriever(), yang tidak mengembalikan
    # distance sama sekali, jadi mereka TIDAK ada di dict ini.
    distance_by_index = {i: d.metadata["_distance"] for i, d in enumerate(docs) if "_distance" in d.metadata}

    # TOP_MATCHES (3) = berapa banyak chunk yang LAYAK DISEBUT sebagai sumber.
    # context_chunks TETAP lengkap sampai top_k -- LLM masih menerima konteks
    # penuh untuk menjawab (termasuk kasus FR-12 "multi-document synthesis"
    # yang memang butuh banyak chunk); yang dipersempit hanya bagian mana yang
    # dikutip. Ditambahkan 2026-08-24 setelah citation "FR-01" ikut menyebut
    # halaman-halaman yang cuma "di sekitar secara topik" dalam window top_k.
    #
    # ── 2026-08-25: dipilih berdasar PERINGKAT ENSEMBLE, bukan distance ─────
    # Sebelumnya best_indices diambil dari `distance_by_index` (3 distance
    # terkecil). Karena dict itu HANYA berisi dokumen leg vector, chunk yang
    # ditemukan HANYA oleh BM25 tidak akan pernah bisa dikutip -- padahal BM25
    # ada justru untuk menangkap identifier eksak ("FR-02", nomor part) yang
    # ranking embedding-nya jelek.
    #
    # Persis itu yang terjadi 2026-08-25: "jelaskan req ID FR-01" dijawab
    # BENAR dari chunk halaman 7 (ditemukan BM25 lewat kecocokan string
    # eksak), tapi citation-nya menyebut halaman 6 dan 9 -- dua tetangga topik
    # dari leg vector -- karena chunk halaman 7 tidak punya "_distance"
    # sehingga tidak pernah masuk best_indices. Jawabannya benar, sumbernya
    # salah total.
    #
    # EnsembleRetriever mengembalikan dokumen SUDAH terurut menurut skor RRF
    # gabungan kedua leg, jadi posisi 0..n ADALAH peringkat relevansi
    # gabungan, dan chunk BM25 bisa ikut bersaing. Kalau BM25 tidak tersedia,
    # docs datang langsung dari Chroma yang juga sudah terurut distance
    # menaik -- rumus posisi yang sama tetap benar untuk kedua jalur.
    TOP_MATCHES = 3
    ranked = list(range(min(TOP_MATCHES, len(docs))))

    # ── 2026-08-25: relevance FLOOR, relatif terhadap peringkat 1 ────────────
    # TOP_MATCHES sebelumnya jumlah TETAP: selalu mengutip 3 chunk, sekuat apa
    # pun peringkat 2 dan 3. Untuk "jelaskan req ID FR-01" -- yang jawabannya
    # ada di SATU chunk saja -- hasilnya "hal. 7, 9, 11": halaman 7 benar,
    # halaman 9 dan 11 cuma pengisi slot. Efek yang sama membuat confidence
    # bias turun: 1 chunk similarity 95% dirata-rata dengan 2 chunk 10%
    # menghasilkan 38%.
    #
    # Sekarang peringkat 1 SELALU dikutip, dan peringkat 2-3 hanya ikut kalau
    # similarity-nya masih dalam CITATION_SIMILARITY_GAP poin dari peringkat 1.
    # Ambangnya RELATIF, bukan absolut, jadi menyesuaikan sendiri: jawaban dari
    # satu kecocokan presisi menyisakan satu citation, sedangkan jawaban yang
    # memang tersebar di beberapa dokumen (kasus FR-12 "multi-document
    # synthesis") tetap mengutip semuanya karena skornya berdekatan. Tidak ada
    # angka absolut yang harus dikalibrasi ulang per korpus -- masalah yang
    # sudah dimiliki escalation_confidence_threshold.
    #
    # Chunk dari leg BM25 tidak punya similarity yang sebanding:
    #   * di peringkat 1 -> dianggap acuan tertinggi (reference 100%), karena
    #     BM25 menaruhnya di puncak justru pada query identifier eksak; efeknya
    #     peringkat 2-3 harus benar-benar kuat untuk ikut terkutip.
    #   * di peringkat 2-3 -> tetap dikutip. Tidak ada bukti dia lemah, dan dia
    #     sampai ke situ lewat peringkat RRF gabungan.
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

    # Confidence dihitung dari chunk yang BENAR-BENAR DIKUTIP -- "seberapa
    # yakin" dan "sumber mana yang disebut" merujuk ke bukti yang SAMA. Karena
    # floor di atas sudah membuang chunk pengisi, satu kecocokan presisi tidak
    # lagi ketarik turun oleh tetangga topik. Chunk BM25 yang terkutip dilewati
    # saat merata-rata: tetap dikutip, cuma tidak punya angka yang sebanding.
    scored = [distance_by_index[i] for i in sorted(best_indices) if i in distance_by_index]
    if scored:
        similarities = [_distance_to_similarity_percent(dist) for dist in scored]
        confidence = round((sum(similarities) / len(similarities)) * 100)
    else:
        # Tidak satupun chunk terkutip punya distance -- jawabannya bersandar
        # pada kecocokan kata kunci (BM25) yang tidak punya skala sebanding
        # dengan cosine similarity. Lebih jujur mengosongkan skor daripada
        # menampilkan angka dari chunk yang TIDAK dikutip. chat/routes.py sudah
        # menjaga None ini sebelum membandingkan ke ambang eskalasi, dan
        # chat/page.jsx menyembunyikan baris keyakinan kalau null.
        confidence = None

    # SRS FCR-003 poin 12.a: "Answers show source references" -- dulu baris
    # ini cuma `[d.page_content for d in docs]`, membuang semua metadata
    # (filename/doc_id/chunk_index dari KbDivisiRetriever & NativeChromaRetriever,
    # faq_id dari FaqChromaRetriever) padahal sudah ADA di `d.metadata` sejak
    # index_document()/index_kb_document()/index_faq_entry(). Sekarang setiap
    # chunk jadi dict supaya metadata itu bisa diteruskan sampai ke
    # ChatReplyResponse.sources (lihat _build_source_citations() di chat/routes.py)
    # -- build_prompt() di llm/router.py cuma pakai chunk["text"], tidak berubah.
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
    # Chat-scoped collection only (where chat_id=...) -- always "chat_document",
    # never faq/kb_divisi, same reasoning as retrieve_context() above.
    return [
        {
            "text": d, "filename": (m or {}).get("filename"), "chunk_index": (m or {}).get("chunk_index"),
            "page": (m or {}).get("page"), "source_type": "chat_document",
        }
        for d, m in zip(docs_list, metas_list)
    ]
