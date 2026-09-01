// Label tampilan untuk role dan divisi (SRS hal. 15 poin 2.d / hal. 8-9).
// Satu sumber untuk semua tempat yang menampilkan role ke user -- sebelumnya
// register/page.jsx sudah punya daftar serupa untuk <select>-nya sendiri;
// modul ini yang jadi acuan supaya keduanya tidak diam-diam menyimpang kalau
// salah satu diubah nanti. Samakan dengan Role.ALL di backend/app/models.py.
export const ROLE_LABELS = {
  it_admin: "IT Admin",
  designer: "Designer",
  mlops: "MLOps",
  consumer_internal: "Consumer Internal BEI",
  consumer_eipo: "Consumer Internet (E-IPO)",
  business_user_designer: "Business User Designer",
  compliance: "Compliance User",
  auditor: "Auditor View",
};

// Dipakai UI mana pun yang menampilkan role mentah dari backend (mis. kartu
// profil, daftar user admin) -- role yang belum terdaftar di sini (skema
// berubah, data lama) ditampilkan apa adanya daripada disembunyikan.
export function roleLabel(role) {
  return ROLE_LABELS[role] || role || "";
}
