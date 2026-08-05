"""
[PENANGGUNG JAWAB: Anggota B]
Rate limiting sederhana untuk mencegah brute-force pada endpoint login.
Implementasi in-memory (disimpan di RAM) — cukup untuk skala internship.
Untuk produksi sungguhan, biasanya dipindah ke Redis agar tidak hilang saat restart
dan bisa dipakai bersama di banyak server.
"""
import time
from fastapi import HTTPException

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60  # 15 menit

# Menyimpan: { "email@contoh.com": [timestamp1, timestamp2, ...] }
_failed_attempts: dict[str, list[float]] = {}


def check_rate_limit(email: str):
    """Panggil di AWAL proses login, sebelum cek password."""
    now = time.time()
    attempts = _failed_attempts.get(email, [])

    # Buang percobaan yang sudah di luar jendela waktu (lebih dari 15 menit lalu)
    attempts = [t for t in attempts if now - t < WINDOW_SECONDS]
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