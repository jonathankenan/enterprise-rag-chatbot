"""
Indeks empat PDF fixture KB (PTI, SDI, WAS, Company Wide) lewat jalur yang
SAMA dengan upload di UI: index_kb_document() ke Chroma + satu baris
KbDocument di Postgres.

    cd backend
    python -m scripts.make_kb_fixtures    # sekali, bikin PDF-nya
    python -m scripts.seed_kb_fixtures    # indeks yang belum ada
    python -m scripts.seed_kb_fixtures --list   # cuma laporkan isi sekarang

Kenapa perlu skrip ini, padahal sudah ada test_kb_isolation.py --keep: skrip
itu cuma menyentuh Chroma (yang memang cukup untuk retrieval), jadi dokumennya
tidak pernah muncul di halaman admin KB dan tidak bisa dihapus dari UI. Yang
ini menulis keduanya, seperti kalau diunggah admin.

Latar (2026-09-13): menyiapkan korpus uji sebelumnya harus lewat UI satu per
satu, jadi sesudah skenario uji yang memang MENGHAPUS dokumen ("hapus dokumen
KB lalu tanyakan lagi", seri H), memulihkannya jadi pekerjaan manual dan
gampang lupa -- dan KB yang separuh terisi itu tidak bisa dibedakan dari bug
retrieval kalau dilihat dari sisi chat saja. Skrip ini bikin pemulihannya satu
perintah.

Catatan untuk yang membaca nanti: KB divisi yang tidak lengkap BELUM TENTU
masalah. Cek audit log dulu (event kb_document_uploaded / kb_document_deleted)
sebelum menyimpulkan -- bisa jadi itu state uji yang disengaja. Kekeliruan itu
pernah terjadi persis di sini.

Idempoten: yang sudah terindeks (dicocokkan per divisi + nama berkas) dilewati,
jadi aman dijalankan berkali-kali. Pakai --replace untuk memaksa indeks ulang.
"""
import argparse
import pathlib
import sys
import uuid

from app.database import SessionLocal
from app.models import KbDocument, KbDocType, User, Role
from app.rag.vectorstore import (
    content_hash, delete_kb_document_from_index, extract_pages_from_pdf,
    index_kb_document,
)

FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[1] / "kb_fixtures"

# (nama berkas, divisi, display_title, doc_type) -- divisi None = Company Wide.
# display_title/doc_type diisi supaya sitasi terbaca seperti di demo
# ("Pedoman Operasional PTI (Pedoman)"), bukan nama berkas mentah.
FIXTURES = [
    ("KB_PTI_Pedoman_Operasional.pdf", "PTI", "Pedoman Operasional Divisi PTI", KbDocType.PEDOMAN),
    ("KB_SDI_Pedoman_Operasional.pdf", "SDI", "Pedoman Operasional Divisi SDI", KbDocType.PEDOMAN),
    ("KB_WAS_Pedoman_Operasional.pdf", "WAS", "Pedoman Operasional Divisi WAS", KbDocType.PEDOMAN),
    ("KB_CompanyWide_Ketentuan_Umum.pdf", None, "Ketentuan Umum Company Wide", KbDocType.PERATURAN),
]


def _wilayah(divisi: str | None) -> str:
    return divisi or "Company Wide"


def _report(db) -> None:
    docs = db.query(KbDocument).order_by(KbDocument.divisi.nulls_first()).all()
    if not docs:
        print("  (kb_documents kosong)")
        return
    for d in docs:
        print(f"  {_wilayah(d.divisi):13} {d.filename:44} {d.chunk_count or 0:>4} chunk")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="cuma laporkan isi kb_documents sekarang")
    ap.add_argument("--replace", action="store_true", help="indeks ulang walau sudah ada")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.list:
            print("kb_documents saat ini:")
            _report(db)
            return 0

        # Dokumen KB butuh pengunggah; pakai IT Admin mana pun yang ada supaya
        # baris Postgres-nya sah (uploaded_by NOT NULL).
        admin = db.query(User).filter(User.role == Role.IT_ADMIN).first()
        if admin is None:
            print("Tidak ada akun IT_ADMIN. Buat dulu:", file=sys.stderr)
            print("  python -m scripts.create_user admin.global@idx.co.id --role it_admin", file=sys.stderr)
            return 1

        for filename, divisi, display_title, doc_type in FIXTURES:
            path = FIXTURE_DIR / filename
            if not path.is_file():
                print(f"LEWAT  {filename} -- berkas tidak ada, jalankan scripts.make_kb_fixtures dulu")
                continue

            sudah = (
                db.query(KbDocument)
                .filter(KbDocument.filename == filename,
                        KbDocument.divisi.is_(None) if divisi is None else KbDocument.divisi == divisi)
                .first()
            )
            if sudah and not args.replace:
                print(f"ADA    {_wilayah(divisi):13} {filename} ({sudah.chunk_count or 0} chunk)")
                continue
            if sudah:
                delete_kb_document_from_index(sudah.id)
                db.delete(sudah)
                db.commit()

            isi = path.read_bytes()
            pages = extract_pages_from_pdf(isi)
            doc_id = str(uuid.uuid4())
            chunk_count = index_kb_document(
                pages=pages, doc_id=doc_id, filename=filename, divisi=divisi,
                hash_isi=content_hash(isi), display_title=display_title, doc_type=doc_type,
            )
            db.add(KbDocument(id=doc_id, divisi=divisi, filename=filename,
                              display_title=display_title, doc_type=doc_type,
                              chunk_count=chunk_count, uploaded_by=admin.id))
            db.commit()
            print(f"INDEKS {_wilayah(divisi):13} {filename} -> {chunk_count} chunk")

        print("\nkb_documents sekarang:")
        _report(db)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
