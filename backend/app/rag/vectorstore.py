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

    Primary pass: pymupdf4llm.to_markdown() provides clean markdown
    formatting (especially for tables), which the MarkdownTextSplitter
    downstream handles well.

    Known issue (confirmed via diagnostic against Project NEXUS BRD, page 6):
    when a table is immediately followed by non-tabular text (bulleted lists,
    plain paragraphs) on the same PDF page, pymupdf4llm silently drops the
    post-table content. Root cause: the table bounding-box detection
    (table_strategy='lines_strict') swallows/overlaps the adjacent text
    region, so it never gets rendered into the markdown output. This affects
    any PDF with this common layout pattern, not just the test document.

    Safety-net pass: pymupdf4llm inserts '-----' page-break separators
    between pages in the markdown output. We split on those to get per-page
    markdown segments, then compare each segment's significant-word set
    against the corresponding page's raw plain text from fitz. If a page's
    markdown segment is missing more than 20% of the words in its plain text,
    we append the raw plain text as a fallback so the content reaches the
    chunker/indexer regardless of what the markdown pass dropped.

    The 20% threshold is intentionally tight: table-only pages typically have
    near-100% coverage because the table cell text renders identically in both
    plain text and markdown. Pages that genuinely dropped post-table prose
    show 30-50% coverage gaps — well above the noise floor.

    Returns a list of {"page": int | None, "text": str}, one entry per PDF
    page IN ORDER. "page" is only None in the rare case where pymupdf4llm's
    '-----' page-break count doesn't match doc.page_count (segments_match
    below) -- when that happens we can't safely attribute ANY page number,
    so the whole document comes back as a single page=None entry rather
    than guessing wrong numbers.
    """
    # ── Primary pass: pymupdf4llm markdown ──────────────────────────────────
    md_output = pymupdf4llm.to_markdown(doc=doc)

    # ── Split markdown into per-page segments ────────────────────────────────
    # pymupdf4llm inserts '\n\n-----\n\n' between pages. Split on that to
    # align markdown segments with their source pages. The resulting list
    # should have the same length as doc.page_count; if the split count
    # doesn't match (e.g. content contains '-----' for other reasons), we
    # fall back gracefully to the full-doc word-set instead.
    PAGE_BREAK = "\n\n-----\n\n"
    md_segments = md_output.split(PAGE_BREAK)

    def _significant_words(text: str) -> set[str]:
        """Lowercase alphabetic words longer than 3 chars (ignores numbers and
        short stop-words that create noise between plain-text and markdown)."""
        return {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", text)}

    md_words_global = _significant_words(md_output)
    segments_match = len(md_segments) == len(doc)

    COVERAGE_THRESHOLD = 0.80  # flag if page markdown covers < 80% of plain-text words

    if not segments_match:
        # Can't attribute page numbers safely -- fall back to the ORIGINAL
        # (pre-page-numbering) behaviour: one blob for the whole document,
        # fallback sections appended at the end, page=None throughout.
        fallback_sections: list[str] = []
        for page_num, page in enumerate(doc):
            plain_text = page.get_text()
            if not plain_text.strip():
                continue
            page_words = _significant_words(plain_text)
            if not page_words:
                continue
            covered = page_words & md_words_global
            coverage = len(covered) / len(page_words)
            if coverage < COVERAGE_THRESHOLD:
                clean = plain_text.strip()
                fallback_sections.append(
                    f"\n\n<!-- plain-text fallback page {page_num + 1}"
                    f" (pymupdf4llm coverage {coverage:.0%}) -->\n{clean}"
                )
        full_text = md_output + ("\n" + "\n".join(fallback_sections) if fallback_sections else "")
        return [{"page": None, "text": full_text}]

    pages_out: list[dict] = []
    for page_num, page in enumerate(doc):
        plain_text = page.get_text()
        page_text = md_segments[page_num]

        if plain_text.strip():
            page_words = _significant_words(plain_text)
            if page_words:
                md_page_words = _significant_words(page_text)
                covered = page_words & md_page_words
                coverage = len(covered) / len(page_words)
                if coverage < COVERAGE_THRESHOLD:
                    clean = plain_text.strip()
                    page_text = (
                        page_text + f"\n\n<!-- plain-text fallback page {page_num + 1}"
                        f" (pymupdf4llm coverage {coverage:.0%}) -->\n{clean}"
                    )
        # Blank/image-only page: keep its (likely empty) markdown segment as-is,
        # still numbered -- so later pages don't shift down just because an
        # earlier page had nothing extractable.

        pages_out.append({"page": page_num + 1, "text": page_text})

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
    # chat-scoped/FAQ/KB divisi -- bukan BM25). Dipakai bareng buat confidence
    # DAN buat nentuin chunk mana yang layak masuk citation, lihat di bawah.
    distance_by_index = {i: d.metadata["_distance"] for i, d in enumerate(docs) if "_distance" in d.metadata}

    # TOP_MATCHES (3) dipakai untuk DUA hal sekaligus, sengaja disatukan
    # supaya konsisten -- "seberapa yakin" dan "sumber mana yang disebut"
    # semestinya merujuk ke bukti yang SAMA, bukan dua definisi berbeda:
    #
    # 1. Confidence = rata-rata similarity dari 3 chunk TERBAIK (distance
    #    terkecil), bukan semua sampai top_k=10. Diubah 2026-08-24 --
    #    sebelumnya rata-rata dari semua chunk hasil ensemble (termasuk yang
    #    cuma "di sekitar" tapi tidak betul-betul dipakai LLM buat jawab)
    #    bikin skor jadi bias turun: 1 chunk yang match presisi (mis.
    #    similarity ~92%) ketarik ke bawah sama chunk lain yang cuma "cukup
    #    relevan" (mis. 55-70%). Tetap ambil >1 (bukan cuma top-1) supaya
    #    jawaban yang genuinely butuh sintesis dari beberapa sumber tidak
    #    direduksi ke satu titik data yang rapuh.
    #
    # 2. Source citation (SRS FCR-003 poin 12.a) -- ditandai via
    #    "is_top_match" di tiap chunk, dikonsumsi _build_source_citations()
    #    di chat/routes.py. Ditambahkan 2026-08-24 setelah user melaporkan
    #    citation "FR-01" ikut menyebut 5 halaman lain yang sama sekali
    #    tidak membahas FR-01 (halaman 2/3/6/8/10 dari Project NEXUS BRD --
    #    cuma "di sekitar secara topik" dalam window top_k=10, sama seperti
    #    masalah yang bikin confidence bias turun). context_chunks TETAP
    #    lengkap sampai top_k (LLM masih dapat konteks penuh buat jawab,
    #    termasuk kasus FR-12 "multi-document synthesis" yang genuinely
    #    butuh banyak chunk) -- yang dipersempit cuma bagian mana yang
    #    LAYAK DISEBUT sebagai sumber.
    TOP_MATCHES = 3
    best_indices = set(sorted(distance_by_index, key=lambda i: distance_by_index[i])[:TOP_MATCHES])

    if distance_by_index:
        best_distances = [distance_by_index[i] for i in best_indices]
        similarities = [_distance_to_similarity_percent(dist) for dist in best_distances]
        confidence = round((sum(similarities) / len(similarities)) * 100)
    else:
        # Tidak ada satupun dokumen dari leg vector (koleksi kosong, atau
        # hasil ensemble kebetulan semua dari BM25) -> tidak relevan ditampilkan skor.
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
