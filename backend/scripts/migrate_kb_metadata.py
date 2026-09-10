"""
Tambah kolom `display_title` dan `doc_type` ke tabel kb_documents (2026-09-01).

Proyek ini belum pakai Alembic (folder ada, tapi kosong -- lihat catatan di
vault), dan Base.metadata.create_all() TIDAK menambah kolom ke tabel yang
sudah ada. Jadi seperti dua kali sebelumnya (chats.archived dkk.), kolom baru
di models.py butuh ALTER TABLE manual. Idempoten -- aman dijalankan berkali-kali.

    cd backend
    python -m scripts.migrate_kb_metadata
"""
from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS display_title VARCHAR",
    "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS doc_type VARCHAR",
]

if __name__ == "__main__":
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"-> {stmt}")
            conn.execute(text(stmt))
    print("Selesai. Dokumen KB yang sudah ada punya display_title/doc_type = NULL -- fallback ke filename apa adanya, tidak perlu diisi ulang.")
