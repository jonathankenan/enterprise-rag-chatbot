"""
[PENANGGUNG JAWAB: Anggota A]
Fungsi inti RAG: memecah dokumen, mengubahnya jadi embedding,
menyimpan & mencari di Vector Database (Chroma).
"""
import chromadb
from chromadb.utils import embedding_functions
from pypdf import PdfReader

from app.config import settings

# Model embedding lokal, gratis, jalan di CPU — cocok untuk skala internship.
# Model ini yang mengubah teks menjadi vektor (representasi angka).
_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

_client = chromadb.PersistentClient(path=settings.chroma_persist_dir)


def get_collection(name: str = "kb_general"):
    """Ambil (atau buat baru) satu koleksi vector DB."""
    return _client.get_or_create_collection(name=name, embedding_function=_embedding_fn)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Ambil teks mentah dari file PDF."""
    reader = PdfReader(file_bytes)  # type: ignore
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    Pecah teks panjang jadi potongan-potongan kecil (chunk).
    Overlap = sedikit tumpang tindih antar chunk, supaya konteks di
    perbatasan potongan tidak terputus.
    """
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return [c for c in chunks if c.strip()]


def index_document(text: str, doc_id: str, filename: str, collection_name: str = "kb_general"):
    """
    Alur lengkap: teks -> chunk -> simpan ke vector DB.
    Dipanggil setelah dokumen diunggah (lihat app/rag/routes.py).
    """
    collection = get_collection(collection_name)
    chunks = chunk_text(text)

    ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"filename": filename, "doc_id": doc_id, "chunk_index": i} for i in range(len(chunks))]

    collection.add(documents=chunks, ids=ids, metadatas=metadatas)
    return len(chunks)


def retrieve_context(query: str, collection_name: str = "kb_general", top_k: int = 3) -> list[str]:
    """
    Fungsi RETRIEVAL — inti dari "R" di RAG.
    Cari potongan teks yang paling relevan secara makna dengan pertanyaan user.
    """
    collection = get_collection(collection_name)
    if collection.count() == 0:
        return []

    results = collection.query(query_texts=[query], n_results=min(top_k, collection.count()))
    documents = results.get("documents", [[]])[0]
    return documents
