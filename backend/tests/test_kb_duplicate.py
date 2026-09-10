"""
Penjaga unggahan ganda ke knowledge base divisi.

Kenapa ini ada: dokumen yang sama pernah terindeks dua kali, dan akibatnya
TIDAK terlihat dari luar sama sekali -- tidak ada error, daftar dokumen cuma
menampilkan dua baris yang wajar. Yang rusak diam-diam adalah daya ambilnya.
Retrieval mengambil top_k=10, tapi karena tiap chunk punya kembaran, yang
sampai ke model cuma 5 chunk berbeda:

    duplikat : 10 chunk, 5 unik   -> baris "Jumlah pegawai tetap" TIDAK terambil
    unik     : 10 chunk, 10 unik  -> terambil

Pertanyaannya dijawab "data tidak tersedia" padahal datanya ada di dokumen.
Kegagalan diam adalah yang paling mahal: tidak ada yang bisa dilacak.
"""
import app.rag.vectorstore as vs
from app.rag.vectorstore import content_hash, KB_COMPANY_WIDE_SENTINEL


class _FakeCollection:
    """Menirukan Chroma secukupnya: add() menyimpan, get() menyaring metadata."""
    def __init__(self):
        self.metas: list[dict] = []

    def add(self, documents, ids, metadatas):
        self.metas.extend(metadatas)

    def get(self, where=None, include=None, limit=None):
        syarat = where.get("$and", [where]) if where else []
        cocok = [m for m in self.metas
                 if all(m.get(k) == v for s in syarat for k, v in s.items())]
        if limit:
            cocok = cocok[:limit]
        return {"metadatas": cocok}


def _pasang(monkeypatch):
    col = _FakeCollection()
    monkeypatch.setattr(vs, "get_collection", lambda name: col)
    return col


HAL = [{"page": 1, "text": "|A|B|C|\n|---|---|---|\n|x|y|z|\n|p|q|r|\n"}]


# --------------------------------------------------------------------------
# Sidik jari isi
# --------------------------------------------------------------------------

def test_hash_sama_untuk_isi_sama():
    assert content_hash(b"halo dunia") == content_hash(b"halo dunia")


def test_hash_beda_untuk_isi_beda():
    assert content_hash(b"halo dunia") != content_hash(b"halo duniA")


# --------------------------------------------------------------------------
# Deteksi kembar
# --------------------------------------------------------------------------

def test_belum_ada_apa_apa_bukan_kembar(monkeypatch):
    _pasang(monkeypatch)
    assert vs.find_kb_duplicate(content_hash(b"isi"), "PTI") is None


def test_isi_identik_di_divisi_sama_terdeteksi(monkeypatch):
    _pasang(monkeypatch)
    h = content_hash(b"isi")
    vs.index_kb_document(pages=HAL, doc_id="doc-1", filename="a.pdf",
                         divisi="PTI", hash_isi=h)
    assert vs.find_kb_duplicate(h, "PTI") == "doc-1"


def test_isi_identik_di_divisi_LAIN_bukan_kembar(monkeypatch):
    """
    Berkas yang sama sengaja diunggah ke dua divisi itu SAH -- mis. kebijakan
    yang berlaku di keduanya. Retrieval memisahkannya lewat filter divisi,
    jadi tidak ada kembaran yang saling memakan slot.
    """
    _pasang(monkeypatch)
    h = content_hash(b"isi")
    vs.index_kb_document(pages=HAL, doc_id="doc-1", filename="a.pdf",
                         divisi="PTI", hash_isi=h)
    assert vs.find_kb_duplicate(h, "SDI") is None


def test_company_wide_punya_wilayahnya_sendiri(monkeypatch):
    _pasang(monkeypatch)
    h = content_hash(b"isi")
    vs.index_kb_document(pages=HAL, doc_id="doc-cw", filename="a.pdf",
                         divisi=None, hash_isi=h)
    assert vs.find_kb_duplicate(h, None) == "doc-cw"
    assert vs.find_kb_duplicate(h, "PTI") is None


def test_isi_berbeda_bukan_kembar(monkeypatch):
    _pasang(monkeypatch)
    vs.index_kb_document(pages=HAL, doc_id="doc-1", filename="a.pdf",
                         divisi="PTI", hash_isi=content_hash(b"isi lama"))
    assert vs.find_kb_duplicate(content_hash(b"isi baru"), "PTI") is None


# --------------------------------------------------------------------------
# Kompatibilitas dokumen lama
# --------------------------------------------------------------------------

def test_dokumen_lama_tanpa_hash_tidak_bikin_error(monkeypatch):
    """
    Dokumen yang diindeks SEBELUM penjaga ini ada tidak punya content_hash.
    Deteksi berbasis hash tidak akan menemukannya -- itu diterima, karena
    pemeriksaan NAMA di endpoint (lewat tabel kb_documents) yang menutupinya.
    Yang penting: tidak meledak.
    """
    _pasang(monkeypatch)
    vs.index_kb_document(pages=HAL, doc_id="doc-lama", filename="a.pdf",
                         divisi="PTI")            # tanpa hash_isi
    assert vs.find_kb_duplicate(content_hash(b"apa pun"), "PTI") is None


def test_hash_ditulis_ke_setiap_chunk(monkeypatch):
    """Kalau cuma sebagian chunk membawanya, deteksi jadi bergantung keberuntungan."""
    col = _pasang(monkeypatch)
    h = content_hash(b"isi")
    n = vs.index_kb_document(pages=HAL, doc_id="doc-1", filename="a.pdf",
                             divisi="PTI", hash_isi=h)
    assert n > 0
    assert all(m.get("content_hash") == h for m in col.metas)
    assert all(m.get("divisi") == "PTI" for m in col.metas)


def test_company_wide_ditandai_sentinel_bukan_none(monkeypatch):
    """ChromaDB tidak bisa menyimpan None di metadata — itu alasan sentinel ada."""
    col = _pasang(monkeypatch)
    vs.index_kb_document(pages=HAL, doc_id="doc-cw", filename="a.pdf",
                         divisi=None, hash_isi=content_hash(b"isi"))
    assert all(m["divisi"] == KB_COMPANY_WIDE_SENTINEL for m in col.metas)
