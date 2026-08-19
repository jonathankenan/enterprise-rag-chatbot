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


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extract PDF to text for RAG indexing using a hybrid strategy.

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
    """
    doc = fitz.Document(stream=file_bytes, filetype="pdf")

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

    # Full-doc fallback word-set — used when page-count doesn't align
    md_words_global = _significant_words(md_output)
    segments_match = len(md_segments) == len(doc)

    COVERAGE_THRESHOLD = 0.80  # flag if page markdown covers < 80% of plain-text words

    fallback_sections: list[str] = []

    for page_num, page in enumerate(doc):
        plain_text = page.get_text()
        if not plain_text.strip():
            continue  # blank/image-only page

        page_words = _significant_words(plain_text)
        if not page_words:
            continue

        # Use the page-local markdown segment when available — this gives a
        # much more accurate signal than the full-doc word-set, because words
        # from the dropped sections (e.g. 4.2 bullet list) often appear
        # elsewhere in the document, artificially inflating the coverage score.
        if segments_match:
            md_page_words = _significant_words(md_segments[page_num])
        else:
            md_page_words = md_words_global

        covered = page_words & md_page_words
        coverage = len(covered) / len(page_words)

        if coverage < COVERAGE_THRESHOLD:
            clean = plain_text.strip()
            fallback_sections.append(
                f"\n\n<!-- plain-text fallback page {page_num + 1}"
                f" (pymupdf4llm coverage {coverage:.0%}) -->\n{clean}"
            )

    doc.close()

    if fallback_sections:
        return md_output + "\n" + "\n".join(fallback_sections)
    return md_output




def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """
    Pecah teks markdown jadi potongan-potongan kecil (chunk).
    Menggunakan MarkdownTextSplitter agar tidak merusak format markdown
    seperti tabel atau header.
    """
    splitter = MarkdownTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    chunks = splitter.split_text(text)
    return [c for c in chunks if c.strip()]


def index_document(text: str, doc_id: str, filename: str, chat_id: str, collection_name: str = "kb_general"):
    collection = get_collection(collection_name)
    chunks = chunk_text(text)

    ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"filename": filename, "doc_id": doc_id, "chunk_index": i, "chat_id": chat_id} for i in range(len(chunks))]

    collection.add(documents=chunks, ids=ids, metadatas=metadatas)  # type: ignore
    return len(chunks)


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


def retrieve_context(search_query: str, chat_id: str, collection_name: str = "kb_general", top_k: int = 10) -> tuple[list[str], int | None]:
    """
    Kembalikan (potongan_teks, retrieval_confidence). Confidence 0-100
    dihitung dari distance yang didapat SEKALI di dalam NativeChromaRetriever
    di atas (via metadata["_distance"]) — TIDAK ada query Chroma kedua
    terpisah lagi cuma untuk menghitung skor (dulu ada fungsi
    compute_retrieval_confidence() sendiri yang query ulang; sekarang
    dihapus, digabung ke sini).

    Confidence cuma dihitung dari dokumen hasil LEG VECTOR (yang punya
    "_distance" di metadata) — dokumen dari leg BM25 (keyword match, dipakai
    kalau ensemble retrieval aktif) diabaikan untuk keperluan skor, karena
    BM25 tidak punya angka yang sebanding dengan cosine similarity.
    """
    chroma_retriever = NativeChromaRetriever(chat_id=chat_id, collection_name=collection_name, top_k=top_k)
    bm25_retriever = get_bm25_retriever(chat_id=chat_id, collection_name=collection_name, top_k=top_k)

    if not bm25_retriever:
        docs = chroma_retriever.invoke(search_query)
    else:
        ensemble = EnsembleRetriever(
            retrievers=[chroma_retriever, bm25_retriever],
            weights=[0.5, 0.5]
        )
        docs = ensemble.invoke(search_query)

    docs = docs[:top_k]

    distances = [d.metadata["_distance"] for d in docs if "_distance" in d.metadata]
    if distances:
        similarities = [_distance_to_similarity_percent(dist) for dist in distances]
        confidence = round((sum(similarities) / len(similarities)) * 100)
    else:
        # Tidak ada satupun dokumen dari leg vector (koleksi kosong, atau
        # hasil ensemble kebetulan semua dari BM25) -> tidak relevan ditampilkan skor.
        confidence = None

    chunks = [d.page_content for d in docs]
    return chunks, confidence

def has_session_document(chat_id: str, collection_name: str = "kb_general") -> bool:
    collection = get_collection(collection_name)
    if collection.count() == 0:
        return False
    results = collection.get(where={"chat_id": chat_id}, limit=1)
    ids = results.get("ids")
    return bool(ids and len(ids) > 0)

def get_all_session_chunks(chat_id: str, limit: int = 15, collection_name: str = "kb_general") -> list[str]:
    collection = get_collection(collection_name)
    if collection.count() == 0:
        return []
    results = collection.get(where={"chat_id": chat_id}, limit=limit, include=["documents"])
    docs = results.get("documents")
    return docs if docs else []
