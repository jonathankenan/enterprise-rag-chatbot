"""
Direktori Azure AD TIRUAN — khusus pengembangan/demo.

SRS FCR-003 hal. 14 poin 2.a mewajibkan "Logon menggunakan LDAP M365 BEI".
Alur OAuth-nya sudah diimplementasi beneran di auth/routes.py lewat MSAL, tapi
menjalankannya butuh direktori Azure AD yang berisi karyawan — dan proyek
magang ini TIDAK punya akses ke tenant BEI asli. Modul ini mengisi lubang itu:
direktori karyawan palsu yang cukup untuk menguji SELURUH alur milik kita
sendiri (redirect, tukar code, pencocokan user, penolakan akun tak terdaftar,
MFA untuk IT Admin, audit log) tanpa tenant Microsoft sama sekali.

YANG DIUJI modul ini:
  * halaman login -> tombol SSO -> redirect -> callback -> sesi jadi
  * user tidak terdaftar di DB ditolak 403 (SRS hal. 64: pendaftaran oleh
    IT Admin, bukan auto-signup)
  * IT Admin tetap diminta MFA walau lolos SSO (SRS ISR-001.d)
  * auth_provider berubah jadi "azure"
  * scoping divisi & role ikut terbawa dari identitas SSO

YANG TIDAK DIUJI, dan harus jujur disebut di laporan:
  * penukaran authorization code sungguhan ke Microsoft
  * verifikasi tanda tangan id_token / JWKS
  * consent, conditional access, MFA milik Microsoft sendiri
Semua itu ada di dalam MSAL, bukan di kode kita. Kalau nanti tenant BEI (atau
tenant developer) tersedia, cukup matikan AZURE_MOCK_ENABLED — tidak ada satu
baris pun di auth/routes.py yang perlu diubah.

CARA PAKAI
    1. backend/.env:   AZURE_MOCK_ENABLED=true
    2. python -m scripts.seed_mock_directory      (daftarkan user ke DB)
    3. Login -> "Masuk dengan Microsoft" -> pilih pegawai dari daftar

JANGAN aktifkan di lingkungan yang bisa diakses orang lain: siapa pun yang
membuka halaman picker bisa masuk sebagai siapa pun tanpa kredensial. Itu
memang tujuannya, dan itu pula sebabnya defaultnya mati dan setiap login lewat
jalur ini dicatat ke audit log dengan severity "high".
"""
from urllib.parse import urlencode

from app.models import Divisi, Role

# Sengaja menyebar ke banyak divisi dan role supaya sekalian bisa dipakai
# menguji Multi-Tenant Knowledge Base (SRS poin 11) dan gating role, bukan
# cuma "berhasil login atau tidak".
MOCK_USERS = [
    # email, nama, role, divisi
    ("budi.santoso@idx.co.id",      "Budi Santoso",       Role.CONSUMER_INTERNAL, Divisi.WAS),
    ("siti.rahayu@idx.co.id",       "Siti Rahayu",        Role.CONSUMER_INTERNAL, Divisi.PLP),
    ("agus.wijaya@idx.co.id",       "Agus Wijaya",        Role.CONSUMER_INTERNAL, Divisi.PPT),
    ("dewi.lestari@idx.co.id",      "Dewi Lestari",       Role.BUSINESS_USER_DESIGNER, Divisi.PP1),
    ("rizky.pratama@idx.co.id",     "Rizky Pratama",      Role.DESIGNER,          Divisi.PP2),
    ("maya.anggraini@idx.co.id",    "Maya Anggraini",     Role.MLOPS,             Divisi.PP3),
    ("hendra.gunawan@idx.co.id",    "Hendra Gunawan",     Role.COMPLIANCE,        Divisi.SDI),
    ("lina.marlina@idx.co.id",      "Lina Marlina",       Role.AUDITOR,           Divisi.OTP),
    # IT Admin GLOBAL (divisi None) -- memicu cabang MFA di azure_callback()
    ("admin.ti@idx.co.id",          "Admin TI Pusat",     Role.IT_ADMIN,          None),
    # IT Admin TERBATAS ke satu divisi (SRS hal. 68: "Admin User dari setiap divisi")
    ("admin.pti@idx.co.id",         "Admin PTI",          Role.IT_ADMIN,          Divisi.PTI),
]

# SENGAJA TIDAK di-seed ke database oleh scripts/seed_mock_directory.py.
# Ada di "direktori Azure" tapi tidak terdaftar di aplikasi — persis kasus
# pegawai BEI yang punya akun M365 tapi belum didaftarkan IT Admin. Dipakai
# untuk menguji penolakan 403 di azure_callback(), yang kalau tidak ada entri
# seperti ini cuma bisa diuji dengan mengarang email asal.
UNREGISTERED_EMAIL = "orang.luar@idx.co.id"

_DIRECTORY = {email: (name, role, divisi) for email, name, role, divisi in MOCK_USERS}
_DIRECTORY[UNREGISTERED_EMAIL] = ("Orang Luar (belum didaftarkan)", None, None)


def directory_entries() -> list[tuple[str, str, str | None, str | None]]:
    """(email, nama, role, divisi) untuk semua akun di direktori tiruan."""
    return [(email, name, role, divisi) for email, (name, role, divisi) in _DIRECTORY.items()]


class MockMsalApp:
    """
    Pengganti msal.ConfidentialClientApplication dengan DUA metode yang persis
    dipakai auth/routes.py. Bentuk kembaliannya sengaja dibuat sama dengan MSAL
    (`id_token_claims`, `error`/`error_description`) supaya azure_callback()
    tidak perlu tahu sedang bicara dengan tiruan atau bukan -- kalau nanti
    diganti MSAL asli, tidak ada cabang khusus yang tertinggal di routes.
    """

    def __init__(self, picker_url: str):
        self._picker_url = picker_url

    def get_authorization_request_url(self, scopes, redirect_uri: str, **_kwargs) -> str:
        # Di alur asli ini URL halaman login Microsoft. Di sini: halaman picker
        # lokal yang menampilkan daftar pegawai palsu. Sama-sama "tempat user
        # membuktikan identitas lalu dikembalikan dengan ?code=".
        return f"{self._picker_url}?{urlencode({'redirect_uri': redirect_uri})}"

    def acquire_token_by_authorization_code(self, code: str, scopes, redirect_uri: str, **_kwargs) -> dict:
        # `code` di sini adalah email yang dipilih di picker. Aman untuk mode
        # tiruan; jelas TIDAK aman untuk apa pun selain itu -- alasan lain
        # kenapa modul ini harus tetap mati secara default.
        entry = _DIRECTORY.get((code or "").strip().lower())
        if not entry:
            return {
                "error": "invalid_grant",
                "error_description": (
                    f"'{code}' tidak ada di direktori Azure AD tiruan. "
                    "Pilih akun dari halaman picker, jangan ketik manual."
                ),
            }
        name, _role, _divisi = entry
        return {
            "id_token_claims": {
                "preferred_username": code.strip().lower(),
                "name": name,
                # Penanda supaya jelas di log/debug bahwa klaim ini BUKAN dari
                # Microsoft. azure_callback() tidak membacanya.
                "iss": "https://mock-directory.local/invalid",
            }
        }


def render_picker_page(redirect_uri: str) -> str:
    """Halaman HTML sederhana pengganti halaman login Microsoft."""
    rows = []
    for email, name, role, divisi in directory_entries():
        if role is None:
            badge = '<span class="warn">tidak terdaftar di aplikasi &mdash; harusnya ditolak</span>'
        else:
            badge = f'<span class="meta">{role}{" &middot; " + divisi if divisi else " &middot; global"}</span>'
        sep = "&" if "?" in redirect_uri else "?"
        href = f"{redirect_uri}{sep}{urlencode({'code': email})}"
        rows.append(
            f'<li><a href="{href}"><strong>{name}</strong>'
            f'<span class="email">{email}</span>{badge}</a></li>'
        )
    items = "\n".join(rows)
    return f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<title>Direktori Azure AD (Tiruan)</title>
<style>
 body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:620px;margin:48px auto;padding:0 20px;color:#1a1a1a}}
 h1{{font-size:20px;margin:0 0 4px}}
 .sub{{color:#666;font-size:13px;margin:0 0 20px}}
 .banner{{background:#fff4e5;border:1px solid #ffd8a8;border-radius:6px;padding:10px 12px;font-size:13px;margin-bottom:20px}}
 ul{{list-style:none;padding:0;margin:0}}
 li{{margin-bottom:8px}}
 a{{display:block;padding:12px 14px;border:1px solid #ddd;border-radius:6px;text-decoration:none;color:inherit}}
 a:hover{{border-color:#0070f3;background:#f5faff}}
 .email{{display:block;color:#666;font-size:12px;margin-top:2px}}
 .meta{{display:block;color:#888;font-size:11px;margin-top:4px;text-transform:uppercase;letter-spacing:.03em}}
 .warn{{display:block;color:#b45309;font-size:11px;margin-top:4px}}
</style></head><body>
<h1>Direktori Azure AD (Tiruan)</h1>
<p class="sub">Berdiri menggantikan halaman login Microsoft.</p>
<div class="banner"><strong>Mode pengembangan.</strong> Tidak ada kata sandi yang diperiksa &mdash;
memilih nama langsung masuk sebagai orang itu. Jangan pernah aktifkan ini di lingkungan
yang bisa dijangkau orang lain.</div>
<ul>
{items}
</ul>
</body></html>"""
