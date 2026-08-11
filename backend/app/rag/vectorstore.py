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
    doc = fitz.Document(stream=file_bytes, filetype="pdf")
    return pymupdf4llm.to_markdown(doc=doc)


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
            include=["documents", "metadatas"]
        )
        docs = results.get("documents")
        metas = results.get("metadatas")
        docs_list = docs[0] if docs else []
        metas_list = metas[0] if metas else []
        return [LCDocument(page_content=d, metadata=m or {}) for d, m in zip(docs_list, metas_list)]


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

def retrieve_context(search_query: str, chat_id: str, collection_name: str = "kb_general", top_k: int = 10) -> list[str]:
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
        
    return [d.page_content for d in docs[:top_k]]

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
