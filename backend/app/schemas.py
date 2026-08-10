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


def validate_password_strength(password: str) -> str:
    """
    Aturan password — sama persis dengan validasi di frontend (register/page.jsx),
    supaya tidak bisa "dilewati" dengan memanggil API langsung tanpa lewat UI.
    """
    if len(password) < 8:
        raise ValueError("Password minimal 8 karakter")
    if not any(c.isalpha() for c in password):
        raise ValueError("Password harus mengandung huruf")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password harus mengandung angka")
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
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str

    class Config:
        from_attributes = True


# ---- Chat ----
class ChatCreate(BaseModel):
    title: str | None = "Percakapan Baru"


class ChatResponse(BaseModel):
    id: str
    title: str
    created_at: datetime

    class Config:
        from_attributes = True


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