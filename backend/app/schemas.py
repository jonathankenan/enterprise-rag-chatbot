"""
[PENANGGUNG JAWAB: Anggota B]
Skema Pydantic — bentuk data yang masuk (request) & keluar (response) dari API.
"""
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator


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


class MessageResponse(BaseModel):
    id: str
    sender: str
    content: str
    llm_used: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatReplyResponse(BaseModel):
    """Dikembalikan setelah user kirim pesan — berisi jawaban AI + metadata."""
    reply: str
    llm_used: str          # "on-prem" atau "commercial"
    is_sensitive: bool     # apakah terdeteksi sebagai data sensitif
    sources: list[str] = []  # potongan referensi dari RAG (opsional untuk F1)