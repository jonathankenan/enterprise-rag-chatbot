"""
[PENANGGUNG JAWAB: Anggota B]
Model tabel untuk database relasional (PostgreSQL).
Ini menyimpan data TERSTRUKTUR: user, chat, pesan, metadata dokumen.
(Isi/teks dokumen untuk RAG disimpan terpisah di Vector DB — lihat app/rag/)
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


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
    content = Column(Text, nullable=False)
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
