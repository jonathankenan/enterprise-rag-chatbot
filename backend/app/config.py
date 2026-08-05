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

    @property
    def sensitive_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.sensitive_keywords.split(",") if k.strip()]

    class Config:
        env_file = ".env"


settings = Settings()