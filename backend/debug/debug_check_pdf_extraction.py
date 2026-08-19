"""
Debug script — cek output MENTAH dari extract_text_from_pdf() (sebelum di-chunk
sama sekali), untuk memastikan apakah section 4.2 (Out-of-Scope Capabilities)
hilang di tahap ekstraksi PDF->markdown, atau masih ada di situ tapi hilang
belakangan pas proses chunking.

Cara pakai:
1. Copy file ini ke folder backend/ (sejajar dengan folder app/).
2. Aktifkan venv: .\venv\Scripts\activate
3. Jalankan dengan path ke file PDF BRD yang sama yang kamu upload:
   python debug_check_pdf_extraction.py "C:\path\ke\Project_NEXUS_Business_Requirements_Document.pdf"
"""

import sys
from app.rag.vectorstore import extract_text_from_pdf, chunk_text


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_check_pdf_extraction.py <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    # 1. Ekstrak PDF ke markdown mentah, PERSIS seperti yang dipanggil saat upload
    print("[1] Menjalankan extract_text_from_pdf()...")
    raw_markdown = extract_text_from_pdf(file_bytes)
    print(f"    Total panjang teks hasil ekstraksi: {len(raw_markdown)} karakter\n")

    # 2. Cek apakah kata kunci section 4.2 ADA di teks mentah hasil ekstraksi
    #    (sebelum sempat di-chunk sama sekali)
    keywords_to_check = [
        "Out-of-Scope",
        "4.2 Out-of-Scope",
        "Automated Loan Approvals",
        "Direct Wire Transfer Execution",
        "Voice Synthesis",
        "Third-Party Financial Aggregation",
        "Plaid",
        "4.3 Supported Languages",
    ]

    print("[2] Mengecek keberadaan kata kunci section 4.2/4.3 di HASIL EKSTRAKSI MENTAH:\n")
    all_found = True
    for kw in keywords_to_check:
        if kw.lower() in raw_markdown.lower():
            idx = raw_markdown.lower().find(kw.lower())
            preview = raw_markdown[max(0, idx - 50):idx + 150].replace("\n", " ")
            print(f"  ✅ '{kw}' DITEMUKAN di posisi karakter {idx}")
            print(f"     konteks: ...{preview}...\n")
        else:
            all_found = False
            print(f"  ❌ '{kw}' TIDAK DITEMUKAN sama sekali di hasil ekstraksi PDF\n")

    print("=" * 70)
    if not all_found:
        print(">>> KESIMPULAN: Section 4.2/4.3 HILANG SEJAK TAHAP EKSTRAKSI PDF")
        print(">>> (pymupdf4llm.to_markdown()), SEBELUM sempat di-chunk.")
        print(">>> Ini bug di extract_text_from_pdf(), bukan di chunk_text()")
        print(">>> ataupun di retrieval logic. Kemungkinan pymupdf4llm gagal")
        print(">>> mem-parsing halaman/section tersebut karena format PDF-nya")
        print(">>> (bullet list dengan bold title, bukan tabel).")
    else:
        print(">>> KESIMPULAN: Section 4.2/4.3 ADA di hasil ekstraksi PDF mentah.")
        print(">>> Berarti section ini hilang BELAKANGAN, di tahap chunk_text()")
        print(">>> atau saat disimpan ke ChromaDB. Perlu investigasi lebih lanjut")
        print(">>> di fungsi chunk_text()/index_document().")

    # 3. Kalau section 4.2 ADA di raw markdown, cek juga apakah dia SELAMAT
    #    setelah proses chunk_text() dijalankan (untuk isolasi lebih lanjut)
    if not all_found:
        print("\n[3] (Section tidak ditemukan di raw extraction, skip pengecekan chunking)")
    else:
        print("\n[3] Section ditemukan di raw text -> cek juga apakah selamat setelah chunking...")
        chunks = chunk_text(raw_markdown)
        found_in_chunks = any(
            "Automated Loan Approvals".lower() in c.lower() for c in chunks
        )
        print(f"    Total chunk dihasilkan dari raw text ini: {len(chunks)}")
        print(f"    'Automated Loan Approvals' ada di salah satu chunk? {found_in_chunks}")

    # 4. Print potongan teks di sekitar section 4 (In-Scope) untuk inspeksi manual,
    #    biar kelihatan persis di mana teks "patah"/hilang
    print("\n[4] Cuplikan teks mentah di sekitar section 4 (untuk inspeksi manual):\n")
    section4_idx = raw_markdown.find("4. Scope")
    if section4_idx == -1:
        section4_idx = raw_markdown.find("In-Scope Capabilities")
    if section4_idx != -1:
        print(raw_markdown[section4_idx:section4_idx + 3000])
    else:
        print("    (Tidak ditemukan penanda awal section 4 sama sekali di teks mentah)")


if __name__ == "__main__":
    main()