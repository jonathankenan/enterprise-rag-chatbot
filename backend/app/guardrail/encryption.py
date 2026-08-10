"""
[PENANGGUNG JAWAB: Anggota B]
Enkripsi AT REST untuk isi pesan chat (SRS FCR-003 hal. 16, poin 3.k:
"Enkripsi data personal in transit & at rest, khususnya apabila menggunakan
LLM COMMERCIAL"). Sisi IN TRANSIT sudah otomatis tercakup lewat HTTPS ke
semua provider commercial (httpx memverifikasi TLS secara default) — modul
ini menutup sisi AT REST: isi pesan disimpan terenkripsi di kolom
`messages.content` pada Postgres, bukan plaintext.

Pendekatan: symmetric encryption pakai Fernet (dari library `cryptography`,
sudah otomatis terpasang sebagai dependency `python-jose[cryptography]` —
tidak perlu tambah dependency baru). Fernet dipilih (bukan skema custom)
karena sudah menyertakan authenticated encryption (AES128-CBC + HMAC) dan
key rotation-friendly, tanpa perlu kita implementasi primitif kripto sendiri
yang gampang salah.

Cara pakai key:
- Set MESSAGE_ENCRYPTION_KEY di .env dengan hasil dari:
      python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
- Kalau TIDAK di-set (mis. saat development lokal supaya tetap "just works"),
  modul ini generate key SEMENTARA saat proses start dan mencetak WARNING
  yang jelas — bukan diam-diam membisukan risikonya. Key sementara ini
  hilang setiap kali server restart, jadi PESAN YANG DIENKRIPSI SESI INI
  TIDAK BISA DIDEKRIPSI LAGI setelah restart kalau key tidak di-set permanen.
  Ini konsekuensi yang DISENGAJA: memaksa siapa pun yang menjalankan sistem
  ini sungguhan sadar bahwa key wajib di-set & disimpan aman (idealnya di
  secret manager, bukan file .env yang ikut ter-commit), bukan cuma warning
  yang gampang diabaikan di log.

Catatan kompatibilitas mundur (PENTING kalau database sudah punya data):
Pesan yang SUDAH tersimpan sebagai plaintext SEBELUM modul ini dipasang
bukan ciphertext Fernet yang valid. decrypt_text() menangani ini secara
graceful: kalau gagal didekripsi, nilai mentah yang tersimpan dikembalikan
apa adanya (dianggap data lama pra-enkripsi), supaya aplikasi tidak crash
membaca riwayat chat lama. INI BUKAN MIGRASI DATA SESUNGGUHNYA — pesan lama
tersebut TETAP plaintext selamanya di database, cuma tidak bikin error saat
dibaca. Kalau butuh migrasi data lama jadi terenkripsi juga, perlu script
terpisah yang baca-ulang & tulis-ulang tiap baris (di luar cakupan modul ini).
"""
import warnings
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

if settings.message_encryption_key:
    _fernet = Fernet(settings.message_encryption_key.encode())
else:
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
    """
    Dekripsi ciphertext kembali ke teks asli. Kalau `value` ternyata bukan
    ciphertext Fernet yang valid (mis. data lama pra-enkripsi, atau data
    korup), kembalikan apa adanya — lihat catatan kompatibilitas mundur di
    docstring modul ini.
    """
    if not value:
        return value
    try:
        return _fernet.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return value
