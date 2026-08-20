/**
 * [PENANGGUNG JAWAB: Anggota B]
 * Wrapper sederhana untuk memanggil backend FastAPI.
 * Semua pemanggilan API dari frontend sebaiknya lewat file ini,
 * supaya kalau ada perubahan endpoint, cukup diubah di satu tempat.
 */
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// startsWith, jadi "/api/auth/mfa" otomatis cakup /mfa/setup, /mfa/setup/confirm, /mfa/verify —
// endpoint-endpoint ini sengaja dikecualikan dari auto-redirect 401 (lihat request()
// di bawah), karena 401 di sini artinya "kode MFA salah", BUKAN "sesi berakhir".
const AUTH_ENDPOINTS = ["/api/auth/login", "/api/auth/register", "/api/auth/mfa"];

function getToken() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

function clearToken() {
  if (typeof window === "undefined") return;
  localStorage.removeItem("access_token");
}

function extractErrorMessage(errorBody, statusCode) {
  const detail = errorBody?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail) && detail.length > 0) {
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

  // ---- MFA (SRS ISR-001.d — wajib untuk role IT Admin) ----
  mfaSetup: (mfaToken) =>
    request("/api/auth/mfa/setup", {
      method: "POST",
      body: JSON.stringify({ mfa_token: mfaToken }),
    }),

  mfaSetupConfirm: (mfaToken, secret, code) =>
    request("/api/auth/mfa/setup/confirm", {
      method: "POST",
      body: JSON.stringify({ mfa_token: mfaToken, secret, code }),
    }),

  mfaVerify: (mfaToken, code) =>
    request("/api/auth/mfa/verify", {
      method: "POST",
      body: JSON.stringify({ mfa_token: mfaToken, code }),
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

  deleteChat: (chatId) => request(`/api/chat/${chatId}`, { method: "DELETE" }),

  renameChat: (chatId, title) =>
    request(`/api/chat/${chatId}/rename`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  getMessages: (chatId) => request(`/api/chat/${chatId}/messages`),

  sendMessage: (chatId, content, llmProvider = "on-prem") =>
    request("/api/chat/message", {
      method: "POST",
      body: JSON.stringify({ chat_id: chatId, content, llm_provider: llmProvider }),
    }),

  uploadDocument: (file, chatId) => {
    const formData = new FormData();
    formData.append("file", file);
    if (chatId) {
      formData.append("chat_id", chatId);
    }
    const token = getToken();
    return fetch(`${API_URL}/api/documents/upload`, {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const errorBody = await res.json().catch(() => ({}));
        throw new Error(errorBody.detail || `Upload gagal (${res.status})`);
      }
      return res.json();
    });
  },

  exportPdf: (chatId) => {
    const token = getToken();
    return fetch(`${API_URL}/api/chat/${chatId}/export-pdf`, {
      method: "GET",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    }).then(async (res) => {
      if (!res.ok) {
        const errorBody = await res.json().catch(() => ({}));
        throw new Error(errorBody.detail || `Export PDF gagal (${res.status})`);
      }
      return res.blob();
    });
  },

  // ---- Audit log (dibatasi Role.AUDIT_VIEWERS di backend — lihat guardrail/routes.py) ----
  getAuditSummary: (sinceHours = 24) => request(`/api/audit/summary?since_hours=${sinceHours}`),

  searchAudit: (params = {}) => {
    const query = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v !== null && v !== undefined))
    ).toString();
    return request(`/api/audit/search${query ? `?${query}` : ""}`);
  },

  exportAuditCsv: (params = {}) => {
    const token = getToken();
    const query = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v !== null && v !== undefined))
    ).toString();
    return fetch(`${API_URL}/api/audit/export${query ? `?${query}` : ""}`, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    }).then(async (res) => {
      if (!res.ok) {
        const errorBody = await res.json().catch(() => ({}));
        throw new Error(errorBody.detail || `Export gagal (${res.status})`);
      }
      return res.blob();
    });
  },

  // ---- Helpdesk tickets ----
  // listTickets & closeTicket dibatasi Role.IT_ADMIN di backend.
  // createTicket & getTicket bisa dipanggil pemilik tiket ATAU IT_ADMIN
  // (lihat helpdesk/routes.py: _get_ticket_or_403).
  listTickets: (statusFilter) =>
    request(`/api/helpdesk/tickets${statusFilter ? `?status=${statusFilter}` : ""}`),

  createTicket: (messageId) =>
    request("/api/helpdesk/tickets", {
      method: "POST",
      body: JSON.stringify({ message_id: messageId }),
    }),

  getTicket: (ticketId) => request(`/api/helpdesk/tickets/${ticketId}`),

  closeTicket: (ticketId) =>
    request(`/api/helpdesk/tickets/${ticketId}/close`, { method: "POST" }),

  // WebSocket tidak lewat request() (bukan HTTP fetch biasa) — helper ini
  // cuma menyusun URL-nya (ws:// bukan http://) + token lewat query param,
  // karena browser tidak bisa kirim header Authorization custom saat
  // WebSocket handshake.
  ticketSocketUrl: (ticketId) => {
    const token = getToken();
    const wsBase = API_URL.replace(/^http/, "ws");
    return `${wsBase}/ws/helpdesk/tickets/${ticketId}?token=${encodeURIComponent(token || "")}`;
  },

  // ---- Manajemen user (dibatasi Role.IT_ADMIN — lihat admin/routes.py) ----
  listUsers: () => request("/api/admin/users"),

  updateUserRole: (userId, role) =>
    request(`/api/admin/users/${userId}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),

  getSystemSettings: () => request("/api/admin/system-settings"),

  toggleCommercialLlm: () =>
    request("/api/admin/system-settings/toggle-commercial-llm", { method: "POST" }),
};