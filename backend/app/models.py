"""
[PENANGGUNG JAWAB: Anggota B]
Model tabel untuk database relasional (PostgreSQL).
Ini menyimpan data TERSTRUKTUR: user, chat, pesan, metadata dokumen.
(Isi/teks dokumen untuk RAG disimpan terpisah di Vector DB — lihat app/rag/)
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum, Integer
from sqlalchemy.types import TypeDecorator
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.database import Base
from app.guardrail.encryption import encrypt_text, decrypt_text


def gen_uuid():
    return str(uuid.uuid4())


class EncryptedText(TypeDecorator):
    """
    Tipe kolom SQLAlchemy yang transparan mengenkripsi nilai saat ditulis ke
    DB dan mendekripsi saat dibaca kembali — lihat app/guardrail/encryption.py
    untuk penjelasan lengkap (SRS FCR-003 poin 3.k: enkripsi at-rest).
    Dipakai untuk Message.content supaya kode di chat/routes.py TIDAK perlu
    tahu apa pun soal enkripsi — cukup baca/tulis `message.content` seperti
    string biasa, encrypt/decrypt terjadi otomatis di level ORM.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return encrypt_text(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return decrypt_text(value)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    role = Column(String, default="user")  # contoh: "user", "admin"
    created_at = Column(DateTime, default=datetime.utcnow)

    chats = relationship("Chat", back_populates="owner")


class Chat(Base):
    __tablename__ = "chats"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    title = Column(String, default="Percakapan Baru")
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="chats")
    messages = relationship("Message", back_populates="chat", order_by="Message.created_at")


class SenderType(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    chat_id = Column(UUID(as_uuid=False), ForeignKey("chats.id"), nullable=False)
    sender = Column(Enum(SenderType), nullable=False)
    # content menyimpan versi MASKED kalau ada PII (SRS FCR-003 poin 3.j:
    # "data yang disimpan kedalam histori adalah informasi yang sudah
    # dimasking"). Placeholder [TYPE_n] di sini dipetakan balik lewat
    # pii_mapping saat perlu ditampilkan ke pemilik chat yang sah.
    content = Column(EncryptedText, nullable=False)
    # Mapping placeholder -> nilai asli, format JSON: {"[ID_NIK_1]": "3271...", ...}.
    # None kalau pesan ini tidak mengandung PII sama sekali. WAJIB EncryptedText
    # (bukan Text biasa) — kolom ini secara harfiah menyimpan nilai PII asli,
    # jadi kalau tidak dienkripsi, tujuan masking content di atas jadi percuma
    # (orang tinggal baca kolom sebelah).
    pii_mapping = Column(EncryptedText, nullable=True)
    # jejak dari mana jawaban berasal — berguna untuk debugging & transparansi
    llm_used = Column(String, nullable=True)      # "on-prem" | "commercial"
    confidence_score = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    chat = relationship("Chat", back_populates="messages")


class Document(Base):
    """Metadata dokumen yang diunggah untuk knowledge base (isi teksnya ada di Vector DB)."""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    uploaded_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    collection_name = Column(String, default="kb_general")  # nama koleksi di vector DB
    created_at = Column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    """Jejak aktivitas guardrail — F2-04, untuk kebutuhan audit/compliance."""
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    event_type = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="low")
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)