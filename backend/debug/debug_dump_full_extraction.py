"""
Dump seluruh hasil extract_text_from_pdf() ke file teks biasa, biar bisa
dibaca langsung dan dilihat persis di mana bagian section 4 (Scope &
Boundaries) hilang / loncat ke section lain.

Cara pakai:
1. Copy ke folder backend/ (sejajar app/), aktifkan venv.
2. python debug_dump_full_extraction.py "C:\path\ke\file.pdf"
3. Buka file output "extracted_raw.txt" yang dihasilkan di folder yang sama,
   cari kata "Scope" atau "4." untuk lihat konten section 4 secara utuh.
"""

import sys
from app.rag.vectorstore import extract_text_from_pdf


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_dump_full_extraction.py <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    raw_markdown = extract_text_from_pdf(file_bytes)

    output_path = "extracted_raw.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(raw_markdown)

    print(f"Selesai. Total {len(raw_markdown)} karakter ditulis ke {output_path}")
    print("Buka file itu, cari kata 'Scope' atau '## 4' untuk lihat isi section 4 secara utuh.")
    print("Perhatikan apakah teks langsung loncat dari section 3 ke section 5 tanpa jeda,")
    print("atau apakah section 4.1 (In-Scope) muncul tapi 4.2/4.3 hilang di tengah jalan.")


if __name__ == "__main__":
    main()