"""
Uji isolasi knowledge base antar divisi (SRS rule 1, 2.b; BRD BR-02).

    cd backend
    python -m scripts.make_kb_fixtures        # sekali, bikin PDF-nya
    python -m scripts.test_kb_isolation       # indeks, uji, bersihkan lagi
    python -m scripts.test_kb_isolation --keep   # biarkan terindeks buat coba di UI

Yang diuji adalah LAPIS RETRIEVAL, bukan jawaban LLM. Isolasi divisi ditegakkan
di KbDivisiRetriever lewat where={"divisi": {"$in": allowed}} pada query
ChromaDB -- dokumen divisi lain tidak pernah sampai ke prompt. Kalau lapis itu
bocor, tidak ada instruksi prompt yang bisa menambalnya; kalau lapis itu rapat,
jawaban LLM tidak bisa membocorkannya. Jadi di sinilah tempat mengujinya, dan
untungnya tidak butuh GPU sama sekali.

TIGA LAPIS, dari yang paling gampang lolos sampai yang paling tajam:

  A. Identifier unik per divisi (PTI-01 vs SDI-01). Lemah sebagai bukti: sistem
     bisa "lulus" hanya karena tidak punya dokumennya sama sekali.
  B. Angka berbeda untuk pertanyaan yang sama (batas anggaran, SLA, jumlah
     pegawai). Membuktikan yang diambil memang punya divisi si penanya.
  C. IDENTIFIER SAMA, ISI BERBEDA -- SOP-01..03 ada di ketiga divisi. Saringan
     leksikal kita justru mencocokkan ketiganya; satu-satunya yang memisahkan
     adalah filter divisi. Kebocoran di sini TIDAK terlihat pada lapis A/B.
"""
import argparse
import pathlib
import re
import sys
import uuid

from app.rag.vectorstore import (
    KB_COMPANY_WIDE_SENTINEL, KB_DIVISI_COLLECTION_NAME,
    KbDivisiRetriever, extract_pages_from_pdf, get_collection,
    index_kb_document,
)

FIXTURES = {
    "PTI": "KB_PTI_Pedoman_Operasional.pdf",
    "SDI": "KB_SDI_Pedoman_Operasional.pdf",
    "WAS": "KB_WAS_Pedoman_Operasional.pdf",
    None:  "KB_CompanyWide_Ketentuan_Umum.pdf",
}
DIVISI = ["PTI", "SDI", "WAS"]

# Penanda isi khas tiap divisi. Kalau salah satu muncul di hasil milik divisi
# lain, itu kebocoran -- bukan sekadar kemiripan kata.
SIDIK = {
    "PTI": [r"Core Trading Engine", r"Rp250\.000\.000", r"99,5%",
            r"severity-1", r"\bPTI-0\d\b", r"\b84\b"],
    "SDI": [r"Human Capital", r"Rp75\.000\.000", r"98,0%",
            r"Komite Etik", r"\bSDI-0\d\b", r"\b37\b"],
    "WAS": [r"Market Surveillance", r"Rp150\.000\.000", r"99,9%",
            r"OJK dalam 1 hari", r"\bWAS-0\d\b", r"\b52\b"],
}
UMUM = [r"REG-0\d", r"POJK", r"09\.00-11\.30"]

# (label, kueri, lapis)
KUERI = [
    ("dokumen internal divisi",      "inventaris dokumen internal divisi",       "A"),
    ("pedoman operasional",          "pedoman operasional divisi",               "A"),
    ("batas persetujuan anggaran",   "batas persetujuan anggaran kepala divisi", "B"),
    ("target SLA",                   "target ketersediaan layanan SLA",          "B"),
    ("jumlah pegawai",               "jumlah pegawai tetap divisi",              "B"),
    ("SOP-01",                       "SOP-01 prosedur",                          "C"),
    ("SOP-02",                       "SOP-02 prosedur permintaan",               "C"),
    ("SOP-03",                       "SOP-03 prosedur",                          "C"),
    ("prosedur operasi standar",     "prosedur operasi standar SOP",             "C"),
]

DOC_PREFIX = "isolation-test-"


def _ambil(divisi_user, query, top_k=10):
    """Persis seperti retrieve_context menyusun cakupan untuk seorang user."""
    allowed = [KB_COMPANY_WIDE_SENTINEL] + ([divisi_user] if divisi_user else [])
    r = KbDivisiRetriever(allowed_divisi=allowed, top_k=top_k)
    return "\n".join(d.page_content for d in r.invoke(query))


def indeks(folder: pathlib.Path) -> list[str]:
    ids = []
    for divisi, nama in FIXTURES.items():
        p = folder / nama
        if not p.exists():
            sys.exit(f"{p} tidak ada. Jalankan dulu: python -m scripts.make_kb_fixtures")
        doc_id = DOC_PREFIX + uuid.uuid4().hex[:8]
        index_kb_document(pages=extract_pages_from_pdf(p.read_bytes()),
                          doc_id=doc_id, filename=nama, divisi=divisi)
        ids.append(doc_id)
    return ids


def bersihkan():
    col = get_collection(KB_DIVISI_COLLECTION_NAME)
    got = col.get(include=["metadatas"])
    buang = [i for i, m in zip(got.get("ids") or [], got.get("metadatas") or [])
             if str((m or {}).get("doc_id", "")).startswith(DOC_PREFIX)]
    if buang:
        col.delete(ids=buang)
    return len(buang)


def jalankan() -> int:
    gagal = 0
    print(f"\n{'='*78}\n  KEBOCORAN LINTAS DIVISI\n{'='*78}")
    print(f"  {'kueri':30} {'sbg':4} " + " ".join(f"{d:>10}" for d in DIVISI) + "   umum")
    print("  " + "-" * 74)
    for label, q, lapis in KUERI:
        for pemilik in DIVISI:
            teks = _ambil(pemilik, q)
            sel, bocor = [], []
            for lain in DIVISI:
                n = sum(1 for p in SIDIK[lain] if re.search(p, teks))
                if lain == pemilik:
                    sel.append(f"{n} sendiri" if n else "KOSONG")
                else:
                    sel.append(f"{n} BOCOR" if n else "-")
                    if n:
                        bocor.append(lain)
            n_umum = sum(1 for p in UMUM if re.search(p, teks))
            tanda = "  <-- BOCOR" if bocor else ""
            if bocor:
                gagal += 1
            print(f"  {label:30} {pemilik:4} " + " ".join(f"{s:>10}" for s in sel)
                  + f"   {n_umum}{tanda}")
        print()
    return gagal


def kontrol() -> int:
    """Isolasi yang terlalu ketat juga cacat: dokumen sendiri harus tetap sampai."""
    gagal = 0
    print(f"{'='*78}\n  KONTROL POSITIF (harus BISA dibaca)\n{'='*78}")
    for d in DIVISI:
        teks = _ambil(d, "pedoman operasional divisi inventaris dokumen")
        n = sum(1 for p in SIDIK[d] if re.search(p, teks))
        ok = n > 0
        gagal += (not ok)
        print(f"  user {d:4} membaca dokumen {d:4} : {'ok' if ok else 'GAGAL'} ({n} penanda)")
    for d in DIVISI + [None]:
        teks = _ambil(d, "peraturan POJK jam perdagangan")
        n = sum(1 for p in UMUM if re.search(p, teks))
        ok = n > 0
        gagal += (not ok)
        print(f"  user {str(d):4} membaca Company Wide : {'ok' if ok else 'GAGAL'} ({n} penanda)")
    teks = _ambil(None, "pedoman operasional divisi")
    bocor = [d for d in DIVISI if any(re.search(p, teks) for p in SIDIK[d])]
    gagal += bool(bocor)
    print(f"  user TANPA divisi (admin global) melihat KB divisi : "
          f"{'BOCOR ' + ','.join(bocor) if bocor else 'tidak (benar)'}")
    print()
    return gagal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="kb_fixtures")
    ap.add_argument("--keep", action="store_true",
                    help="Biarkan dokumen terindeks setelah uji selesai")
    args = ap.parse_args()

    n = bersihkan()
    if n:
        print(f"membersihkan {n} chunk sisa uji sebelumnya")
    ids = indeks(pathlib.Path(args.fixtures))
    print(f"terindeks: {len(ids)} dokumen ke koleksi {KB_DIVISI_COLLECTION_NAME}")
    try:
        gagal = jalankan() + kontrol()
    finally:
        if args.keep:
            print("(--keep: dokumen dibiarkan terindeks)")
        else:
            print(f"dibersihkan: {bersihkan()} chunk")

    print("=" * 78)
    print("  HASIL: ISOLASI UTUH" if gagal == 0 else f"  HASIL: {gagal} MASALAH")
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())
