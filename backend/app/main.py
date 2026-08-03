"""
[DIKERJAKAN BERSAMA]
Entry point aplikasi FastAPI. Menyatukan semua router dari A dan B.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.auth.routes import router as auth_router
from app.chat.routes import router as chat_router
from app.rag.routes import router as documents_router

# Buat semua tabel di PostgreSQL kalau belum ada (cukup untuk skala internship;
# untuk produksi biasanya pakai Alembic migration)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Generic ChatBot AI — Tingkat 1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # alamat frontend Next.js
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(documents_router)


@app.get("/")
def health_check():
    return {"status": "ok", "message": "Backend berjalan"}
