"""Rate limiting login sederhana, in-memory (RAM) — cukup untuk skala internship, produksi biasanya pindah ke Redis."""
import time
from fastapi import HTTPException

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60  # 15 menit

_failed_attempts: dict[str, list[float]] = {}  # { "email@contoh.com": [timestamp1, timestamp2, ...] }


def check_rate_limit(email: str):
    """Panggil di AWAL proses login, sebelum cek password."""
    now = time.time()
    attempts = _failed_attempts.get(email, [])

    attempts = [t for t in attempts if now - t < WINDOW_SECONDS]  # buang percobaan di luar jendela waktu
    _failed_attempts[email] = attempts

    if len(attempts) >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail=f"Terlalu banyak percobaan gagal. Coba lagi dalam {WINDOW_SECONDS // 60} menit.",
        )


def record_failed_attempt(email: str):
    """Panggil setiap kali login gagal (password salah)."""
    now = time.time()
    _failed_attempts.setdefault(email, []).append(now)


def clear_attempts(email: str):
    """Panggil setelah login BERHASIL — reset hitungan percobaan gagal."""
    _failed_attempts.pop(email, None)
