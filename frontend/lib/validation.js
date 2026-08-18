/**
 * [PENANGGUNG JAWAB: Anggota B]
 * Aturan password — SRS ISR-002.a/b: kompleks (huruf besar, huruf kecil,
 * angka, karakter khusus) dan minimal 12 karakter. HARUS sinkron dengan
 * validate_password_strength() di backend/app/schemas.py — backend tetap
 * jadi penjaga sesungguhnya (validasi ini cuma buat UX cepat sebelum
 * request dikirim), tapi kalau dua tempat ini berbeda, user bisa dapat
 * pesan error yang membingungkan (lolos di frontend, ditolak di backend).
 */
const SPECIAL_CHARS_REGEX = /[!@#$%^&*()_+\-=[\]{}|;:'",.<>/?`~\\]/;

export function getPasswordError(password) {
  if (password.length < 12) return "Password minimal 12 karakter";
  if (!/[A-Z]/.test(password)) return "Password harus mengandung huruf besar";
  if (!/[a-z]/.test(password)) return "Password harus mengandung huruf kecil";
  if (!/[0-9]/.test(password)) return "Password harus mengandung angka";
  if (!SPECIAL_CHARS_REGEX.test(password)) return "Password harus mengandung karakter khusus (mis. ! @ # $ %)";
  return null;
}
