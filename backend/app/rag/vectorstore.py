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


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Pecah teks markdown jadi chunk kecil, pakai MarkdownTextSplitter supaya tabel/header tidak rusak."""
    splitter = MarkdownTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    chunks = splitter.split_text(text)
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


def index_kb_document(pages: list[dict], doc_id: str, filename: str, divisi: str | None) -> int:
    """Multi-Tenant KB (SRS poin 11) — divisi=None berarti Company Wide, chunk per halaman sama seperti index_document()."""
    collection = get_collection(KB_DIVISI_COLLECTION_NAME)
    divisi_tag = divisi or KB_COMPANY_WIDE_SENTINEL
    documents: list[str] = []
    metadatas: list[dict] = []
    for page_info in pages:
        for c in chunk_text(page_info["text"]):
            documents.append(c)
            meta = {"doc_id": doc_id, "filename": filename, "chunk_index": len(documents) - 1, "divisi": divisi_tag}
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

    best_indices: set[int] = set()
    if ranked:
        first = ranked[0]
        best_indices.add(first)
        reference = _similarity(first)
        if reference is None:
            reference = 100.0
        floor = reference - CITATION_SIMILARITY_GAP
        for i in ranked[1:]:
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
