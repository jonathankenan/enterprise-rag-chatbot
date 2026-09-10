# demo.ps1 — satu perintah untuk menyalakan semuanya sebelum demo, dan
# memastikan tiap bagian benar-benar hidup sebelum bilang "siap".
#
# Menyalakan (masing-masing di window PowerShell sendiri, biar log-nya
# kelihatan kalau ada yang error):
#   1. Postgres (docker compose)
#   2. cek Ollama di PC GPU lewat Tailscale -- TIDAK dinyalakan dari sini,
#      cuma diperiksa, karena itu di mesin lain
#   3. Backend (uvicorn)
#   4. Frontend (next dev)
#
# Pakai venv\Scripts\python.exe langsung (bukan Activate.ps1) supaya tidak
# kena ganjalan ExecutionPolicy di PC yang belum pernah di-set.
#
# Jalankan dari root project:  .\demo.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"

function Write-Check {
    param([bool]$Ok, [string]$Label, [string]$Detail)
    if ($Ok) {
        Write-Host "  [OK]   $Label" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $Label" -ForegroundColor Red
    }
    if ($Detail) { Write-Host "         $Detail" -ForegroundColor DarkGray }
}

# ── 1. Postgres ──────────────────────────────────────────────────────────
Write-Host "`n=== 1/4 Postgres ===" -ForegroundColor Cyan
Push-Location $backendDir
docker compose up -d | Out-Null
Pop-Location

$pgOk = $false
for ($i = 0; $i -lt 15; $i++) {
    docker exec chatbot_postgres pg_isready -U chatbot_user *> $null
    if ($LASTEXITCODE -eq 0) { $pgOk = $true; break }
    Start-Sleep -Seconds 1
}
Write-Check -Ok $pgOk -Label "Postgres (chatbot_postgres)" -Detail "docker compose up -d"
if (-not $pgOk) {
    Write-Host "`nPostgres tidak siap dalam 15 detik. Cek 'docker ps' dan 'docker logs chatbot_postgres'." -ForegroundColor Red
    exit 1
}

# ── 2. Ollama, lewat Tailscale ke PC GPU -- cuma diperiksa, tidak dinyalakan ──
Write-Host "`n=== 2/4 Ollama (di PC GPU, via Tailscale) ===" -ForegroundColor Cyan
$ollamaUrl = "http://100.86.208.11:11434"
$ollamaModel = "qwen2.5:7b"
$envFile = Join-Path $backendDir ".env"
if (Test-Path $envFile) {
    $urlLine = Get-Content $envFile | Where-Object { $_ -match "^OLLAMA_BASE_URL=" } | Select-Object -First 1
    if ($urlLine) { $ollamaUrl = ($urlLine -split "=", 2)[1].Trim() }
    $modelLine = Get-Content $envFile | Where-Object { $_ -match "^OLLAMA_MODEL=" } | Select-Object -First 1
    if ($modelLine) { $ollamaModel = ($modelLine -split "=", 2)[1].Trim() }
}

$ollamaOk = $false
$ollamaDetail = ""
try {
    $resp = Invoke-RestMethod -Uri "$ollamaUrl/api/tags" -TimeoutSec 5
    $models = @($resp.models | ForEach-Object { $_.name })
    if ($models -contains $ollamaModel) {
        $ollamaOk = $true
        $ollamaDetail = "model '$ollamaModel' tersedia di $ollamaUrl"
    } else {
        $ollamaDetail = "Ollama hidup tapi model '$ollamaModel' TIDAK ada (ada: $($models -join ', ')) -- jalur sensitif akan salah jawab"
    }
} catch {
    $ollamaDetail = "$ollamaUrl tidak terjangkau -- cek PC GPU menyala, 'ollama serve' jalan, dan Tailscale aktif"
}
Write-Check -Ok $ollamaOk -Label "Ollama ($ollamaUrl)" -Detail $ollamaDetail

if (-not $ollamaOk) {
    Write-Host "`n[!] Ollama TIDAK siap -- pertanyaan bermuatan data sensitif akan gagal atau" -ForegroundColor Yellow
    Write-Host "    (lebih buruk) diam-diam lari ke provider komersial. Kalau lanjut demo," -ForegroundColor Yellow
    Write-Host "    JANGAN tunjukkan pertanyaan sensitif / klaim routing on-prem berfungsi." -ForegroundColor Yellow
    $continue = Read-Host "`nLanjutkan tanpa Ollama? (y/n)"
    if ($continue -ne "y") { exit 1 }
}

# ── 3. Backend ───────────────────────────────────────────────────────────
Write-Host "`n=== 3/4 Backend ===" -ForegroundColor Cyan
$backendPython = Join-Path $backendDir "venv\Scripts\python.exe"
if (-not (Test-Path $backendPython)) {
    Write-Host "  venv tidak ditemukan di backend\venv -- jalankan setup dulu (lihat README)." -ForegroundColor Red
    exit 1
}
# Sengaja TANPA --reload: uvicorn --reload mengawasi seluruh backend/,
# termasuk chroma_data/ yang berubah tiap ada dokumen di-index -- kalau itu
# ke-trigger pas demo (mis. upload dokumen KB langsung di depan orang),
# server bisa restart mendadak di tengah presentasi. Reload cuma berguna
# untuk development aktif, bukan untuk sesi demo.
#
# HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE: TANPA ini, import app.main (lewat
# sentence-transformers) mencoba menghubungi Hugging Face Hub buat cek versi
# model terbaru setiap kali proses Python dimulai -- diukur di mesin ini,
# itu bikin startup 6+ MENIT (nyaris idle CPU, jelas nunggu network timeout,
# bukan komputasi). Modelnya sudah ada di cache lokal (~/.cache/huggingface),
# jadi mode offline aman dan startup turun jadi ~35 detik. Ini bukan cuma
# soal skrip demo -- setiap `uvicorn --reload` restart pas development
# sehari-hari kena pajak yang sama tanpa variabel ini.
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backendDir'; `$env:HF_HUB_OFFLINE='1'; `$env:TRANSFORMERS_OFFLINE='1'; & '$backendPython' -m uvicorn app.main:app --port 8000"

# Cold start di mesin ini diukur berkali-kali (bersih, tanpa proses lain
# jalan): SELALU berhasil, tapi 2-6 menit -- terukur disk-I/O-bound (CPU
# yang benar-benar terpakai cuma ~30 detik dari total waktu itu), bukan
# proses macet. Bukan salah skrip, bukan salah HF_HUB_OFFLINE (itu tetap
# dipakai, cuma bukan bottleneck utamanya) -- ini karakter hardware-nya.
# 360 detik dipilih generus dengan sadar supaya skrip tidak salah bilang
# FAIL padahal cuma butuh waktu lebih.
$backendOk = $false
for ($i = 0; $i -lt 360; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://localhost:8000/" -TimeoutSec 2
        if ($r.status -eq "ok") { $backendOk = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
    if ($i -gt 0 -and $i % 30 -eq 0) {
        Write-Host "  ... masih menunggu backend ($i detik -- normal di hardware ini, bisa sampai beberapa menit)" -ForegroundColor DarkGray
    }
}
Write-Check -Ok $backendOk -Label "Backend (http://localhost:8000)" -Detail "dijalankan di window baru (cold start di hardware ini terukur konsisten 2-6 menit -- selalu berhasil, cuma lambat)"
if (-not $backendOk) {
    Write-Host "`nBackend belum merespons setelah 6 menit -- ini di luar rentang yang pernah terukur." -ForegroundColor Red
    Write-Host "Cek window barunya: kalau ada traceback merah, itu error sungguhan." -ForegroundColor Yellow
    Write-Host "Kalau windownya masih diam/memuat tanpa error, kemungkinan cuma perlu waktu" -ForegroundColor Yellow
    Write-Host "lebih lagi -- tunggu saja, atau coba lagi nanti." -ForegroundColor Yellow
    exit 1
}

# ── 4. Frontend ──────────────────────────────────────────────────────────
Write-Host "`n=== 4/4 Frontend ===" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontendDir'; npm run dev"

# Terukur 48.8 detik di hardware ini (Next.js baca banyak file dari
# node_modules, kena disk I/O lambat yang sama seperti backend) -- 120
# detik dikasih dengan margin, bukan 30.
$frontendOk = $false
for ($i = 0; $i -lt 120; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:3000" -TimeoutSec 2 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $frontendOk = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}
Write-Check -Ok $frontendOk -Label "Frontend (http://localhost:3000)" -Detail "dijalankan di window baru (terukur ~49 detik di hardware ini)"

# ── Ringkasan ────────────────────────────────────────────────────────────
Write-Host ""
if ($pgOk -and $backendOk -and $frontendOk) {
    Write-Host "=== Siap demo ===" -ForegroundColor Green
    if (-not $ollamaOk) {
        Write-Host "(Ollama tidak siap -- hindari pertanyaan sensitif / jalur on-prem saat demo)" -ForegroundColor Yellow
    }
    Start-Process "http://localhost:3000"
} else {
    Write-Host "=== Belum siap -- lihat [FAIL] di atas sebelum mulai demo ===" -ForegroundColor Red
    exit 1
}
