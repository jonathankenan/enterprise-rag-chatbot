"""
[PENANGGUNG JAWAB: Anggota B]
Skema Pydantic — bentuk data yang masuk (request) & keluar (response) dari API.
"""
from datetime import datetime
from pydantic import BaseModel, EmailStr


# ---- Auth ----
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


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
