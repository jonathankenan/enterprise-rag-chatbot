"""Konektor ke LLM "on-premise" via Ollama lokal — simulasi "Foundation Model on-prem" dari SRS. Prasyarat: ollama pull llama3 && ollama serve."""
import httpx

from app.config import settings


async def call_local_llm(prompt: str) -> str:
    """Kirim prompt ke Ollama yang jalan lokal, kembalikan jawaban teks."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                # 2026-08-26: sebelumnya "options" TIDAK pernah dikirim sama
                # sekali, jadi Ollama memakai defaultnya sendiri -- dan default
                # itu tidak cocok untuk RAG:
                #
                #   * num_ctx default 4096 (Ollama 0.32). build_prompt() sudah
                #     memotong PROVIDED CONTEXT di 15.000 karakter (~3.750
                #     token) SEBELUM ditambah aturan (~800 token) dan riwayat
                #     percakapan. Untuk query tanpa identifier -- "ringkas
                #     semua dokumen", sintesis multi-dokumen -- totalnya lewat
                #     4096, dan Ollama memotongnya DIAM-DIAM. Tidak ada error,
                #     tidak ada peringatan; jawabannya cuma jadi salah karena
                #     sebagian konteks tidak pernah sampai ke model.
                #
                #   * temperature default 0.8. Terlalu tinggi untuk sistem yang
                #     tugasnya menyalin angka dari dokumen. Diukur pada dua
                #     kasus tabel NEXUS, temperature ternyata TIDAK mengubah
                #     benar/salahnya (5/5 dan 0/5 di 0.8 maupun 0) -- jadi ini
                #     bukan perbaikan akurasi, melainkan pengurangan variasi
                #     jawaban antar-run untuk pertanyaan yang sama. Tidak
                #     di-nol-kan karena chatbot ini juga dipakai untuk
                #     percakapan umum (SRS: "Generic ChatBot"), yang jadi kaku
                #     kalau sepenuhnya deterministik.
                "options": {
                    "num_ctx": settings.ollama_num_ctx,
                    "temperature": settings.ollama_temperature,
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()
