"""Skema Pydantic — bentuk data yang masuk (request) & keluar (response) dari API."""
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator, model_validator

from app.config import settings

_COMMERCIAL_PROVIDERS = {"groq", "gemini", "mistral", "cloudflare"}  # duplikat kecil dari llm/router.py, sengaja lepas import biar schemas.py tidak bergantung modul llm/


_SPECIAL_CHARS = set("!@#$%^&*()_+-=[]{}|;:'\",.<>/?`~\\")


def validate_password_strength(password: str) -> str:
    """SRS ISR-002.a/b: kompleks + minimal 12 karakter — sama persis dengan validasi frontend, supaya tidak bisa dilewati lewat API langsung."""
    if len(password) < 12:
        raise ValueError("Password minimal 12 karakter")
    if not any(c.isupper() for c in password):
        raise ValueError("Password harus mengandung huruf besar")
    if not any(c.islower() for c in password):
        raise ValueError("Password harus mengandung huruf kecil")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password harus mengandung angka")
    if not any(c in _SPECIAL_CHARS for c in password):
        raise ValueError("Password harus mengandung karakter khusus (mis. ! @ # $ %)")
    return password


# ---- Auth ----
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    role: str | None = None    # divalidasi ke Role.SELF_REGISTERABLE
    divisi: str | None = None  # divalidasi ke Divisi.ALL

    @field_validator("role")
    @classmethod
    def check_self_registerable(cls, v: str | None) -> str | None:
        from app.models import Role
        if v is not None and v not in Role.SELF_REGISTERABLE:
            raise ValueError("Role tersebut tidak bisa dipilih sendiri, hubungi IT Admin")
        return v

    @field_validator("divisi")
    @classmethod
    def check_valid_divisi(cls, v: str | None) -> str | None:
        from app.models import Divisi
        if v is not None and v not in Divisi.ALL:
            raise ValueError(f"Divisi tidak valid. Pilihan: {', '.join(Divisi.ALL)}")
        return v

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    previous_login_at: datetime | None = None  # SRS ISR-001.g
    failed_attempts_since_last_login: int = 0
    password_expired: bool = False  # SRS ISR-002.c: true = frontend wajib arahkan ke ganti password
    # SRS ISR-001.d: kalau salah satu true, access_token sengaja None, frontend arahkan ke alur MFA pakai mfa_token
    mfa_required: bool = False           # akun sudah punya MFA aktif, minta kode TOTP
    mfa_setup_required: bool = False     # akun WAJIB MFA tapi belum pernah setup
    mfa_token: str | None = None         # token sementara (5 menit), khusus 2 endpoint MFA di bawah


class MfaSetupRequest(BaseModel):
    mfa_token: str


class MfaSetupResponse(BaseModel):
    secret: str            # buat entry manual di aplikasi authenticator
    qr_code_base64: str    # data URI PNG, tinggal taruh di <img src="...">


class MfaSetupConfirmRequest(BaseModel):
    mfa_token: str
    secret: str
    code: str


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str


# ---- SSO Azure AD (simulasi LDAP M365 BEI, SRS hal. 64) ----
class AzureLoginUrlResponse(BaseModel):
    auth_url: str


class AzureCallbackRequest(BaseModel):
    code: str


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    divisi: str | None = None  # None = tidak terikat 1 divisi (IT_ADMIN: admin global)

    class Config:
        from_attributes = True


# ---- Manajemen user (dibatasi Role.IT_ADMIN, lihat admin/routes.py) ----
class AdminUserResponse(UserResponse):
    created_at: datetime


class UserRoleUpdateRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def check_valid_role(cls, v: str) -> str:
        from app.models import Role  # import lokal — hindari import melingkar
        if v not in Role.ALL:
            raise ValueError(f"Role tidak valid. Pilihan: {', '.join(Role.ALL)}")
        return v


class UserDivisiUpdateRequest(BaseModel):
    divisi: str | None  # None = lepas dari divisi manapun (IT_ADMIN jadi admin global)

    @field_validator("divisi")
    @classmethod
    def check_valid_divisi(cls, v: str | None) -> str | None:
        from app.models import Divisi
        if v is not None and v not in Divisi.ALL:
            raise ValueError(f"Divisi tidak valid. Pilihan: {', '.join(Divisi.ALL)}")
        return v


# ---- System settings (dibatasi Role.IT_ADMIN — SRS FCR-003 Rules poin 2: force-stop LLM Commercial) ----
class SystemSettingsResponse(BaseModel):
    commercial_llm_force_stopped: bool
    export_allowed_roles: list[str]
    chat_rate_limit_max_messages: int
    chat_rate_limit_window_seconds: int
    chat_retention_days: int | None
    updated_by: str | None
    updated_at: datetime | None

    class Config:
        from_attributes = True


class UpdateExportRolesRequest(BaseModel):
    roles: list[str]


# ---- SRS poin 4.c-d: rate limit & API limiter dikonfigurasi IT Admin (dulu cuma .env) ----
class UpdateRateLimitRequest(BaseModel):
    max_messages: int
    window_seconds: int

    @field_validator("max_messages", "window_seconds")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Nilai harus lebih besar dari 0")
        return v


# ---- SRS poin 6: konfigurasi retensi data historis ----
class UpdateRetentionRequest(BaseModel):
    retention_days: int | None  # None = tanpa batas (nonaktifkan retensi)

    @field_validator("retention_days")
    @classmethod
    def must_be_positive_or_none(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("Retensi harus lebih besar dari 0 hari, atau kosongkan untuk tanpa batas")
        return v


class RetentionApplyResponse(BaseModel):
    archived_count: int


# ---- Chat ----
class ChatCreate(BaseModel):
    title: str | None = "Percakapan Baru"


class ChatResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    archived: bool = False

    class Config:
        from_attributes = True


class ChatRenameRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Judul chat tidak boleh kosong.")
        if len(v) > 100:
            raise ValueError("Judul chat maksimal 100 karakter.")
        return v


class MessageCreate(BaseModel):
    chat_id: str
    content: str
    llm_provider: str = "auto"  # "auto" | "on-prem" | "groq" | "gemini"

    @model_validator(mode="after")
    def check_content_length(self):
        """Guardrail F2-04 / SRS Model Usage Policy poin b — ambang beda tergantung provider, makanya model_validator bukan field_validator."""
        limit = (
            settings.max_prompt_length_commercial
            if self.llm_provider in _COMMERCIAL_PROVIDERS
            else settings.max_prompt_length_onprem
        )
        if len(self.content) > limit:
            raise ValueError(
                f"Pesan terlalu panjang ({len(self.content)} karakter). "
                f"Maksimal {limit} karakter untuk provider '{self.llm_provider}'."
            )
        return self


class MessageResponse(BaseModel):
    id: str
    sender: str
    content: str
    llm_used: str | None
    confidence_score: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class SourceCitation(BaseModel):
    """SRS poin 12.a: source references — satu entri per dokumen/FAQ unik (bukan per chunk), lihat _build_source_citations() di chat/routes.py."""
    label: str  # nama yang ditampilkan ke user: "file.pdf (hal. 3, 7)", atau "FAQ Helpdesk"
    filename: str | None = None
    source_type: str  # "chat_document" | "kb_divisi" | "faq"
    pages: list[int] = []  # nomor halaman (1-indexed) sumber chunk, urut tanpa duplikat; kosong utk FAQ atau kalau halaman tidak bisa dipastikan


class ChatReplyResponse(BaseModel):
    """Dikembalikan setelah user kirim pesan — berisi jawaban AI + metadata."""
    reply: str
    llm_used: str
    is_sensitive: bool
    confidence_score: int | None = None
    pii_detected: bool = False
    sources: list[SourceCitation] = []
    new_title: str | None = None
    message_id: str | None = None
    escalation_offered: bool = False  # SRS poin 7: sistem MENAWARKAN eskalasi, bukan auto-create tiket (lihat helpdesk/routes.py POST /tickets)
    intent: str = "question"  # SRS hal. 17 poin 9.a: diekspos ke response supaya bisa diverifikasi lewat testing


# ---- Helpdesk (FCR-003 poin 7 — eskalasi ke human helpdesk) ----
class CreateTicketRequest(BaseModel):
    """Tiket dibuat saat user MENGIRIM pesan pertama, bukan saat membuka halaman — makanya `content` yang wajib, bukan chat_id."""
    content: str | None = None            # pesan pertama; wajib untuk jalur "Hubungi Admin"
    attached_chat_id: str | None = None   # percakapan AI yang dilampirkan ke pesan pertama
    chat_id: str | None = None            # cuma dipakai jalur eskalasi confidence rendah
    message_id: str | None = None         # idem — jawaban AI yang memicu tawaran eskalasi


class TicketResponse(BaseModel):
    id: str
    chat_id: str | None
    user_id: str
    user_email: str
    confidence_score: int | None
    target_divisi: str | None = None  # None = ditangani IT Admin global
    status: str
    created_at: datetime


class HelpdeskMessageResponse(BaseModel):
    id: str
    ticket_id: str
    sender_role: str
    sender_id: str | None
    content: str
    attached_chat_id: str | None = None
    attached_chat_title: str | None = None  # diisi manual di route (bukan kolom DB) supaya UI tidak perlu query kedua
    created_at: datetime

    class Config:
        from_attributes = True


class SendTicketMessageRequest(BaseModel):
    content: str
    attached_chat_id: str | None = None


class TicketDetailResponse(TicketResponse):
    chat_title: str | None = None
    ticket_messages: list[HelpdeskMessageResponse]  # percakapan user<->admin


# ---- Audit log (dibatasi Role.ADMIN / Role.COMPLIANCE, lihat guardrail/routes.py) ----
class AuditLogResponse(BaseModel):
    id: str
    user_id: str | None
    event_type: str
    severity: str
    detail: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class AuditSummaryResponse(BaseModel):
    since_hours: int
    counts_by_type: dict[str, int]

# ---- FAQ Helpdesk (dibatasi Role.IT_ADMIN — SRS poin 10.b: sumber RAG) ----
class CreateFaqRequest(BaseModel):
    question: str
    answer: str

    @field_validator("question", "answer")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Tidak boleh kosong")
        return v.strip()


class FaqEntryResponse(BaseModel):
    id: str
    question: str
    answer: str
    created_by: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class FaqBulkImportResponse(BaseModel):
    filename: str
    created: list[FaqEntryResponse]
    count: int


# ---- Multi-Tenant Knowledge Base (SRS poin 11 & hal. 68) ----
class KbDocumentResponse(BaseModel):
    id: str
    divisi: str | None  # None = Company Wide
    filename: str
    chunk_count: int
    uploaded_by: str | None
    created_at: datetime

    class Config:
        from_attributes = True
