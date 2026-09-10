"""
Bangun dokumen PDF uji untuk knowledge base per divisi.

    cd backend
    python -m scripts.make_kb_fixtures                 # tulis ke ./kb_fixtures/
    python -m scripts.make_kb_fixtures --out D:/uji    # folder lain

Menghasilkan empat PDF: PTI, SDI, WAS, dan satu Company Wide. Semuanya
mengikuti bentuk Project NEXUS -- tabel bergaris dengan identifier bergaya
`XXX-NN` -- supaya jalur yang sama ikut teruji: deteksi tabel pymupdf4llm,
pemotongan per baris, saringan identifier, dan pelengkapan baris tabel.

CARA DOKUMEN INI MENGUJI ISOLASI DIVISI
Tiga lapis, dari yang paling gampang sampai yang paling tajam:

1. Identifier unik per divisi (PTI-01, SDI-01, WAS-01). Kalau user PTI bisa
   menjawab SDI-01, isolasinya bocor. Gampang dilihat, tapi lemah: model bisa
   saja menolak karena memang tidak tahu.

2. Angka berbeda untuk pertanyaan yang sama. Ketiga divisi punya "batas
   persetujuan anggaran" dan "target SLA" dengan NILAI BERBEDA. Jawaban yang
   benar bergantung pada divisi si penanya.

3. IDENTIFIER YANG SAMA, ISI BERBEDA -- ini jebakan sesungguhnya. SOP-01
   sampai SOP-03 ada di KETIGA dokumen divisi dengan isi yang lain-lain.
   Retrieval tidak bisa membedakannya secara leksikal; satu-satunya yang
   memisahkan adalah filter `divisi` di tingkat query. Kalau user PTI bertanya
   "apa isi SOP-02" lalu mendapat jawaban SDI, filter itu tidak bekerja --
   dan gejalanya TIDAK akan terlihat pada lapis 1 maupun 2.

Dokumen Company Wide sengaja tidak memuat SOP-01..03, jadi kemunculannya
tidak pernah ambigu.

Setiap dokumen juga menyebut satu identifier yang TIDAK ADA isinya di mana
pun (lihat "Referensi silang"), untuk menguji penolakan.
"""
import argparse
import pathlib
import sys

import pymupdf

CSS = """
body { font-family: sans-serif; font-size: 10pt; }
h1 { font-size: 15pt; margin-bottom: 2pt; }
h2 { font-size: 12pt; margin-top: 12pt; margin-bottom: 4pt; }
p  { margin: 4pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; }
th, td { border: 1px solid #333; padding: 4pt 6pt; text-align: left;
         vertical-align: top; font-size: 9pt; }
th { background: #dddddd; font-weight: bold; }
.small { font-size: 8pt; color: #555; }
"""


def _table(headers, rows):
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


# (kode, nama panjang, batas anggaran, target SLA, sistem inti)
DIVISI = {
    "PTI": ("Divisi Pengembangan Teknologi Informasi", "Rp250.000.000",
            "99,5%", "Core Trading Engine"),
    "SDI": ("Divisi Sumber Daya Insani", "Rp75.000.000",
            "98,0%", "Human Capital Information System"),
    "WAS": ("Divisi Pengawasan Transaksi", "Rp150.000.000",
            "99,9%", "Market Surveillance Platform"),
}

# Identifier yang SAMA di ketiga divisi, isi berbeda -- jebakan utamanya.
SOP_BERSAMA = {
    "PTI": [
        ("SOP-01", "Penanganan Insiden Produksi",
         "Insiden severity-1 wajib dieskalasi ke Kepala Divisi dalam 15 menit dan "
         "root cause analysis diserahkan maksimal 3 hari kerja."),
        ("SOP-02", "Permintaan Akses Sistem",
         "Permintaan akses ke Core Trading Engine memerlukan persetujuan dua tingkat "
         "dan otomatis dicabut setelah 90 hari tanpa aktivitas."),
        ("SOP-03", "Rilis ke Produksi",
         "Rilis hanya boleh dijalankan Selasa dan Kamis pukul 19.00-22.00 WIB, "
         "di luar itu wajib emergency change request."),
    ],
    "SDI": [
        ("SOP-01", "Penanganan Keluhan Pegawai",
         "Keluhan yang menyangkut dugaan pelanggaran etika wajib diteruskan ke Komite "
         "Etik dalam 2 hari kerja dan identitas pelapor dirahasiakan."),
        ("SOP-02", "Permintaan Cuti Tahunan",
         "Cuti lebih dari 5 hari berturut-turut memerlukan persetujuan Kepala Divisi "
         "dan diajukan minimal 10 hari kerja sebelumnya."),
        ("SOP-03", "Proses Rekrutmen",
         "Setiap lowongan wajib dibuka internal minimal 7 hari kerja sebelum "
         "diumumkan ke publik."),
    ],
    "WAS": [
        ("SOP-01", "Penanganan Transaksi Mencurigakan",
         "Pola transaksi tidak wajar wajib dilaporkan ke OJK dalam 1 hari kerja "
         "sejak terkonfirmasi analis."),
        ("SOP-02", "Permintaan Data Perdagangan",
         "Permintaan data dari pihak eksternal hanya dilayani atas dasar surat resmi "
         "dan disetujui Kepala Divisi Pengawasan."),
        ("SOP-03", "Suspensi Perdagangan Saham",
         "Suspensi diusulkan bila harga bergerak lebih dari 35% dalam satu sesi "
         "tanpa keterbukaan informasi pendukung."),
    ],
}


def html_divisi(kode: str) -> str:
    nama, anggaran, sla, sistem = DIVISI[kode]
    sop = SOP_BERSAMA[kode]
    lain = [k for k in DIVISI if k != kode]

    prosedur = _table(
        ["Kode SOP", "Judul Prosedur", "Ketentuan"],
        [(k, j, i) for k, j, i in sop],
    )
    internal = _table(
        ["ID Dokumen", "Nama Dokumen", "Pemilik", "Frekuensi Pembaruan"],
        [(f"{kode}-01", f"Pedoman Operasional {nama}", f"Kepala Divisi {kode}", "Tahunan"),
         (f"{kode}-02", f"Matriks Kewenangan {kode}", f"Sekretariat {kode}", "Semesteran"),
         (f"{kode}-03", f"Daftar Risiko {kode}", f"Manajemen Risiko {kode}", "Triwulanan"),
         (f"{kode}-04", f"Rencana Kerja {kode} 2026", f"Kepala Divisi {kode}", "Tahunan")],
    )
    ambang = _table(
        ["Parameter", "Nilai", "Catatan"],
        [("Batas persetujuan anggaran Kepala Divisi", anggaran,
          "Di atas nilai ini wajib persetujuan Direksi"),
         ("Target ketersediaan layanan (SLA)", sla, f"Diukur pada {sistem}"),
         ("Jumlah pegawai tetap", {"PTI": "84", "SDI": "37", "WAS": "52"}[kode],
          "Posisi per 31 Desember 2025"),
         ("Waktu tanggap permintaan internal",
          {"PTI": "2 hari kerja", "SDI": "3 hari kerja", "WAS": "1 hari kerja"}[kode],
          "Dihitung sejak tiket dibuat")],
    )
    return f"""
    <h1>Pedoman Operasional {nama}</h1>
    <p class="small">RAHASIA INTERNAL &middot; {kode}-DOC-2026-V1.0 &middot;
    Hanya untuk lingkungan {nama}</p>

    <h2>1. Ruang Lingkup</h2>
    <p>Dokumen ini mengatur tata kerja {nama} ({kode}) pada tahun anggaran 2026.
    Sistem inti yang menjadi tanggung jawab divisi ini adalah {sistem}.
    Dokumen ini <b>tidak berlaku</b> bagi divisi lain; ketentuan setara untuk
    divisi {lain[0]} dan {lain[1]} diatur pada pedoman masing-masing.</p>

    <h2>2. Prosedur Operasi Standar</h2>
    <p>Kode SOP di bawah bersifat lokal terhadap divisi ini. Kode yang sama
    dapat digunakan divisi lain untuk prosedur yang sama sekali berbeda.</p>
    {prosedur}

    <h2>3. Inventaris Dokumen Internal</h2>
    {internal}

    <h2>4. Ambang Batas dan Parameter Operasional</h2>
    {ambang}

    <h2>5. Referensi silang</h2>
    <p>Ketentuan pengadaan lintas divisi mengacu pada {kode}-09, yang belum
    diterbitkan pada saat dokumen ini disusun.</p>
    """


def html_company_wide() -> str:
    regulasi = _table(
        ["Kode", "Peraturan", "Penerbit", "Berlaku Sejak"],
        [("REG-01", "POJK Nomor 4/POJK.04/2025 tentang Keterbukaan Informasi",
          "Otoritas Jasa Keuangan", "1 Maret 2025"),
         ("REG-02", "Peraturan Bursa Nomor I-A tentang Pencatatan Saham",
          "Bursa Efek Indonesia", "1 Januari 2024"),
         ("REG-03", "Surat Keputusan Direksi Nomor SK-011/BEI/2026 tentang Tata Kelola AI",
          "Direksi BEI", "15 Januari 2026"),
         ("REG-04", "POJK Nomor 11/POJK.03/2022 tentang Penyelenggaraan Teknologi Informasi",
          "Otoritas Jasa Keuangan", "1 Juli 2022")],
    )
    umum = _table(
        ["Parameter", "Nilai", "Catatan"],
        [("Jam perdagangan sesi I", "09.00-11.30 WIB", "Senin sampai Kamis"),
         ("Jam perdagangan sesi II", "13.30-15.49 WIB", "Senin sampai Kamis"),
         ("Batas auto rejection saham Rp200-Rp5.000", "25%", "Simetris atas dan bawah"),
         ("Periode retensi arsip korespondensi", "5 tahun", "Sesuai SK-011/BEI/2026")],
    )
    return f"""
    <h1>Ketentuan Umum dan Regulasi Perusahaan</h1>
    <p class="small">COMPANY WIDE &middot; BEI-DOC-2026-V1.0 &middot;
    Dapat diakses seluruh divisi</p>

    <h2>1. Ruang Lingkup</h2>
    <p>Dokumen ini memuat ketentuan yang berlaku bagi <b>seluruh divisi</b>
    tanpa terkecuali. Setiap pegawai, dari divisi mana pun, berhak membaca
    dokumen ini.</p>

    <h2>2. Daftar Regulasi yang Berlaku</h2>
    {regulasi}

    <h2>3. Parameter Operasional Umum</h2>
    {umum}

    <h2>4. Referensi silang</h2>
    <p>Ketentuan turunan mengenai sanksi administratif dimuat pada REG-08,
    yang masih dalam proses penyusunan.</p>
    """


def tulis_pdf(html: str, path: pathlib.Path) -> int:
    story = pymupdf.Story(html=html, user_css=CSS)
    writer = pymupdf.DocumentWriter(str(path))
    kotak = pymupdf.paper_rect("a4")
    area = kotak + (50, 50, -50, -50)
    halaman = 0
    lagi = True
    while lagi:
        dev = writer.begin_page(kotak)
        lagi, _ = story.place(area)
        story.draw(dev)
        writer.end_page()
        halaman += 1
    writer.close()
    return halaman


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="kb_fixtures", help="Folder keluaran")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    dibuat = []
    for kode in DIVISI:
        p = out / f"KB_{kode}_Pedoman_Operasional.pdf"
        dibuat.append((p, tulis_pdf(html_divisi(kode), p), kode))
    p = out / "KB_CompanyWide_Ketentuan_Umum.pdf"
    dibuat.append((p, tulis_pdf(html_company_wide(), p), "Company Wide"))

    print(f"Ditulis ke {out.resolve()}\n")
    for path, n, kode in dibuat:
        print(f"  {path.name:44} {n} hal   -> unggah sebagai: {kode}")
    print("\nUnggah lewat halaman admin KB, pilih divisi sesuai kolom terakhir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
