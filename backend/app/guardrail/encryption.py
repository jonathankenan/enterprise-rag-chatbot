"""Enkripsi at-rest isi pesan chat (SRS hal. 16 poin 3.k) via Fernet — in-transit sudah tercakup HTTPS bawaan httpx."""
import warnings
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

if settings.message_encryption_key:
    _fernet = Fernet(settings.message_encryption_key.encode())
else:
    # Key sementara kalau MESSAGE_ENCRYPTION_KEY kosong -- hilang tiap restart, sengaja supaya operator sadar wajib set key permanen
    _fernet = Fernet(Fernet.generate_key())
    warnings.warn(
        "MESSAGE_ENCRYPTION_KEY belum di-set di .env — memakai key SEMENTARA "
        "yang dibuat otomatis saat proses ini start. Pesan yang dienkripsi "
        "pada sesi ini TIDAK BISA didekripsi lagi setelah server di-restart. "
        "Untuk pemakaian yang datanya perlu bertahan, generate key permanen "
        "(Fernet.generate_key()) dan simpan di .env / secret manager.",
        stacklevel=2,
    )


def encrypt_text(plaintext: str) -> str:
    """Enkripsi teks, kembalikan ciphertext sebagai string (aman disimpan di kolom Text)."""
    if not plaintext:
        return plaintext
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_text(value: str) -> str:
    """Dekripsi ciphertext ke teks asli — kalau bukan ciphertext valid (data lama pra-enkripsi), kembalikan apa adanya."""
    if not value:
        return value
    try:
        return _fernet.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return value
