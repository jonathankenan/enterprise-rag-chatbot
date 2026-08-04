"""
[PENANGGUNG JAWAB: Anggota B]
Setup koneksi ke PostgreSQL menggunakan SQLAlchemy.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

db_url = settings.database_url
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(db_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency untuk endpoint FastAPI — buka session, tutup otomatis setelah request selesai."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()