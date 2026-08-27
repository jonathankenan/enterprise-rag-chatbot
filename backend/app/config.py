"""Konfigurasi terpusat, dibaca dari .env — jangan hardcode credential di sini."""
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

    # Bahasa jawaban default — instruksi relatif saja tidak cukup buat model on-prem, lihat build_prompt() di llm/router.py
    response_language: str = "Bahasa Indonesia"

    # Vector DB
    chroma_persist_dir: str = "./chroma_data"

    # Ambang relatif (poin similarity) dari peringkat 1 supaya chunk lain masih layak jadi citation (SRS poin 12.a), lihat retrieve_context()
    citation_similarity_gap: int = 15

    # Guardrail — dipisah koma di .env, contoh: "rahasia,internal"
    sensitive_keywords: str = "rahasia,internal,confidential"

    # Guardrail — batas panjang prompt & response, commercial lebih ketat karena charge per token (SRS Model Usage Policy poin b, BR-04)
    max_prompt_length_onprem: int = 6000
    max_prompt_length_commercial: int = 3000
    max_response_tokens_commercial: int = 1024

    # Guardrail — rate limiting per-user endpoint chat (SRS Model Usage Policy poin c-d)
    chat_rate_limit_max_messages: int = 30
    chat_rate_limit_window_seconds: int = 60

    # Guardrail — enkripsi at-rest isi pesan chat (SRS hal. 16 poin 3.k), kosong = key sementara hilang tiap restart (dev-friendly)
    message_encryption_key: str = ""

    # Eskalasi otomatis ke human helpdesk (SRS poin 7) kalau confidence_score di bawah ambang ini; None (general chat) tidak pernah memicu
    escalation_confidence_threshold: int = 20

    # SSO — simulasi LDAP M365 BEI (SRS hal. 64) pakai Azure AD tenant developer/pribadi, bukan tenant BEI asli
    azure_client_id: str = ""
    azure_tenant_id: str = ""
    azure_client_secret: str = ""
    azure_redirect_uri: str = "http://localhost:3000/auth/azure/callback"  # harus persis sama dengan yang didaftarkan di Azure Portal

    @property
    def sensitive_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.sensitive_keywords.split(",") if k.strip()]

    class Config:
        env_file = ".env"


settings = Settings()
