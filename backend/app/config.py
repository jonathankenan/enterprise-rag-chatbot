"""
Konfigurasi terpusat, dibaca dari file .env.
Jangan hardcode credential di sini — semua lewat environment variable.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str

    # Auth
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # LLM Commercial
    gemini_api_key: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = ""
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    commercial_provider: str = "groq"  # default untuk fitur internal (mis. auto-generate judul chat)

    # LLM On-Premise
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    # Vector DB
    chroma_persist_dir: str = "./chroma_data"

    # Guardrail — dipisah koma di .env, contoh: "rahasia,internal"
    sensitive_keywords: str = "rahasia,internal,confidential"

    # Guardrail — batas panjang prompt & response (SRS Model Usage Policy poin b).
    # Ambang untuk commercial sengaja lebih ketat daripada on-prem karena
    # langsung berkorelasi dengan biaya token (BR-04: penggunaan recurring
    # cost yang efektif) — on-prem tidak charge per token jadi lebih longgar.
    max_prompt_length_onprem: int = 6000
    max_prompt_length_commercial: int = 3000
    max_response_tokens_commercial: int = 1024

    # Guardrail — rate limiting per-user di endpoint chat (SRS Model Usage
    # Policy poin c-d: "Rate limiting" & "API limiter", dikonfigurasi IT admin).
    chat_rate_limit_max_messages: int = 30
    chat_rate_limit_window_seconds: int = 60

    # Guardrail — enkripsi at-rest untuk isi pesan chat (SRS FCR-003 hal. 16,
    # poin 3.k). Isi dengan Fernet.generate_key() (lihat app/guardrail/encryption.py
    # untuk penjelasan lengkap). Kalau dibiarkan kosong, sistem tetap jalan
    # (dev-friendly) tapi pakai key SEMENTARA yang hilang tiap restart.
    message_encryption_key: str = ""

    # Eskalasi otomatis ke human helpdesk (SRS FCR-003 poin 7). Jawaban AI
    # dengan confidence_score DI BAWAH ambang ini otomatis bikin tiket.
    # Confidence None (percakapan umum tanpa RAG) TIDAK pernah memicu ini —
    # itu bukan "jawaban tidak meyakinkan", cuma tidak relevan diberi skor.
    #
    # Nilai 20 (turun dari 30 semula) — dikalibrasi ulang setelah confidence
    # diganti dari self-report LLM ke retrieval similarity (cosine). Skala
    # keduanya BEDA: cosine similarity untuk konten yang genuinely relevan
    # tapi beda kata-kata wajar cuma 30-60% (LLM self-report dulu cenderung
    # jauh lebih "murah hati"). Ambang 30 di skala baru berisiko meng-eskalasi
    # jawaban yang sebenarnya cukup baik. Ini kalibrasi awal dari sampel kecil
    # — sebaiknya ditinjau ulang setelah ada data pemakaian nyata dari halaman
    # /helpdesk (kalau tiket yang masuk mayoritas ternyata jawabannya sudah
    # bagus, naikkan; kalau tiket yang seharusnya masuk malah lolos, turunkan).
    escalation_confidence_threshold: int = 20

    # SSO — simulasi LDAP M365 BEI (SRS hal. 64) pakai Azure AD (Microsoft
    # Entra ID) beneran, tapi tenant developer/pribadi, bukan tenant BEI
    # asli (yang tidak bisa diakses proyek magang ini). Default kosong
    # supaya app tetap jalan sebelum di-setup (tombol "Login Microsoft"
    # otomatis disembunyikan di frontend kalau kosong).
    azure_client_id: str = ""
    azure_tenant_id: str = ""
    azure_client_secret: str = ""
    # HARUS PERSIS SAMA dengan Redirect URI yang didaftarkan di Azure Portal
    # (App Registration > Authentication) — kalau beda walau 1 karakter,
    # Microsoft menolak tukar authorization code dengan token.
    azure_redirect_uri: str = "http://localhost:3000/auth/azure/callback"

    @property
    def sensitive_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.sensitive_keywords.split(",") if k.strip()]

    class Config:
        env_file = ".env"


settings = Settings()