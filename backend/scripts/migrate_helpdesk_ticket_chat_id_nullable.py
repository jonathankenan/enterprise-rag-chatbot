"""
Longgarkan helpdesk_tickets.chat_id jadi NULLABLE (2026-09-13).

Proyek ini belum pakai Alembic (folder ada, tapi kosong), dan
Base.metadata.create_all() TIDAK mengubah constraint kolom yang sudah ada.
Tabel helpdesk_tickets dibuat sebelum jalur "Hubungi Admin" (tiket TANPA
chat_id, lihat docstring create_ticket() di helpdesk/routes.py) ditambahkan --
models.py sudah benar (chat_id nullable=True, komentarnya eksplisit), tapi
constraint NOT NULL lama di live DB tidak pernah ikut berubah. Akibatnya
POST /helpdesk/tickets lewat jalur "Hubungi Admin" (chat_id memang None by
design) gagal dengan NotNullViolation di setiap mesin/checkout yang tabelnya
dibuat sebelum perubahan ini ada di models.py. Idempoten -- aman dijalankan
berkali-kali.

    cd backend
    python -m scripts.migrate_helpdesk_ticket_chat_id_nullable
"""
from sqlalchemy import text

from app.database import engine

STATEMENTS = [
    "ALTER TABLE helpdesk_tickets ALTER COLUMN chat_id DROP NOT NULL",
]

if __name__ == "__main__":
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"-> {stmt}")
            conn.execute(text(stmt))
    print("Selesai.")
