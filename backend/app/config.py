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

    # Panjang context window yang diminta ke Ollama. HARUS lebih besar dari
    # prompt terpanjang yang bisa dihasilkan build_prompt() -- konteks dipotong
    # di 15.000 karakter (~3.750 token) DITAMBAH aturan (~800) dan riwayat.
    # Kalau kurang, Ollama memotong prompt tanpa error apa pun dan jawabannya
    # jadi salah karena sebagian konteks tidak pernah terbaca.
    #
    # Ada harganya di VRAM: diukur pada GTX 1660 6GB, qwen2.5:7b Q4_K_M naik
    # dari 5,12 GB (ctx 4096) ke 5,38 GB (ctx 8192). Kartu itu cuma sanggup
    # menampung 4,19 GB, jadi sisanya jalan di CPU dan kecepatan turun ke
    # sekitar sepertiga. Kalau ganti model/GPU, cek ulang lewat /api/ps
    # apakah size_vram masih sama dengan size total.
    ollama_num_ctx: int = 8192

    # 0.8 (default Ollama) terlalu tinggi untuk sistem yang menyalin angka dari
    # dokumen. Tidak di-nol-kan: chatbot ini juga melayani percakapan umum.
    ollama_temperature: float = 0.2

    # Bahasa jawaban default (SRS: aplikasi berbahasa Indonesia).
    #
    # 2026-08-25: instruksi relatif ("jawab dalam bahasa yang sama dengan
    # user") TIDAK cukup untuk model on-prem. Seluruh prompt sistem dan
    # PROVIDED CONTEXT berbahasa Inggris, jadi model condong ke Inggris.
    # Ketika instruksi diperkuat jadi "abaikan bahasa Inggris di sekitarmu",
    # qwen2.5 malah jatuh ke prior bahasa aslinya dan menjawab dalam
    # MANDARIN -- instruksi itu cuma bilang ke mana JANGAN pergi, bukan ke
    # mana harus pergi. Menyebut bahasa targetnya eksplisit memberi jangkar
    # yang jelas. Lihat build_prompt() di llm/router.py.
    response_language: str = "Bahasa Indonesia"

    # Vector DB
    chroma_persist_dir: str = "./chroma_data"

    # Seberapa jauh (poin similarity) sebuah chunk boleh tertinggal dari
    # peringkat 1 dan masih layak disebut sebagai sumber (SRS FCR-003 poin
    # 12.a). Ambang RELATIF, bukan absolut: jawaban dari satu kecocokan
    # presisi menyisakan satu citation, jawaban yang memang butuh sintesis
    # beberapa dokumen tetap mengutip semuanya karena skornya berdekatan.
    # Lihat retrieve_context() di rag/vectorstore.py.
    #
    # 2026-08-26: 15 -> 5. Diukur pada korpus satu dokumen (Project_NEXUS,
    # 39 chunk), SELURUH top-10 cuma membentang 8 poin (74.69%..66.59%) --
    # floor 15 poin jatuh di 59.69% dan tidak pernah membuang satu chunk pun.
    # all-MiniLM-L6-v2 pada dokumen yang seluruh isinya satu topik memang
    # menghasilkan pita similarity sempit. Daya pisah utama sekarang ada di
    # saringan leksikal (_has_query_id/_is_toc di retrieve_context); angka ini
    # tinggal jadi pengaman untuk query TANPA identifier, yang tidak tersentuh
    # saringan itu.
    citation_similarity_gap: int = 5

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

    # Direktori Azure AD TIRUAN untuk pengembangan — lihat
    # auth/mock_directory.py. Dipakai kalau tenant Azure (BEI maupun
    # developer) tidak tersedia: seluruh alur SSO milik kita tetap bisa diuji
    # tanpa Microsoft sama sekali.
    #
    # BYPASS OTENTIKASI. Kalau true, siapa pun yang membuka halaman picker
    # bisa masuk sebagai pegawai mana pun tanpa kredensial apa pun. Default
    # HARUS tetap false, dan jangan pernah dinyalakan di lingkungan yang bisa
    # dijangkau orang lain. Setiap login lewat jalur ini dicatat ke audit log
    # dengan severity "high" supaya tidak bisa terjadi diam-diam.
    azure_mock_enabled: bool = False
    # Tempat picker di-host. Perlu absolut karena yang membukanya adalah
    # BROWSER (hasil redirect), bukan backend sendiri.
    azure_mock_picker_url: str = "http://localhost:8000/api/auth/azure/mock-picker"

    @property
    def sensitive_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.sensitive_keywords.split(",") if k.strip()]

    class Config:
        env_file = ".env"


settings = Settings()
