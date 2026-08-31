"""
Penjagaan divisi asing (chat/routes.py, extract_query_divisi di vectorstore.py).

Filter divisi di KbDivisiRetriever sudah benar -- dokumen SDI tidak pernah
sampai ke prompt kalau penanya PTI. Tapi baris tabel yang lolos filter tidak
menyebut nama divisinya sendiri ("Batas persetujuan anggaran Kepala Divisi |
Rp250.000.000", tanpa kata "PTI"), dan build_prompt() cuma mengirim teks
chunk. Ditanya soal SDI oleh user PTI, satu-satunya angka di konteks (milik
PTI) ditempelkan ke nama SDI -- bukan kebocoran data, tapi pelabelan keliru
yang meyakinkan.
"""
from app.rag.vectorstore import extract_query_divisi

KODE = {"WAS", "PLP", "PPT", "PP1", "PP2", "PP3", "PTI", "SDI", "OTP"}


def test_kasus_asal_terdeteksi():
    """Kasus yang dilaporkan: PTI ditanya tentang SDI."""
    assert extract_query_divisi("berapa batas anggaran divisi SDI", KODE) == {"SDI"}


def test_hasil_rewrite_bahasa_inggris_terdeteksi():
    """search_query yang dipakai retrieval sudah ditulis ulang ke Inggris."""
    assert extract_query_divisi("budget approval limit division SDI", KODE) == {"SDI"}
    assert extract_query_divisi("SDI division budget", KODE) == {"SDI"}


def test_sinonim_kata_penunjuk():
    for kata in ("divisi", "division", "bagian", "unit"):
        assert extract_query_divisi(f"{kata} SDI", KODE) == {"SDI"}
        assert extract_query_divisi(f"SDI {kata}", KODE) == {"SDI"}


def test_tanpa_penyebutan_divisi_kosong():
    assert extract_query_divisi("apa isi SOP-02", KODE) == set()


def test_case_insensitive():
    assert extract_query_divisi("BAGIAN sdi", KODE) == {"SDI"}
    assert extract_query_divisi("bagian Sdi", KODE) == {"SDI"}


# --------------------------------------------------------------------------
# Kata umum yang bertabrakan dengan kode divisi -- alasan pola ini butuh
# kata penunjuk berdampingan, bukan token telanjang.
# --------------------------------------------------------------------------

def test_was_sebagai_kata_inggris_tidak_terpicu():
    assert extract_query_divisi("kemarin saya was busy sekali", KODE) == set()


def test_ppt_sebagai_format_berkas_tidak_terpicu():
    assert extract_query_divisi("kirim file presentasi PPT untuk rapat", KODE) == set()


def test_otp_sebagai_kode_2fa_tidak_terpicu():
    assert extract_query_divisi("masukkan kode OTP dari aplikasi authenticator", KODE) == set()


def test_kata_umum_tetap_terpicu_kalau_didampingi_penunjuk():
    """
    Batas desain yang disadari: begitu kata umum ini didampingi "divisi" dkk,
    tetap dianggap merujuk divisi. False-positive yang tersisa langka --
    orang jarang menulis "divisi OTP" untuk maksud lain.
    """
    assert extract_query_divisi("kebijakan divisi OTP", KODE) == {"OTP"}


# --------------------------------------------------------------------------
# Banyak divisi sekaligus, dan divisi sendiri
# --------------------------------------------------------------------------

def test_dua_divisi_sekaligus_terdeteksi():
    disebut = extract_query_divisi("bandingkan divisi PTI dan divisi SDI", KODE)
    assert disebut == {"PTI", "SDI"}


def test_divisi_sendiri_ikut_terdeteksi_penyaringan_di_pemanggil():
    """
    extract_query_divisi TIDAK tahu divisi user sendiri -- itu urusan
    pemanggil (chat/routes.py: disebut - {user.divisi}). Fungsi ini murni
    "divisi apa saja yang disebut", supaya bisa diuji lepas dari User model.
    """
    assert extract_query_divisi("berapa anggaran divisi PTI", KODE) == {"PTI"}


def test_kode_tidak_dikenal_diabaikan():
    assert extract_query_divisi("divisi XYZ tidak ada", KODE) == set()


def test_teks_kosong_aman():
    assert extract_query_divisi("", KODE) == set()
    assert extract_query_divisi("halo apa kabar", KODE) == set()
