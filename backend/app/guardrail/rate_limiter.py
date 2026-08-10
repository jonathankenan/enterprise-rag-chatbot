"""
[PENANGGUNG JAWAB: Anggota B]
Rate limiting per-user untuk endpoint chat (F2-04 / SRS Model Usage Policy
poin c-d: "Rate limiting" & "API limiter", dikonfigurasi oleh IT admin).

Implementasi in-memory (disimpan di RAM) — pola sama seperti auth/rate_limit.py,
cukup untuk skala internship. Untuk produksi sungguhan idealnya dipindah ke
Redis: penyimpanan in-memory berarti hitungan reset tiap kali server restart,
dan tidak konsisten kalau backend dijalankan multi-instance di belakang load
balancer (tiap instance punya hitungannya sendiri-sendiri).
"""
import time
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.guardrail.audit_log import log_guardrail_event, EventType

# Menyimpan: { "user_id": [timestamp1, timestamp2, ...] }
_message_timestamps: dict[str, list[float]] = {}


def check_chat_rate_limit(db: Session, user_id: str):
    """
    Panggil di AWAL endpoint kirim pesan — SEBELUM guardrail lain (filter kata
    kunci, prompt injection, PII, dst) supaya user yang sedang di-rate-limit
    tidak ikut membebani pemeriksaan yang lebih mahal (apalagi panggilan LLM).
    """
    now = time.time()
    timestamps = _message_timestamps.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < settings.chat_rate_limit_window_seconds]

    if len(timestamps) >= settings.chat_rate_limit_max_messages:
        log_guardrail_event(
            db, user_id, EventType.RATE_LIMIT_HIT,
            detail="chat_message_rate_limit",
            metadata={
                "max_messages": settings.chat_rate_limit_max_messages,
                "window_seconds": settings.chat_rate_limit_window_seconds,
            },
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Terlalu banyak pesan dalam waktu singkat. Maksimal "
                f"{settings.chat_rate_limit_max_messages} pesan per "
                f"{settings.chat_rate_limit_window_seconds} detik. Coba lagi sebentar lagi."
            ),
        )

    timestamps.append(now)
    _message_timestamps[user_id] = timestamps
