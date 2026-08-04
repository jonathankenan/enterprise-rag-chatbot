/**
 * [PENANGGUNG JAWAB: Anggota B]
 * Wrapper sederhana untuk memanggil backend FastAPI.
 * Semua pemanggilan API dari frontend sebaiknya lewat file ini,
 * supaya kalau ada perubahan endpoint, cukup diubah di satu tempat.
 */
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const AUTH_ENDPOINTS = ["/api/auth/login", "/api/auth/register"];

function getToken() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

function clearToken() {
  if (typeof window === "undefined") return;
  localStorage.removeItem("access_token");
}

/**
 * FastAPI mengembalikan error dalam beberapa bentuk berbeda:
 * 1. String biasa: {"detail": "Email sudah terdaftar"}
 * 2. Array validasi Pydantic: {"detail": [{"msg": "...", "loc": [...], ...}]}
 * Fungsi ini menyeragamkan keduanya jadi satu string yang mudah dibaca user.
 */
function extractErrorMessage(errorBody, statusCode) {
  const detail = errorBody?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail) && detail.length > 0) {
    // Ambil pesan error pertama saja, cukup untuk ditampilkan ke user
    return detail[0].msg || "Data yang dimasukkan tidak valid";
  }

  return `Terjadi kesalahan (kode ${statusCode})`;
}

async function request(path, options = {}) {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (!res.ok) {
    const isAuthEndpoint = AUTH_ENDPOINTS.some((ep) => path.startsWith(ep));
    if (res.status === 401 && !isAuthEndpoint) {
      clearToken();
      if (typeof window !== "undefined") {
        window.location.href = "/login?expired=true";
      }
    }

    const errorBody = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessage(errorBody, res.status));
  }
  return res.json();
}

export const api = {
  register: (email, password, full_name) =>
    request("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name }),
    }),

  login: (email, password) =>
    request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  logout: () => {
    clearToken();
  },

  isLoggedIn: () => {
    return !!getToken();
  },

  getMe: () => request("/api/auth/me"),

  changePassword: (oldPassword, newPassword) =>
    request("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    }),

  createChat: (title) =>
    request("/api/chat", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),

  getChatHistory: () => request("/api/chat/history"),

  getMessages: (chatId) => request(`/api/chat/${chatId}/messages`),

  sendMessage: (chatId, content) =>
    request("/api/chat/message", {
      method: "POST",
      body: JSON.stringify({ chat_id: chatId, content }),
    }),
};