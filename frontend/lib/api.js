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
const AUTH_ENDPOINTS = ["/api/auth/login", "/api/auth/register", "/api/auth/mfa", "/api/auth/azure"];

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
  register: (email, password, full_name, role = null, divisi = null) =>
    request("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name, role, divisi }),
    }),

  login: (email, password) =>
    request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  // ---- SSO Azure AD (simulasi LDAP M365 BEI, SRS hal. 64) ----
  getAzureLoginUrl: () => request("/api/auth/azure/login-url"),

  azureCallback: (code) =>
    request("/api/auth/azure/callback", {
      method: "POST",
      body: JSON.stringify({ code }),
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

  getChatHistory: (archived = false) => request(`/api/chat/history?archived=${archived}`),

  deleteChat: (chatId) => request(`/api/chat/${chatId}`, { method: "DELETE" }),

  // ---- Arsip chat (SRS poin 4: "menghapus atau mengarsipkan percakapan") ----
  archiveChat: (chatId) => request(`/api/chat/${chatId}/archive`, { method: "PATCH" }),

  unarchiveChat: (chatId) => request(`/api/chat/${chatId}/unarchive`, { method: "PATCH" }),

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

  // Tiket lahir saat pesan PERTAMA dikirim (bukan saat halaman dibuka), supaya
  // membuka "Hubungi Admin" tanpa jadi bertanya tidak membanjiri antrean admin.
  createTicketWithMessage: (content, attachedChatId = null) =>
    request("/api/helpdesk/tickets", {
      method: "POST",
      body: JSON.stringify({ content, attached_chat_id: attachedChatId }),
    }),

  // Jalur banner confidence rendah — tetap terikat ke jawaban AI yang memicu.
  escalateMessage: (chatId, messageId) =>
    request("/api/helpdesk/tickets", {
      method: "POST",
      body: JSON.stringify({ chat_id: chatId, message_id: messageId }),
    }),

  // Tiket terbuka yang DIBUAT user ini — beda dari listTickets() yang untuk
  // IT Admin berisi antrean divisinya, bukan percakapannya sendiri.
  getMyOpenTicket: () => request("/api/helpdesk/my-open-ticket"),

  getTicket: (ticketId) => request(`/api/helpdesk/tickets/${ticketId}`),

  getAttachedChat: (ticketId, chatId) =>
    request(`/api/helpdesk/tickets/${ticketId}/attached-chat/${chatId}`),

  closeTicket: (ticketId) =>
    request(`/api/helpdesk/tickets/${ticketId}/close`, { method: "POST" }),

  deleteTicket: (ticketId) =>
    request(`/api/helpdesk/tickets/${ticketId}`, { method: "DELETE" }),

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

  // F2-08: role mana boleh export chat ke PDF
  updateExportRoles: (roles) =>
    request("/api/admin/system-settings/export-roles", {
      method: "POST",
      body: JSON.stringify({ roles }),
    }),

  // ---- SRS poin 4.c-d: rate limit & API limiter dikonfigurasi IT Admin ----
  updateRateLimit: (maxMessages, windowSeconds) =>
    request("/api/admin/system-settings/rate-limit", {
      method: "POST",
      body: JSON.stringify({ max_messages: maxMessages, window_seconds: windowSeconds }),
    }),

  // ---- SRS poin 6: konfigurasi retensi data historis ----
  updateRetention: (retentionDays) =>
    request("/api/admin/system-settings/retention", {
      method: "POST",
      body: JSON.stringify({ retention_days: retentionDays }),
    }),

  applyRetention: () =>
    request("/api/admin/system-settings/retention/apply", { method: "POST" }),

  // ---- FAQ Helpdesk (dibatasi Role.IT_ADMIN — sumber RAG SRS poin 10.b) ----
  listFaqs: () => request("/api/faq"),

  createFaq: (question, answer) =>
    request("/api/faq", {
      method: "POST",
      body: JSON.stringify({ question, answer }),
    }),

  deleteFaq: (faqId) => request(`/api/faq/${faqId}`, { method: "DELETE" }),

  uploadFaqPdf: (file) => {
    const formData = new FormData();
    formData.append("file", file);
    const token = getToken();
    return fetch(`${API_URL}/api/faq/upload-pdf`, {
      method: "POST",
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const errorBody = await res.json().catch(() => ({}));
        throw new Error(errorBody.detail || `Upload gagal (${res.status})`);
      }
      return res.json();
    });
  },

  updateUserDivisi: (userId, divisi) =>
    request(`/api/admin/users/${userId}/divisi`, {
      method: "PATCH",
      body: JSON.stringify({ divisi }),
    }),

  // ---- Multi-Tenant Knowledge Base (dibatasi Role.IT_ADMIN, scope divisi otomatis di backend) ----
  listKbDocuments: () => request("/api/kb/documents"),

  uploadKbDocument: (file, divisi) => {
    const formData = new FormData();
    formData.append("file", file);
    if (divisi) formData.append("divisi", divisi);
    const token = getToken();
    return fetch(`${API_URL}/api/kb/upload`, {
      method: "POST",
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const errorBody = await res.json().catch(() => ({}));
        throw new Error(errorBody.detail || `Upload gagal (${res.status})`);
      }
      return res.json();
    });
  },

  deleteKbDocument: (docId) => request(`/api/kb/documents/${docId}`, { method: "DELETE" }),
};
