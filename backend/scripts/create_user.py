"""
Buat akun lokal untuk pengembangan (role apa pun, termasuk IT_ADMIN).

    cd backend
    python -m scripts.create_user admin@idx.co.id --role it_admin
    python -m scripts.create_user admin.pti@idx.co.id --role it_admin --divisi PTI
    python -m scripts.create_user user.pti@idx.co.id --divisi PTI   # consumer, default
    python -m scripts.create_user user.pti@idx.co.id --reset-password

GLOBAL vs DIVISI bukan dua role, melainkan satu role IT_ADMIN yang dibedakan
kolom `divisi` (lihat get_divisi_scope di auth/utils.py):

    divisi = None   -> admin global : boleh mengelola SEMUA divisi + Company Wide
    divisi = "PTI"  -> admin divisi : cuma boleh mengelola PTI

Konsekuensi yang perlu disadari saat menguji: `divisi` dipakai untuk DUA
makna sekaligus -- keanggotaan divisi DAN cakupan kewenangan admin. Karena
retrieval memfilter dengan allowed_divisi = [COMPANY_WIDE] + [user.divisi],
admin global (divisi None) di chat-nya sendiri cuma menerima knowledge
Company Wide; dia boleh mengunggah dan menghapus dokumen divisi mana pun,
tapi tidak bisa membacanya lewat chat. Arahnya aman (lebih ketat, bukan lebih
longgar), tapi hampir pasti bukan yang dimaksud SRS.

CATATAN LOGIN: role IT_ADMIN wajib MFA. Login pertama tidak langsung memberi
access token -- responsnya `mfa_setup_required` beserta `mfa_token`, lalu
lanjut ke /api/auth/mfa/setup dan /api/auth/mfa/setup/confirm memakai aplikasi
authenticator. Itu memang alurnya, bukan kegagalan login.

Script ini UNTUK PENGEMBANGAN LOKAL. Sandi dicetak sekali ke layar dan tidak
disimpan ke mana pun; jangan dipakai membuat akun di lingkungan yang bisa
dijangkau orang lain.
"""
import argparse
import secrets
import string
import sys

from app.database import SessionLocal
from app.models import User, Role, Divisi
from app.auth.utils import hash_password


def _random_password(n: int = 20) -> str:
    # Tanpa karakter yang gampang keliru dibaca dari layar (0/O, 1/l/I).
    alphabet = (string.ascii_letters + string.digits).translate(
        str.maketrans("", "", "0O1lI")
    ) + "!@#$%^&*-_"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def main() -> int:
    ap = argparse.ArgumentParser(description="Buat akun lokal untuk pengembangan.")
    # Default consumer_internal, BUKAN it_admin: akun uji sehari-hari
    # jauh lebih sering butuh user biasa, dan it_admin memaksa MFA.
    ap.add_argument("email")
    ap.add_argument("--role", default=Role.CONSUMER_INTERNAL, choices=list(Role.ALL))
    ap.add_argument("--name", default=None, help="Nama lengkap (default: dari email)")
    ap.add_argument("--divisi", default=None, choices=list(Divisi.ALL),
                    help="Kosongkan untuk admin GLOBAL")
    ap.add_argument("--password", default=None, help="Kosongkan untuk sandi acak")
    ap.add_argument("--reset-password", action="store_true",
                    help="Kalau email sudah ada: setel ulang sandi, role, dan divisi")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email).first()
        if user and not args.reset_password:
            scope = user.divisi or "global"
            print(f"'{args.email}' sudah ada (role={user.role}, scope={scope}).")
            print("Pakai --reset-password kalau memang mau menimpanya.")
            return 1

        password = args.password or _random_password()
        name = args.name or args.email.split("@")[0].replace(".", " ").title()

        if user:
            user.hashed_password = hash_password(password)
            user.role = args.role
            user.divisi = args.divisi
            user.full_name = name
            # MFA di-reset supaya alur setup bisa dijalani dari awal; secret
            # lama tidak ada gunanya kalau sandinya diganti.
            user.mfa_enabled = False
            user.totp_secret = None
            aksi = "diperbarui"
        else:
            user = User(
                email=args.email, hashed_password=hash_password(password),
                full_name=name, role=args.role, divisi=args.divisi,
                auth_provider="local",
            )
            db.add(user)
            aksi = "dibuat"
        db.commit()

        scope = args.divisi or "GLOBAL (semua divisi + Company Wide)"
        print(f"\nAkun {aksi}.")
        print(f"  email  : {args.email}")
        print(f"  nama   : {name}")
        print(f"  role   : {args.role}")
        print(f"  scope  : {scope}")
        print(f"  sandi  : {password}")
        print("\nSandi di atas TIDAK disimpan di mana pun — catat sekarang.")
        if args.role == Role.IT_ADMIN:
            print("Login pertama akan meminta setup MFA (role IT_ADMIN wajib MFA).")
        if args.role == Role.IT_ADMIN and args.divisi is None:
            print("\nCatatan: sebagai admin global, di chat sendiri akun ini hanya")
            print("menerima knowledge Company Wide — bukan KB divisi mana pun.")
            print("Itu perilaku sekarang, lihat docstring script ini.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
