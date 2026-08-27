"""Model tabel database relasional (PostgreSQL) — data terstruktur: user, chat, pesan, metadata dokumen (isi/teks dokumen RAG ada di Vector DB, lihat app/rag/)."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum, Integer, Boolean
from sqlalchemy.types import TypeDecorator
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.database import Base
from app.guardrail.encryption import encrypt_text, decrypt_text


def gen_uuid():
    return str(uuid.uuid4())


class EncryptedText(TypeDecorator):
    """Tipe kolom SQLAlchemy yang transparan enkripsi/dekripsi (SRS poin 3.k) — caller cukup baca/tulis seperti string biasa."""
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


class Role:
    """8 role sesuai SRS hal. 15 poin 2.d — cuma AUDIT_VIEWERS yang benar-benar dibedakan perilakunya di PoC ini, role lain sah tapi fiturnya belum ada."""
    IT_ADMIN = "it_admin"
    DESIGNER = "designer"
    MLOPS = "mlops"
    CONSUMER_INTERNAL = "consumer_internal"            # "Consumer internal BEI"
    CONSUMER_EIPO = "consumer_eipo"                    # "Consumer internet – eipo"
    BUSINESS_USER_DESIGNER = "business_user_designer"
    COMPLIANCE = "compliance"                          # "Compliance users"
    AUDITOR = "auditor"                                # "Auditor view"

    ALL = (
        IT_ADMIN, DESIGNER, MLOPS, CONSUMER_INTERNAL, CONSUMER_EIPO,
        BUSINESS_USER_DESIGNER, COMPLIANCE, AUDITOR,
    )

    AUDIT_VIEWERS = (IT_ADMIN, COMPLIANCE, AUDITOR)  # role yang boleh baca audit log guardrail


class Divisi:
    """9 divisi sesuai SRS (hal. 8-9, 64-70), terpisah dari Role — dasar Multi-Tenant KB (SRS hal. 14 Rules poin 1)."""
    WAS = "WAS"
    PLP = "PLP"
    PPT = "PPT"
    PP1 = "PP1"
    PP2 = "PP2"
    PP3 = "PP3"
    PTI = "PTI"
    SDI = "SDI"
    OTP = "OTP"

    ALL = (WAS, PLP, PPT, PP1, PP2, PP3, PTI, SDI, OTP)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    role = Column(String, default=Role.CONSUMER_INTERNAL)  # salah satu dari Role.ALL
    divisi = Column(String, nullable=True)  # None = global (IT_ADMIN admin global); terisi = anggota/admin divisi itu (SRS hal. 68/70)
    created_at = Column(DateTime, default=datetime.utcnow)
    password_changed_at = Column(DateTime, default=datetime.utcnow)  # SRS ISR-002.c: umur password maks 90 hari

    totp_secret = Column(EncryptedText, nullable=True)  # SRS ISR-001.d MFA — wajib EncryptedText, bocor = sama fatalnya dgn password bocor
    mfa_enabled = Column(Boolean, nullable=False, default=False)

    auth_provider = Column(String, nullable=False, default="local")  # "local" | "azure" (SRS hal. 64) — azure skip cek password_expired

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
    content = Column(EncryptedText, nullable=False)  # versi MASKED kalau ada PII (SRS poin 3.j)
    pii_mapping = Column(EncryptedText, nullable=True)  # placeholder -> nilai asli, JSON; wajib EncryptedText juga (nilai PII asli)
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
    detail = Column(EncryptedText, nullable=True)  # SRS ISR-006.b: SEMUA data terenkripsi, termasuk cuplikan pesan pra-masking
    created_at = Column(DateTime, default=datetime.utcnow)


class TicketStatus:
    OPEN = "open"
    CLOSED = "closed"


class HelpdeskTicket(Base):
    """Tiket eskalasi ke human helpdesk (SRS poin 7) — chat_id saja, tanpa snapshot riwayat (ambil langsung dari tabel Message biar tidak basi/duplikat)."""
    __tablename__ = "helpdesk_tickets"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    chat_id = Column(UUID(as_uuid=False), ForeignKey("chats.id"), nullable=False)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    message_id = Column(UUID(as_uuid=False), ForeignKey("messages.id"), nullable=True)  # jawaban AI yang memicu eskalasi
    confidence_score = Column(Integer, nullable=True)
    status = Column(String, default=TicketStatus.OPEN)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User")  # one-directional, tidak perlu back_populates di User


class HelpdeskSender:
    USER = "user"
    ADMIN = "admin"


class HelpdeskMessage(Base):
    """Percakapan dua-arah user<->admin di dalam satu tiket (real-time via WebSocket, helpdesk/ws.py) — beda dari Message (chat AI)."""
    __tablename__ = "helpdesk_messages"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    ticket_id = Column(UUID(as_uuid=False), ForeignKey("helpdesk_tickets.id"), nullable=False)
    sender_role = Column(String, nullable=False)  # HelpdeskSender.USER | ADMIN
    sender_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)  # nullable buat kemungkinan pesan sistem nanti
    content = Column(EncryptedText, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    sender = relationship("User")


class SystemSettings(Base):
    """Konfigurasi sistem yang bisa diubah runtime oleh IT Admin (beda dari config.py yang butuh .env+restart) — tabel singleton, id="global"."""
    __tablename__ = "system_settings"

    id = Column(String, primary_key=True, default="global")
    commercial_llm_force_stopped = Column(Boolean, nullable=False, default=False)  # SRS hal. 10 Rules poin 2: force-stop LLM Commercial
    export_allowed_roles = Column(Text, nullable=False, default="it_admin,compliance")  # F2-08, string koma-pisah; IT_ADMIN dipaksa selalu ikut
    updated_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_export_allowed_roles(self) -> list[str]:
        raw = self.export_allowed_roles or ""
        return [r.strip() for r in raw.split(",") if r.strip()]


class FaqEntry(Base):
    """FAQ Helpdesk (SRS poin 10.b) — Postgres source of truth, diindeks ulang ke ChromaDB "kb_faq_helpdesk" supaya bisa di-retrieve semantik tanpa perlu user upload dokumen."""
    __tablename__ = "faq_entries"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    author = relationship("User")

class KbDocument(Base):
    """Multi-Tenant KB (SRS poin 11 & hal. 68) — metadata saja, isi teks diindeks ke ChromaDB koleksi "kb_divisi"; divisi None = Company Wide."""
    __tablename__ = "kb_documents"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    divisi = Column(String, nullable=True)  # None = Company Wide
    filename = Column(String, nullable=False)
    chunk_count = Column(Integer, nullable=False, default=0)
    uploaded_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    uploader = relationship("User")
