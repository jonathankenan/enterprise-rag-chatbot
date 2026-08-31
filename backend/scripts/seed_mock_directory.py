"""
Daftarkan pegawai dari direktori Azure AD tiruan ke tabel users.

Perlu dijalankan karena azure_callback() SENGAJA menolak akun yang belum
terdaftar (SRS FCR-003 hal. 64: pendaftaran user Active Directory dilakukan
IT Admin, bukan auto-signup). Jadi "ada di direktori" dan "boleh masuk" itu
dua hal berbeda — dan script ini cuma mengurus yang kedua.

    cd backend
    python -m scripts.seed_mock_directory            # tambah yang belum ada
    python -m scripts.seed_mock_directory --reset    # hapus dulu, lalu isi ulang

UNREGISTERED_EMAIL sengaja TIDAK ikut di-seed: dia ada di picker tapi tidak di
database, supaya jalur penolakan 403 bisa diuji tanpa mengarang email asal.

Idempoten: menjalankan dua kali tidak menggandakan user. User yang sudah ada
di-update role/divisi-nya agar cocok dengan direktori — kalau kamu mengubah
MOCK_USERS, cukup jalankan ulang.
"""
import sys
import uuid

from app.database import SessionLocal
from app.models import User
from app.auth.utils import hash_password
from app.auth.mock_directory import MOCK_USERS, UNREGISTERED_EMAIL


def main(reset: bool = False) -> None:
    db = SessionLocal()
    try:
        emails = [email for email, _, _, _ in MOCK_USERS]

        if reset:
            deleted = db.query(User).filter(User.email.in_(emails)).delete(synchronize_session=False)
            db.commit()
            print(f"--reset: {deleted} user dihapus\n")

        created = updated = 0
        for email, full_name, role, divisi in MOCK_USERS:
            user = db.query(User).filter(User.email == email).first()
            if user:
                if user.role != role or user.divisi != divisi or user.full_name != full_name:
                    user.full_name, user.role, user.divisi = full_name, role, divisi
                    updated += 1
                    print(f"  ubah   {email:32} {role} / {divisi or 'global'}")
                continue

            db.add(User(
                id=str(uuid.uuid4()),
                email=email,
                full_name=full_name,
                role=role,
                divisi=divisi,
                auth_provider="azure",
                # Login lokal untuk akun SSO harus MUSTAHIL, bukan sekadar
                # "sulit ditebak": hash dari secret acak yang tidak pernah
                # disimpan di mana pun, jadi tidak ada password yang cocok.
                # Kolomnya nullable=False, jadi tidak bisa dikosongkan saja.
                hashed_password=hash_password(uuid.uuid4().hex + uuid.uuid4().hex),
            ))
            created += 1
            print(f"  tambah {email:32} {role} / {divisi or 'global'}")

        db.commit()
        print(f"\n{created} dibuat, {updated} diperbarui, {len(MOCK_USERS)} total di direktori.")
        print(f"\nTIDAK di-seed (sengaja, untuk menguji penolakan 403): {UNREGISTERED_EMAIL}")
        print("\nLangkah berikutnya: set AZURE_MOCK_ENABLED=true di backend/.env, restart backend,")
        print("lalu login lewat tombol Microsoft di halaman /login.")
    finally:
        db.close()


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
