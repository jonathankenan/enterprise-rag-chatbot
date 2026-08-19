"""
Debug script — cek langsung isi ChromaDB vector store untuk satu chat_id,
tanpa lewat chatbot/LLM sama sekali. Tujuannya memastikan apakah chunk yang
berisi section 4.2 (Out-of-Scope Capabilities) benar-benar ter-index atau
tidak pernah masuk ke vector store sejak awal.

Cara pakai:
1. Copy file ini ke folder backend/ (sejajar dengan folder app/), atau taruh
   di backend/app/ dan sesuaikan import jika perlu.
2. Aktifkan venv backend kamu dulu: .\venv\Scripts\activate
3. Jalankan: python debug_check_vectorstore.py <chat_id>
   Ganti <chat_id> dengan ID chat/session yang dokumennya kamu upload
   (bisa dilihat dari URL chat di browser, atau dari log backend saat
   dokumen diupload).
"""

import sys
from app.rag.vectorstore import get_all_session_chunks, has_session_document, get_collection


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_check_vectorstore.py <chat_id>")
        sys.exit(1)

    chat_id = sys.argv[1]

    # 1. Pastikan dokumen untuk chat_id ini memang ter-index
    exists = has_session_document(chat_id)
    print(f"[1] Dokumen untuk chat_id={chat_id} ter-index? {exists}")
    if not exists:
        print("    -> Tidak ada dokumen ter-index untuk chat_id ini. Cek ulang chat_id-nya.")
        sys.exit(1)

    # 2. Ambil semua chunk untuk chat_id ini (naikkan limit biar semua ke-ambil,
    #    dari upload sebelumnya BRD ini terindeks jadi 28 potongan teks)
    chunks = get_all_session_chunks(chat_id, limit=50)
    print(f"[2] Total chunk ditemukan untuk chat_id ini: {len(chunks)}")

    # 3. Cari kata kunci yang HARUS ada di section 4.2 (Out-of-Scope) kalau
    #    section itu ter-index dengan benar
    keywords_to_check = [
        "Out-of-Scope",
        "Automated Loan Approvals",
        "Direct Wire Transfer Execution",
        "Voice Synthesis",
        "Third-Party Financial Aggregation",
        "Plaid",
    ]

    print("\n[3] Mengecek keberadaan kata kunci section 4.2 di seluruh chunk:\n")
    found_any = False
    for kw in keywords_to_check:
        matching_chunks = [
            (i, c) for i, c in enumerate(chunks) if kw.lower() in c.lower()
        ]
        if matching_chunks:
            found_any = True
            print(f"  ✅ '{kw}' DITEMUKAN di {len(matching_chunks)} chunk:")
            for idx, chunk_text in matching_chunks:
                preview = chunk_text.strip().replace("\n", " ")[:150]
                print(f"     - chunk index {idx}: {preview}...")
        else:
            print(f"  ❌ '{kw}' TIDAK DITEMUKAN di chunk manapun")

    print()
    if not found_any:
        print(">>> KESIMPULAN: Section 4.2 (Out-of-Scope) sepertinya TIDAK PERNAH")
        print(">>> ter-index sama sekali. Ini masalah di tahap ingestion/chunking,")
        print(">>> bukan di tahap retrieval saat chat berlangsung.")
    else:
        print(">>> KESIMPULAN: Section 4.2 ADA di vector store, tapi tidak pernah")
        print(">>> ter-retrieve saat chat. Ini masalah di similarity scoring /")
        print(">>> ranking, bukan di ingestion. Perlu investigasi retrieval logic.")

    # 4. (Opsional) print semua chunk mentah biar bisa dibaca manual kalau perlu
    print("\n[4] Semua chunk (mentah, untuk pengecekan manual jika diperlukan):\n")
    for i, c in enumerate(chunks):
        print(f"--- Chunk {i} ---")
        print(c.strip()[:300])
        print()


if __name__ == "__main__":
    main()