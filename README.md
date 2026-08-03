# Generic ChatBot AI — Tingkat 1 (Mini)

Purwarupa chatbot AI berbasis RAG dengan LLM Switching (on-premise vs commercial),
terinspirasi dari Fungsi FCR-003 SRS IDX Catalyst.

## Struktur Project

```
chatbot-project/
├── backend/          FastAPI + PostgreSQL + Chroma (Vector DB)
│   ├── app/
│   │   ├── auth/      [B] login, register, JWT
│   │   ├── chat/      [A+B] endpoint chat (titik integrasi)
│   │   ├── rag/       [A] embedding, vector search, upload dokumen
│   │   ├── llm/       [A] LLM switching (on-prem vs commercial)
│   │   ├── guardrail/ [B] filter kata terlarang
│   │   ├── models.py  [B] tabel database
│   │   ├── schemas.py [B] skema request/response
│   │   └── main.py    [A+B] entry point, gabungkan semua router
│   ├── requirements.txt
│   ├── docker-compose.yml   (PostgreSQL siap pakai)
│   └── .env.example
│
└── frontend/          Next.js
    ├── app/
    │   ├── login/     [B] halaman login
    │   └── chat/      [B] halaman chat utama
    ├── lib/api.js     [B] wrapper pemanggilan API
    └── .env.local.example
```

## Pembagian Tugas

| Area | Anggota A | Anggota B |
|---|---|---|
| Fokus | RAG pipeline + LLM switching | Auth, database, guardrail, frontend |
| Folder | `backend/app/rag/`, `backend/app/llm/` | `backend/app/auth/`, `backend/app/guardrail/`, `frontend/` |
| Bersama | `backend/app/chat/routes.py`, `backend/app/main.py` | (sama) |

## Setup Awal (Kerjakan Berdua di Awal)

### 1. Clone & masuk folder project
```bash
git clone <url-repo-anda>
cd chatbot-project
```

### 2. Jalankan PostgreSQL via Docker
```bash
cd backend
docker compose up -d
```
Cek berjalan: `docker ps` — harus muncul container `chatbot_postgres`.

### 3. Setup backend (Python)
```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```
Edit `.env` — isi minimal:
- `JWT_SECRET_KEY` (bebas, string acak)
- `GEMINI_API_KEY` (dari https://aistudio.google.com/apikey — gratis)

### 4. (Khusus Anggota A) Setup Ollama untuk LLM on-premise
```bash
# Install dari https://ollama.com
ollama pull llama3
ollama serve   # biarkan berjalan di terminal terpisah
ollama list
```

### 5. Jalankan backend
```bash
uvicorn app.main:app --reload --port 8000 #jalankan di direktori /backend

cd path/ke/chatbot-project/backend    # 1. masuk ke folder backend
source venv/bin/activate               # 2. aktifkan virtual environment
uvicorn app.main:app --reload --port 8000   # 3. jalankan server
```
Buka http://localhost:8000/docs — akan muncul Swagger UI untuk uji coba semua endpoint.

### 6. Setup frontend
```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```
Buka http://localhost:3000

## Alur Kerja Git yang Disarankan

```bash
git checkout -b feature/rag-llm       # Anggota A
git checkout -b feature/auth-frontend # Anggota B
```
Merge ke `main` secara berkala (idealnya tiap 2-3 hari), terutama sebelum mulai
mengerjakan `chat/routes.py` bersama — supaya tidak konflik besar di akhir.

## Urutan Pengerjaan yang Disarankan

**Minggu 1**
- A: pastikan `rag/vectorstore.py` bisa index & retrieve dokumen (uji lewat script Python biasa dulu, belum lewat API)
- B: pastikan `auth/routes.py` bisa register & login (uji lewat `/docs`)

**Minggu 2**
- A: pastikan `llm/router.py` bisa switching on-prem/commercial (uji manual dengan prompt yang mengandung kata "rahasia" vs tidak)
- B: bangun `documents.py` metadata + mulai frontend (login page, chat UI kosongan)

**Minggu 3**
- A + B: sambungkan semuanya lewat `chat/routes.py`, uji end-to-end dari frontend
- Testing bersama, perbaikan bug

## Cara Menguji LLM Switching (F1-05)

Setelah backend jalan, coba dua prompt berbeda lewat `/docs` atau frontend:

1. `"Apa itu machine learning?"` → seharusnya `llm_used: "commercial"` (Gemini)
2. `"Ini rahasia perusahaan, tolong analisis"` → seharusnya `llm_used: "on-prem"` (Ollama)

Kata kunci sensitif bisa diubah di `.env` pada variabel `SENSITIVE_KEYWORDS`.
