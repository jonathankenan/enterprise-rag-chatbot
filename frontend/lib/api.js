/**
 * [PENANGGUNG JAWAB: Anggota B]
 * Wrapper sederhana untuk memanggil backend FastAPI.
 * Semua pemanggilan API dari frontend sebaiknya lewat file ini,
 * supaya kalau ada perubahan endpoint, cukup diubah di satu tempat.
 */
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getToken() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
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
    const errorBody = await res.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Request gagal (${res.status})`);
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
    localStorage.removeItem("access_token");
  },

  isLoggedIn: () => {
    return !!getToken();
  },

  getMe: () => request("/api/auth/me"),

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