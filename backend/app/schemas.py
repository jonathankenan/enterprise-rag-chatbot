"""
[PENANGGUNG JAWAB: Anggota B]
Skema Pydantic — bentuk data yang masuk (request) & keluar (response) dari API.
"""
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator, model_validator

from app.config import settings

# Provider yang dianggap "commercial" untuk keperluan ambang batas panjang
# prompt — duplikat kecil dari COMMERCIAL_PROVIDERS di llm/router.py, sengaja
# tidak di-import langsung dari sana supaya schemas.py (lapisan validasi
# request, dijalankan paling awal) tidak bergantung ke modul llm/.
_COMMERCIAL_PROVIDERS = {"groq", "gemini", "mistral", "cloudflare"}


_SPECIAL_CHARS = set("!@#$%^&*()_+-=[]{}|;:'\",.<>/?`~\\")


def validate_password_strength(password: str) -> str:
    """
    Aturan password sesuai SRS ISR-002.a/b: kompleks (huruf besar, huruf
    kecil, angka, karakter khusus) dan minimal 12 karakter. Sama persis
    dengan validasi di frontend (register/page.jsx & change-password/page.jsx),
    supaya tidak bisa "dilewati" dengan memanggil API langsung tanpa lewat UI.
    """
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
    # SRS ISR-001.g: info login sebelumnya + percobaan gagal sejak saat itu
    previous_login_at: datetime | None = None
    failed_attempts_since_last_login: int = 0
    # SRS ISR-002.c: true kalau password sudah lewat 90 hari, frontend WAJIB
    # arahkan user ke halaman ganti password (bukan langsung ke /chat)
    password_expired: bool = False
    # SRS ISR-001.d: password sudah benar, tapi login BELUM SELESAI — kalau
    # salah satu true, `access_token` di atas sengaja None (belum boleh
    # dianggap login), frontend harus arahkan ke alur MFA memakai `mfa_token`.
    mfa_required: bool = False           # akun sudah punya MFA aktif, minta kode TOTP
    mfa_setup_required: bool = False     # akun WAJIB MFA tapi belum pernah setup
    mfa_token: str | None = None         # token sementara (5 menit), khusus buat 2 endpoint MFA di bawah


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


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    divisi: str | None = None  # None = tidak terikat 1 divisi (atau, khusus IT_ADMIN, artinya admin GLOBAL)

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
        from app.models import Role  # import lokal — hindari import melingkar di level modul
        if v not in Role.ALL:
            raise ValueError(f"Role tidak valid. Pilihan: {', '.join(Role.ALL)}")
        return v


class UserDivisiUpdateRequest(BaseModel):
    divisi: str | None  # None = lepas dari divisi manapun (utk IT_ADMIN berarti jadi admin GLOBAL)

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
    updated_by: str | None
    updated_at: datetime | None

    class Config:
        from_attributes = True


class UpdateExportRolesRequest(BaseModel):
    roles: list[str]


# ---- Chat ----
class ChatCreate(BaseModel):
    title: str | None = "Percakapan Baru"


class ChatResponse(BaseModel):
    id: str
    title: str
    created_at: datetime

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
        """
        Guardrail F2-04 / SRS Model Usage Policy poin b: batasi panjang prompt
        supaya tidak membengkakkan biaya token LLM commercial tanpa kendali
        (BR-04 — penggunaan recurring cost yang efektif). Pakai model_validator
        (bukan field_validator biasa) karena ambangnya butuh nilai llm_provider,
        bukan cuma content saja.
        """
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


class ChatReplyResponse(BaseModel):
    """Dikembalikan setelah user kirim pesan — berisi jawaban AI + metadata."""
    reply: str
    llm_used: str
    is_sensitive: bool
    confidence_score: int | None = None
    pii_detected: bool = False
    sources: list[str] = []
    new_title: str | None = None
    message_id: str | None = None
    # FCR-003 poin 7: "sistem MENAWARKAN eskalasi" — bukan langsung bikin
    # tiket. True kalau confidence di bawah ambang, dipakai frontend untuk
    # tampilkan banner tanya user, BUKAN auto-create tiket (lihat
    # helpdesk/routes.py: POST /tickets, dipanggil user kalau setuju).
    escalation_offered: bool = False


# ---- Helpdesk (FCR-003 poin 7 — eskalasi ke human helpdesk) ----
class CreateTicketRequest(BaseModel):
    message_id: str  # jawaban AI low-confidence yang user setuju dieskalasi


class TicketResponse(BaseModel):
    id: str
    chat_id: str
    user_id: str
    user_email: str
    confidence_score: int | None
    status: str
    created_at: datetime


class HelpdeskMessageResponse(BaseModel):
    id: str
    ticket_id: str
    sender_role: str
    sender_id: str | None
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class SendTicketMessageRequest(BaseModel):
    content: str


class TicketDetailResponse(TicketResponse):
    chat_title: str
    messages: list[MessageResponse]  # riwayat chat AI (konteks awal, read-only)
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
