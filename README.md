# IDX Catalyst — Generic ChatBot AI

Purwarupa chatbot AI perusahaan berbasis RAG (Retrieval-Augmented Generation) dengan
LLM switching (on-premise vs commercial), dibangun mengikuti spesifikasi **FCR-003**
dari SRS "IDX Catalyst" milik PT Bursa Efek Indonesia (BEI). Proyek ini dikerjakan
sebagai bagian dari program magang, dan tema visualnya (warna, tipografi) mengikuti
nuansa situs resmi [idx.co.id](https://www.idx.co.id).

## Fitur

**Chat & RAG**
- Percakapan dengan AI, riwayat tersimpan per akun, arsip & pemulihan percakapan
- Upload dokumen PDF per percakapan — jadi konteks tambahan untuk jawaban AI
- Retrieval berlapis (RAG): dokumen chat, FAQ perusahaan, Knowledge Base per-divisi,
  digabung lewat *ensemble retriever* dengan bobot yang menyesuaikan intent pertanyaan
- Klasifikasi intent 2 lapis (regex + LLM) — sapaan/basa-basi otomatis dilewati dari RAG
- Sitasi sumber pada tiap jawaban (nama dokumen + nomor halaman, atau "FAQ Helpdesk")
- Ekspor percakapan ke PDF (dibatasi role tertentu, bisa diatur IT Admin)

**Keamanan & Guardrail**
- Filter konten terlarang (SARA, kekerasan, pornografi, instruksi ilegal, self-harm, dll)
- Deteksi & pemblokiran prompt injection / jailbreak (single-turn & multi-turn)
- Deteksi PII (NIK, NPWP, no. HP, plat kendaraan, dll) — otomatis disamarkan sebelum
  dikirim ke LLM commercial, didemasking kembali hanya untuk pemilik percakapan
  yang sah
- Enkripsi at-rest untuk seluruh isi pesan & audit log (Fernet)
- LLM switching otomatis: konten sensitif/PII selalu dialihkan ke model on-premise
- Rate limiting per-user, dikonfigurasi runtime oleh IT Admin (bukan lewat `.env`)
- Tombol *force-stop* darurat untuk mematikan seluruh LLM commercial perusahaan

**Autentikasi**
- JWT + sesi tunggal per akun (login baru otomatis mengakhiri sesi lama)
- MFA (TOTP) wajib untuk role IT Admin
- SSO Azure AD (simulasi "Logon LDAP M365 BEI") — opsional, login lokal tetap tersedia
- Kebijakan password (kompleksitas, masa berlaku 90 hari)

**Multi-Tenant & Manajemen**
- 9 divisi × 8 role sebagai dua sumbu independen (role = jabatan, divisi = unit kerja)
- Knowledge Base per-divisi + Company Wide, terisolasi lewat filter vector DB
- Manajemen user (ubah role/divisi) — admin divisi hanya mengelola divisinya sendiri,
  admin global mengelola semua
- Retensi data historis (arsip otomatis chat lama) yang bisa dikonfigurasi & dipicu
  manual oleh admin global
- Audit log lengkap dengan pencarian/filter/ekspor CSV — admin divisi hanya melihat
  aktivitas divisinya, admin global & compliance/auditor melihat semua

**Helpdesk (eskalasi ke manusia)**
- Tombol "Hubungi Admin" permanen + eskalasi otomatis saat confidence jawaban AI rendah
- Hierarki eskalasi: user biasa → IT Admin divisinya; IT Admin divisi → IT Admin global
- Chat real-time (WebSocket) antara user dan admin yang menangani, dengan opsi
  melampirkan satu percakapan AI sebagai konteks tambahan

## Tumpukan Teknologi

| | |
|---|---|
| Backend | FastAPI, SQLAlchemy, PostgreSQL |
| Vector DB | ChromaDB (embedding lokal, `all-MiniLM-L6-v2`) |
| LLM on-premise | Ollama (default: `llama3`) |
| LLM commercial | Groq, Gemini, Mistral, atau Cloudflare Workers AI (dipilih dari `.env`) |
| PII detection | Microsoft Presidio + recognizer kustom untuk pola identitas Indonesia |
| Frontend | Next.js 14 (App Router), React, tanpa framework CSS eksternal |

## Struktur Proyek

```
enterprise-rag-chatbot/
├── backend/
│   ├── app/
│   │   ├── auth/        login, register, MFA, SSO Azure AD, JWT
│   │   ├── admin/        manajemen user & setelan sistem (rate limit, retensi, dll)
│   │   ├── chat/          endpoint chat utama, ekspor PDF
│   │   ├── rag/           upload dokumen, endpoint retrieval
│   │   ├── llm/           LLM switching (on-prem vs commercial)
│   │   ├── kb/             Knowledge Base multi-tenant per divisi
│   │   ├── faq/            FAQ helpdesk (sumber RAG company-wide)
│   │   ├── helpdesk/       tiket eskalasi + chat real-time (WebSocket)
│   │   ├── guardrail/      filter konten, PII, prompt injection, audit log, enkripsi
│   │   ├── models.py       tabel database (SQLAlchemy)
│   │   ├── schemas.py      skema request/response (Pydantic)
│   │   └── main.py         entry point, menyatukan semua router
│   ├── requirements.txt
│   ├── requirements-sso.txt  (dependensi Azure AD, diinstal terpisah — lihat komentarnya)
│   ├── docker-compose.yml    (PostgreSQL siap pakai)
│   └── .env.example
│
└── frontend/
    ├── app/
    │   ├── (app)/         halaman di dalam shell (sidebar): chat, admin, audit, helpdesk, dll
    │   ├── components/    Sidebar, Composer, Dialog, dll — dipakai lintas halaman
    │   ├── login/, register/, mfa-*/, change-password/   halaman di luar shell
    │   └── page.jsx       root — redirect ke /chat
    ├── lib/api.js         wrapper pemanggilan API backend
    └── .env.local.example
```

## Setup Awal

### 1. Clone & masuk folder proyek
```bash
git clone <url-repo-anda>
cd enterprise-rag-chatbot
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

# SSO Azure AD (opsional) — lewati kalau tidak dipakai
pip install -r requirements-sso.txt --no-deps
pip install "PyJWT[crypto]<3,>=1.0.0"

cp .env.example .env
```

Edit `.env` — isi minimal:
- `JWT_SECRET_KEY` (string acak, bebas)
- Minimal satu API key LLM commercial (`GEMINI_API_KEY` dari
  [aistudio.google.com/apikey](https://aistudio.google.com/apikey), atau `GROQ_API_KEY`, dst)
- `MESSAGE_ENCRYPTION_KEY` — wajib untuk pemakaian sungguhan (opsional saat development
  lokal). Generate dengan:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

Untuk mengaktifkan SSO Azure AD, tambahkan juga di `.env`:
```
AZURE_CLIENT_ID=
AZURE_TENANT_ID=
AZURE_CLIENT_SECRET=
AZURE_REDIRECT_URI=http://localhost:3000/auth/azure/callback
```
Kosongkan (default) kalau tidak dipakai — tombol "Login dengan Microsoft" otomatis
tersembunyi dan endpoint terkait membalas 400 yang jelas.

### 4. Setup Ollama (LLM on-premise)
```bash
# Install dari https://ollama.com
ollama pull llama3
ollama serve   # biarkan berjalan di terminal terpisah
```

### 5. Jalankan backend
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```
Tabel database dibuat otomatis saat pertama kali dijalankan. Buka
http://localhost:8000/docs untuk Swagger UI.

### 6. Setup & jalankan frontend
```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```
Buka http://localhost:3000 — akan otomatis diarahkan ke `/login` (belum ada akun)
atau `/chat` (sudah login).

Logo aplikasi diambil dari `frontend/public/logo.png` — taruh berkas di sana untuk
menampilkannya di sidebar; kalau belum ada, otomatis jatuh ke lambang bawaan.

## Membuat Akun Pertama

Registrasi mandiri (`/register`) hanya mengizinkan role non-administratif (Designer,
MLOps, Consumer, Compliance, Auditor, dst) — role **IT Admin** sengaja tidak bisa
diklaim sendiri lewat form publik. Untuk membuat admin pertama, jalankan langsung
lewat database atau lewat `/docs` (`POST /api/auth/register` lalu ubah kolom `role`
ke `it_admin` secara manual di PostgreSQL), kemudian login — sistem akan meminta
setup MFA di percobaan login pertama (wajib untuk IT Admin).

## Konfigurasi Runtime (bukan lewat `.env`)

Beberapa kebijakan sengaja bisa diubah IT Admin langsung dari UI (`/admin`), tanpa
restart server: rate limit chat, retensi data historis, daftar role yang boleh
ekspor PDF, dan tombol *force-stop* LLM commercial. Nilai di `.env` hanya jadi
nilai awal/*fallback*.

## Catatan Pengembangan

- Migrasi database dilakukan manual lewat `psql` (`ALTER TABLE` langsung), bukan
  Alembic — cukup untuk skala prototipe ini.
- Sesi login (`_active_session`) dan rate limiter menyimpan state di memori proses
  backend — reset setiap restart server, dan tidak sinkron kalau dijalankan
  multi-instance. Ini keterbatasan yang disengaja untuk skala PoC.
- Simulasi SSO Azure AD memakai tenant developer/pribadi, bukan tenant BEI
  sesungguhnya — alur OAuth-nya berjalan nyata, hanya belum terhubung ke direktori
  karyawan BEI yang asli.
