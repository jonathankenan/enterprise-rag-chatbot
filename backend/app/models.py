"""
[PENANGGUNG JAWAB: Anggota B]
Model tabel untuk database relasional (PostgreSQL).
Ini menyimpan data TERSTRUKTUR: user, chat, pesan, metadata dokumen.
(Isi/teks dokumen untuk RAG disimpan terpisah di Vector DB — lihat app/rag/)
"""
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


class Role:
    """
    8 role PERSIS sesuai SRS FCR-003 hal. 15, poin 2.d (daftar role minimal
    yang wajib dibedakan sistem): IT Admin, Designer, MLOps, Consumer
    internal BEI, Consumer internet-eipo, Business user designer, Compliance
    users, Auditor view.

    CATATAN JUJUR (supaya tidak terkesan menyembunyikan keterbatasan):
    PoC ini baru punya SATU fitur yang benar-benar dibedakan per role (baca
    audit log — lihat AUDIT_VIEWERS). Role lainnya SAH ada dan bisa dipakai,
    tapi sementara ini perilakunya sama saja untuk fitur chat/upload/export
    — bukan karena rolenya keliru, tapi karena fitur yang seharusnya
    membedakan mereka memang belum/tidak ada di repo ini:
    - DESIGNER: mendesain prompt/flow AI — tidak ada fitur desain prompt di PoC ini
    - MLOPS: deploy/monitor model — tidak ada fitur MLOps di PoC ini
    - CONSUMER_EIPO: akses chatbot publik di aplikasi E-IPO — itu FCR-004,
      fitur terpisah yang tidak ada di repo ini
    - BUSINESS_USER_DESIGNER: user bisnis yang mendesain use case — tidak
      ada fitur yang membedakannya dari consumer biasa di PoC ini

    Taksonominya tetap dibuat 8 penuh (bukan disederhanakan) supaya nama &
    struktur sudah benar sejak awal — kalau nanti fitur di atas dibangun,
    tinggal tambah pengecekan `require_role(...)` baru, tanpa migrasi ulang
    skema role.
    """
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

    # Role yang boleh membaca audit log guardrail — IT_ADMIN ikut (wajar,
    # dia superset semua akses), plus 2 role yang memang tujuan utamanya ini.
    AUDIT_VIEWERS = (IT_ADMIN, COMPLIANCE, AUDITOR)


class Divisi:
    """
    9 divisi PERSIS sesuai SRS FCR-003 (banyak disebut di hal. 8-9, 64-70):
    WAS, PLP, PPT, PP1, PP2, PP3, PTI, SDI, OTP. Terpisah dari Role — role
    itu fungsi jabatan (IT Admin, Designer, dst, berlaku lintas divisi),
    divisi itu unit organisasi tempat user bekerja. SRS hal. 14, Rules poin
    1: "Data yang di-upload oleh masing-masing divisi hanya dapat diakses
    oleh divisi tersebut" — dasar Multi-Tenant Knowledge Base (SRS poin 11
    & hal. 68).
    """
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
    role = Column(String, default=Role.CONSUMER_INTERNAL)  # salah satu dari Role.ALL — default: pengguna internal biasa
    # NULL = tidak terikat 1 divisi tertentu (berlaku untuk kebanyakan role,
    # dan untuk IT_ADMIN artinya admin GLOBAL — lihat auth/utils.py
    # get_divisi_scope()). Terisi salah satu Divisi.ALL = user itu anggota
    # divisi tsb; kalau role-nya IT_ADMIN, artinya admin TERBATAS ke divisi
    # itu saja (SRS hal. 68/70: "Admin User dari setiap divisi").
    divisi = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # SRS ISR-002.c: umur password maksimal 90 hari. Di-set ulang tiap kali
    # password diganti (register = set awal, change-password = reset ulang).
    password_changed_at = Column(DateTime, default=datetime.utcnow)

    # SRS ISR-001.d (keterangan): "IT Admin dan user Admin menggunakan
    # Database dengan tambahan Multi Factor Authentication". totp_secret
    # WAJIB EncryptedText — kalau bocor plaintext, siapa pun bisa generate
    # kode OTP yang valid (sama fatalnya dengan kebocoran password).
    totp_secret = Column(EncryptedText, nullable=True)
    mfa_enabled = Column(Boolean, nullable=False, default=False)

    # SRS hal. 64: "User dapat login menggunakan credential Azure AD
    # (primary) atau user internal platform (alternative)". "local" = daftar
    # email+password biasa (jalur yang sudah ada dari awal), "azure" = login
    # via SSO Azure AD (lihat auth/routes.py azure_callback()). Dipakai buat
    # skip pengecekan password_expired untuk akun Azure — mereka tidak
    # punya siklus password lokal yang relevan buat sistem ini sama sekali.
    auth_provider = Column(String, nullable=False, default="local")

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
    # EncryptedText (bukan Text polos) — SRS ISR-006.b minta SEMUA data yang
    # diproses dienkripsi, bukan sebagian. detail berisi cuplikan mentah
    # pesan user (sampai 500 karakter) TERMASUK untuk pesan yang diblokir
    # sebelum sempat dimasking oleh alur chat biasa — kalau kolom ini tidak
    # dienkripsi, ada PII/konten sensitif yang bocor plaintext lewat jalur
    # audit log meski Message.content sudah aman.
    detail = Column(EncryptedText, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TicketStatus:
    OPEN = "open"
    CLOSED = "closed"


class HelpdeskTicket(Base):
    """
    Tiket eskalasi ke human helpdesk — SRS FCR-003 poin 7 "Eskalasi otomatis":
    kalau confidence AI rendah, sistem otomatis buat tiket. Riwayat percakapan
    SENGAJA TIDAK disalin ke sini (tidak ada kolom "chat_history_snapshot")
    — cukup simpan chat_id, lalu endpoint detail tiket ambil pesan langsung
    dari tabel Message yang sudah ada. Alasannya: kalau disalin, salinannya
    bisa basi (chat aslinya masih bisa nambah pesan baru setelah tiket
    dibuat) dan duplikasi data yang sudah dienkripsi+masked di tempat lain.
    """
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
    """
    Percakapan dua-arah user<->admin DI DALAM satu tiket — beda dari
    Message (chat AI) yang sudah ada. Ditambahkan supaya "human helpdesk"
    di SRS FCR-003 poin 7 benar-benar berupa chat dengan staf (real-time,
    lewat WebSocket di helpdesk/ws.py), bukan cuma tiket satu-arah yang
    dibaca sepihak oleh admin.

    sender_id sengaja nullable — kalau nanti ada pesan sistem (mis. "tiket
    ditutup oleh admin"), tidak perlu dikaitkan ke user manapun.
    """
    __tablename__ = "helpdesk_messages"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    ticket_id = Column(UUID(as_uuid=False), ForeignKey("helpdesk_tickets.id"), nullable=False)
    sender_role = Column(String, nullable=False)  # HelpdeskSender.USER | ADMIN
    sender_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    content = Column(EncryptedText, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    sender = relationship("User")


class SystemSettings(Base):
    """
    Konfigurasi sistem yang bisa diubah RUNTIME oleh IT Admin (beda dari
    app/config.py yang cuma bisa diubah lewat .env + restart server).
    Tabel SINGLETON — cuma boleh ada 1 baris, id selalu sama
    ("global"), supaya gampang di-query tanpa perlu tahu ID-nya.

    commercial_llm_force_stopped: SRS FCR-003 hal. 10, Rules poin 2 —
    "Terdapat button 'force stop' dan disable seluruh penggunaan LLM
    Commercial untuk kebutuhan menghentikan operasional ke LLM Commercial
    saat dibutuhkan". Kalau True, SEMUA chat dipaksa ke on-prem, apa pun
    provider yang dipilih user — dicek di chat/routes.py sebelum
    route_and_generate() dipanggil.
    """
    __tablename__ = "system_settings"

    id = Column(String, primary_key=True, default="global")
    commercial_llm_force_stopped = Column(Boolean, nullable=False, default=False)
    # F2-08 (spesifikasi Tingkat 2): "Ekspor percakapan ke PDF, dibatasi hanya
    # untuk role tertentu (mis. admin, compliance)." Disimpan sebagai string
    # koma-pisah (bukan tabel relasi terpisah) — konsisten dengan pola kolom
    # runtime-configurable lain di tabel singleton ini, dan daftarnya pendek
    # (maksimal 8 role) jadi tidak butuh normalisasi berlebihan. IT_ADMIN
    # dipaksa selalu ikut di _get_or_create_settings()/toggle, supaya admin
    # tidak bisa tidak sengaja mengunci dirinya sendiri dari fitur export.
    export_allowed_roles = Column(Text, nullable=False, default="it_admin,compliance")
    updated_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_export_allowed_roles(self) -> list[str]:
        raw = self.export_allowed_roles or ""
        return [r.strip() for r in raw.split(",") if r.strip()]


class FaqEntry(Base):
    """
    FAQ Helpdesk — SRS FCR-003 poin 10.b: "Sistem memproses menggunakan RAG:
    ... b) FAQ helpdesk". Beda dari HelpdeskTicket (itu tiket ESKALASI KELUAR
    ke manusia), tabel ini isinya SUMBER pengetahuan yang ditarik MASUK ke
    RAG — jadi tiap chat bisa terjawab dari FAQ ini walau user tidak
    upload dokumen apa pun (beda dari kb_general yang di-scope per chat_id).

    Postgres di sini jadi SOURCE OF TRUTH yang gampang di-list/edit/hapus
    lewat UI admin; isinya (question+answer digabung jadi satu teks)
    diindeks ULANG ke koleksi ChromaDB terpisah "kb_faq_helpdesk" (lihat
    rag/vectorstore.py: index_faq_entry()) supaya bisa di-retrieve semantik,
    sama seperti dokumen upload biasa.
    """
    __tablename__ = "faq_entries"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    author = relationship("User")

class KbDocument(Base):
    """
    Multi-Tenant Knowledge Base — SRS poin 11 & hal. 68: "Knowledge Base
    dapat dibuatkan terpisah untuk setiap divisi... Terdapat Knowledge Base
    Company Wide... Metadata dokumen dapat disimpan pada relation database
    minimum terdapat informasi nama dokumen, versi, update time."

    divisi NULL = dokumen Company Wide (SRS: "klasifikasi informasi umum
    internal seperti POJK, Peraturan BEI, SK", bisa diakses SEMUA divisi).
    divisi terisi = cuma bisa diakses user divisi itu (SRS hal. 14: "Data
    yang di-upload oleh masing-masing divisi hanya dapat diakses oleh
    divisi tersebut").

    Isi teksnya sendiri diindeks ke ChromaDB (koleksi "kb_divisi", metadata
    {"divisi": ...}) — pola yang sama dengan FaqEntry/kb_faq_helpdesk; baris
    di sini cuma metadata (nama file, siapa upload, kapan), bukan isi
    dokumen mentah.
    """
    __tablename__ = "kb_documents"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    divisi = Column(String, nullable=True)  # None = Company Wide
    filename = Column(String, nullable=False)
    chunk_count = Column(Integer, nullable=False, default=0)
    uploaded_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    uploader = relationship("User")
