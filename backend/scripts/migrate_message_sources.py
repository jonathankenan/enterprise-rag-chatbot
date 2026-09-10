"""
Tambah kolom `sources` ke tabel messages (2026-09-09).

Proyek ini belum pakai Alembic (folder ada, tapi kosong -- lihat catatan di
vault), dan Base.metadata.create_all() TIDAK menambah kolom ke tabel yang
sudah ada. Jadi seperti beberapa kali sebelumnya (chats.archived,
kb_documents.display_title, dkk.), kolom baru di models.py butuh ALTER TABLE
manual. Idempoten -- aman dijalankan berkali-kali.

Latar: sitasi sumber cuma pernah dikirim SEKALI, di respons kirim-pesan
(ChatReplyResponse) -- tidak pernah disimpan. Refresh halaman atau login
ulang memanggil GET /messages, yang tidak pernah tahu sitasi itu ada, jadi
badge "Referensi" hilang meski jawabannya sendiri masih ada.

    cd backend
    python -m scripts.migrate_message_sources
"""
from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS sources TEXT",
]

if __name__ == "__main__":
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"-> {stmt}")
            conn.execute(text(stmt))
    print("Selesai. Pesan lama punya sources = NULL -- get_messages() memperlakukannya sebagai [] (tidak ada sitasi), bukan error. Sitasi pesan LAMA sendiri sudah tidak bisa dipulihkan (tidak pernah tersimpan), tapi pesan BARU sejak sekarang akan tetap ada setelah refresh/login ulang.")
