"use client";
// [PENANGGUNG JAWAB: Anggota A & B]

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "../../lib/api";

export default function ChatPage() {
  const router = useRouter();
  const [chatId, setChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [chatHistory, setChatHistory] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [llmProvider, setLlmProvider] = useState("on-prem");
  const [loginInfo, setLoginInfo] = useState(null); // SRS ISR-001.g
  const [activeTickets, setActiveTickets] = useState([]); // tiket helpdesk milik user yang masih "open" — navigasi balik
  const [editingChatId, setEditingChatId] = useState(null); // id chat yang sedang di-rename inline
  const [editTitle, setEditTitle] = useState("");           // nilai input sementara saat rename

  // Guard supaya loadChatHistory() (yang bisa memicu pembuatan chat baru
  // otomatis kalau history kosong) tidak terpanggil dua kali. React 18
  // Strict Mode (aktif default di Next.js dev mode) SENGAJA menjalankan
  // useEffect dua kali berturut-turut untuk membongkar efek samping yang
  // tidak idempotent — persis seperti loadChatHistory() di bawah. useRef
  // (bukan useState) dipakai karena nilainya harus terbaca-tulis SEKARANG
  // JUGA secara sinkron sebelum effect kedua sempat jalan; kalau pakai
  // state, update-nya baru "kelihatan" di render berikutnya — terlambat
  // untuk mencegah pemanggilan kedua yang juga terjadi secara sinkron.
  const didInitChatHistory = useRef(false);

  useEffect(() => {
    if (!api.isLoggedIn()) {
      router.push("/login");
      return;
    }

    api.getMe()
      .then((user) => {
        setCurrentUser(user);
        setCheckingSession(false);
        // IT Admin punya halaman /helpdesk sendiri buat lihat SEMUA tiket
        // (antrian) — daftar di sidebar ini khusus "tiket SAYA" buat user
        // biasa navigasi balik, jadi sengaja tidak dipanggil untuk admin
        // supaya tidak tumpang tindih/membingungkan dengan halaman itu.
        if (user.role !== "it_admin") {
          api.listTickets("open").then(setActiveTickets).catch(() => {});
        }
      })
      .catch(() => {
        api.logout();
        router.push("/login");
      });

    if (didInitChatHistory.current) return;
    didInitChatHistory.current = true;
    loadChatHistory();

    // SRS ISR-001.g: tampilkan SEKALI info login sebelumnya + jumlah
    // percobaan gagal, lalu langsung hapus dari sessionStorage supaya tidak
    // muncul lagi kalau halaman ini di-refresh berkali-kali.
    const raw = sessionStorage.getItem("login_info");
    if (raw) {
      sessionStorage.removeItem("login_info");
      try {
        setLoginInfo(JSON.parse(raw));
      } catch {
        // abaikan kalau datanya rusak
      }
    }
  }, []);

  function handleLogout() {
    api.logout();
    router.push("/login");
  }

  async function loadChatHistory() {
    try {
      const history = await api.getChatHistory();
      setChatHistory(history);

      if (history.length > 0 && !chatId) {
        selectChat(history[0].id);
      } else if (history.length === 0) {
        handleNewChat();
      }
    } catch (err) {
      console.error("Gagal memuat history:", err);
    }
  }

  async function selectChat(id) {
    setChatId(id);
    setLoading(true);
    setMessages([]);
    try {
      const msgs = await api.getMessages(id);
      setMessages(msgs);
    } catch (err) {
      console.error("Gagal memuat pesan:", err);
    } finally {
      setLoading(false);
    }
  }

  async function handleNewChat() {
    try {
      const chat = await api.createChat("Percakapan Baru");
      setChatId(chat.id);
      setMessages([]);
      loadChatHistory();
    } catch (err) {
      console.error("Gagal membuat percakapan baru:", err);
    }
  }

  async function handleDeleteChat(e, id) {
    e.stopPropagation();
    try {
      await api.deleteChat(id);
      if (chatId === id) {
        setChatId(null);
        setMessages([]);
      }
      loadChatHistory();
    } catch (err) {
      console.error("Gagal menghapus percakapan:", err);
    }
  }

  function startEditing(e, chat) {
    e.stopPropagation();
    setEditingChatId(chat.id);
    setEditTitle(chat.title);
  }

  async function saveTitle(e, chatId) {
    e.stopPropagation();
    const trimmed = editTitle.trim();
    if (!trimmed) {
      setEditingChatId(null);
      return;
    }
    try {
      const updated = await api.renameChat(chatId, trimmed);
      setChatHistory((prev) =>
        prev.map((c) => (c.id === chatId ? { ...c, title: updated.title } : c))
      );
    } catch (err) {
      alert("Gagal mengubah judul: " + err.message);
    } finally {
      setEditingChatId(null);
    }
  }

  async function handleSend(e) {
    e.preventDefault();
    if (!input.trim() || !chatId) return;

    const userMessage = { sender: "user", content: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    try {
      const result = await api.sendMessage(chatId, userMessage.content, llmProvider);

      if (result.new_title) {
        loadChatHistory();
      }

      setMessages((prev) => [
        ...prev,
        {
          sender: "assistant",
          content: result.reply,
          llm_used: result.llm_used,
          confidence_score: result.confidence_score,
          pii_detected: result.pii_detected,
          message_id: result.message_id,
          escalation_offered: result.escalation_offered,
          escalation_status: result.escalation_offered ? "offered" : null,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [...prev, { sender: "assistant", content: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  }

  // SRS FCR-003 poin 7: "sistem MENAWARKAN eskalasi" — tiket baru dibuat
  // kalau user klik tombol ini, bukan otomatis. message_id dikirim ke
  // backend supaya tiket terikat ke jawaban low-confidence yang tepat.
  async function handleEscalate(messageId) {
    setMessages((prev) =>
      prev.map((m) => (m.message_id === messageId ? { ...m, escalation_status: "creating" } : m))
    );
    try {
      const ticket = await api.createTicket(messageId);
      setMessages((prev) =>
        prev.map((m) => (m.message_id === messageId ? { ...m, escalation_status: "created", ticket_id: ticket.id } : m))
      );
      setActiveTickets((prev) => [ticket, ...prev]);
      router.push(`/helpdesk/tickets/${ticket.id}`);
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) => (m.message_id === messageId ? { ...m, escalation_status: "offered" } : m))
      );
      alert(err.message || "Gagal membuat tiket eskalasi");
    }
  }

  function handleDismissEscalation(messageId) {
    setMessages((prev) =>
      prev.map((m) => (m.message_id === messageId ? { ...m, escalation_status: "dismissed" } : m))
    );
  }

  async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    setUploading(true);
    try {
      const result = await api.uploadDocument(file, chatId);
      setMessages((prev) => [
        ...prev,
        {
          sender: "assistant",
          content: `✅ Dokumen "${result.filename}" berhasil diunggah dan diindeks (${result.chunks_indexed} potongan teks).`,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { sender: "assistant", content: `❌ Gagal mengunggah dokumen: ${err.message}` },
      ]);
    } finally {
      setUploading(false);
      e.target.value = null;
    }
  }

  async function handleExportPdf() {
    if (!chatId) return;
    setExportingPdf(true);
    try {
      const blob = await api.exportPdf(chatId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `chat_${chatId}_export.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      alert("Gagal mengekspor PDF: " + err.message);
    } finally {
      setExportingPdf(false);
    }
  }

  if (checkingSession) {
    return (
      <div style={{ maxWidth: 700, margin: "80px auto", textAlign: "center" }}>
        <p style={{ color: "#888" }}>Memeriksa sesi...</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "sans-serif" }}>
      {/* SIDEBAR */}
      <div style={{
        width: "280px",
        borderRight: "1px solid #ddd",
        padding: "20px",
        display: "flex",
        flexDirection: "column",
        background: "#f9f9f9"
      }}>
        <h2>Riwayat Chat</h2>
        <button
          onClick={handleNewChat}
          style={{
            padding: "10px",
            marginBottom: "20px",
            background: "#0070f3",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: "pointer"
          }}>
          + Percakapan Baru
        </button>
        <div style={{ overflowY: "auto", flex: 1 }}>
          {chatHistory.map((chat) => (
            <div
              key={chat.id}
              onClick={() => selectChat(chat.id)}
              style={{
                padding: "12px",
                marginBottom: "8px",
                background: chat.id === chatId ? "#e0e0e0" : "white",
                borderRadius: "4px",
                cursor: "pointer",
                border: "1px solid #ddd"
              }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                {editingChatId === chat.id ? (
                  // ── Inline edit mode ──
                  <>
                    <input
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveTitle(e, chat.id);
                        if (e.key === "Escape") { e.stopPropagation(); setEditingChatId(null); }
                      }}
                      onClick={(e) => e.stopPropagation()}
                      maxLength={100}
                      style={{
                        flex: 1,
                        fontSize: "13px",
                        padding: "2px 6px",
                        borderRadius: "3px",
                        border: "1px solid #0070f3",
                        marginRight: "4px",
                        outline: "none",
                      }}
                    />
                    <button
                      onClick={(e) => saveTitle(e, chat.id)}
                      title="Simpan"
                      style={{ background: "transparent", border: "none", cursor: "pointer", color: "#2e7d32", padding: "0 3px", fontSize: "14px" }}
                    >✓</button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setEditingChatId(null); }}
                      title="Batal"
                      style={{ background: "transparent", border: "none", cursor: "pointer", color: "#888", padding: "0 3px", fontSize: "14px" }}
                    >✕</button>
                  </>
                ) : (
                  // ── Normal display mode ──
                  <>
                    <div style={{ fontWeight: "bold", fontSize: "14px", flex: 1, paddingRight: "8px" }}>{chat.title}</div>
                    <div style={{ display: "flex", gap: "2px", flexShrink: 0 }}>
                      <button
                        onClick={(e) => startEditing(e, chat)}
                        title="Ubah nama"
                        style={{ background: "transparent", border: "none", cursor: "pointer", color: "#555", padding: "0 3px", fontSize: "13px", lineHeight: "1" }}
                      >✏️</button>
                      <button
                        onClick={(e) => handleDeleteChat(e, chat.id)}
                        title="Hapus percakapan"
                        style={{ background: "transparent", border: "none", cursor: "pointer", color: "#d32f2f", padding: "0 4px", fontSize: "14px", lineHeight: "1" }}
                      >✕</button>
                    </div>
                  </>
                )}
              </div>
              <div style={{ fontSize: "11px", color: "#888", marginTop: "4px" }}>
                {new Date(chat.created_at.endsWith("Z") ? chat.created_at : chat.created_at + "Z").toLocaleString()}
              </div>
            </div>
          ))}
        </div>

        {/* Navigasi balik ke tiket helpdesk yang masih aktif (status "open")
            — dibutuhkan karena redirect ke halaman tiket cuma terjadi SEKALI
            waktu klik "Ya, eskalasi"; kalau user pindah ke chat lain lalu
            mau balik, tidak ada jalan lain tanpa ini. Cuma untuk user biasa
            (lihat useEffect di atas — tidak di-fetch untuk IT Admin). */}
        {activeTickets.length > 0 && (
          <div style={{ borderTop: "1px solid #ddd", paddingTop: 12, marginTop: 12 }}>
            <h3 style={{ margin: "0 0 8px", fontSize: 13, color: "#666" }}>🎫 Tiket Helpdesk Aktif</h3>
            {activeTickets.map((t) => (
              <Link
                key={t.id}
                href={`/helpdesk/tickets/${t.id}`}
                style={{ display: "block", padding: "8px 10px", marginBottom: 6, background: "#e0f2fe", border: "1px solid #7dd3fc", borderRadius: 4, fontSize: 12, color: "#0c4a6e" }}
              >
                Confidence {t.confidence_score}% — buka chat →
              </Link>
            ))}
          </div>
        )}

        {/* Info user + logout, diletakkan di bawah sidebar */}
        <div style={{ borderTop: "1px solid #ddd", paddingTop: 12, marginTop: 12 }}>
          {currentUser && (
            <p style={{ margin: "0 0 8px", fontSize: 13, color: "#666" }}>
              {currentUser.full_name || currentUser.email}
              <br />
              <Link href="/change-password">Ganti Password</Link>
              {/* Cuma tampil untuk role IT Admin/Compliance/Auditor — samakan
                  dengan Role.AUDIT_VIEWERS di backend/app/models.py. Ini
                  sekadar sembunyikan menu, BUKAN penegakan akses (itu tugas
                  backend); user role lain yang paksa buka /audit lewat URL
                  tetap akan ditolak halaman itu sendiri. */}
              {["it_admin", "compliance", "auditor"].includes(currentUser.role) && (
                <>
                  {" · "}
                  <Link href="/audit">Audit Log</Link>
                </>
              )}
              {currentUser.role === "it_admin" && (
                <>
                  {" · "}
                  <Link href="/helpdesk">Tiket Helpdesk</Link>
                  {" · "}
                  <Link href="/admin">Kelola User</Link>
                </>
              )}
            </p>
          )}
          <button
            onClick={handleLogout}
            style={{ width: "100%", padding: "8px", background: "#eee", border: "1px solid #ccc", borderRadius: 4, cursor: "pointer" }}
          >
            Keluar
          </button>
        </div>
      </div>

      {/* MAIN CHAT AREA */}
      <div style={{ flex: 1, padding: "20px 40px", display: "flex", flexDirection: "column", maxWidth: "900px", margin: "0 auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <h1 style={{ margin: 0 }}>Generic ChatBot AI</h1>
          {chatId && messages.length > 0 && (
            <button
              onClick={handleExportPdf}
              disabled={exportingPdf}
              style={{
                padding: "8px 16px",
                background: "#28a745",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: exportingPdf ? "wait" : "pointer"
              }}
            >
              {exportingPdf ? "Mengekspor..." : "⬇ Export PDF"}
            </button>
          )}
        </div>

        {/* SRS ISR-001.g: waktu login sebelumnya + jumlah percobaan gagal
            sejak saat itu. Cuma tampil sekali (data dihapus dari
            sessionStorage begitu dibaca), warna kuning kalau ada percobaan
            gagal (kemungkinan indikasi akun disasar orang lain). */}
        {loginInfo && (
          <div style={{
            padding: "8px 12px", marginBottom: 12, borderRadius: 4, fontSize: 13,
            background: loginInfo.failed_attempts_since_last_login > 0 ? "#fff3cd" : "#e7f3ff",
            border: `1px solid ${loginInfo.failed_attempts_since_last_login > 0 ? "#ffe69c" : "#b6d4fe"}`,
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}>
            <span>
              {loginInfo.previous_login_at
                ? `Login sebelumnya: ${new Date(loginInfo.previous_login_at.endsWith("Z") ? loginInfo.previous_login_at : loginInfo.previous_login_at + "Z").toLocaleString()}`
                : "Ini adalah login pertama Anda."}
              {loginInfo.failed_attempts_since_last_login > 0 && (
                <> — <b>{loginInfo.failed_attempts_since_last_login} percobaan login gagal</b> tercatat sejak saat itu.</>
              )}
            </span>
            <button onClick={() => setLoginInfo(null)} style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: 14 }}>✕</button>
          </div>
        )}

        <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, flex: 1, overflowY: "auto", marginBottom: "20px", background: "white" }}>
          {messages.map((m, i) => (
            <div key={i} style={{ marginBottom: 12, textAlign: m.sender === "user" ? "right" : "left" }}>
              <div
                style={{
                  display: "inline-block",
                  padding: "8px 12px",
                  borderRadius: 8,
                  background: m.sender === "user" ? "#DCF0FF" : "#F1F1F1",
                  maxWidth: "80%",
                  textAlign: "left"
                }}
              >
                {m.content}
              </div>
              {m.llm_used && (
                <div style={{ fontSize: 11, color: "#888", marginTop: 2 }}>
                  sumber: {m.llm_used}
                  {m.confidence_score !== undefined && m.confidence_score !== null && (
                    <span style={{ marginLeft: 8, fontWeight: "bold", color: m.confidence_score >= 80 ? "#2e7d32" : m.confidence_score >= 50 ? "#ed6c02" : "#d32f2f" }}>
                      • keyakinan: {m.confidence_score}%
                    </span>
                  )}
                </div>
              )}
              {m.pii_detected && (
                <div style={{ fontSize: 11, color: "#b45309", marginTop: 2, fontWeight: 500 }}>
                  ⚠ Data pribadi terdeteksi pada pesan ini — disamarkan otomatis sebelum diproses AI.
                </div>
              )}
              {m.escalation_status && m.escalation_status !== "dismissed" && (
                <div style={{ fontSize: 12, color: "#0c4a6e", marginTop: 6, padding: 8, background: "#e0f2fe", border: "1px solid #7dd3fc", borderRadius: 6, maxWidth: "80%" }}>
                  {(m.escalation_status === "offered" || m.escalation_status === "creating") && (
                    <>
                      <div style={{ marginBottom: 6 }}>🎫 Jawaban ini kurang meyakinkan. Ingin eskalasi ke tim helpdesk (chat langsung dengan admin)?</div>
                      <button
                        disabled={m.escalation_status === "creating"}
                        onClick={() => handleEscalate(m.message_id)}
                        style={{ marginRight: 8, padding: "4px 10px", fontSize: 12, background: "#0070f3", color: "#fff", border: "none", borderRadius: 4 }}
                      >
                        {m.escalation_status === "creating" ? "Membuat tiket..." : "Ya, eskalasi"}
                      </button>
                      <button
                        disabled={m.escalation_status === "creating"}
                        onClick={() => handleDismissEscalation(m.message_id)}
                        style={{ padding: "4px 10px", fontSize: 12, background: "transparent", border: "1px solid #94a3b8", borderRadius: 4 }}
                      >
                        Tidak, terima kasih
                      </button>
                    </>
                  )}
                  {m.escalation_status === "created" && (
                    <>
                      ✅ Tiket dibuat.{" "}
                      <Link href={`/helpdesk/tickets/${m.ticket_id}`} style={{ color: "#0070f3", fontWeight: 600 }}>
                        Buka chat dengan admin →
                      </Link>
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
          {loading && <p style={{ color: "#888" }}>Sedang memproses...</p>}
        </div>

        <form onSubmit={handleSend} style={{ display: "flex", gap: 8 }}>
          <select
            value={llmProvider}
            onChange={(e) => setLlmProvider(e.target.value)}
            style={{ padding: 10, borderRadius: 4, border: "1px solid #ccc" }}
          >
            <option value="on-prem">On-Premise (Ollama)</option>
            <option value="groq">GPT-OSS 120B (Groq)</option>
            <option value="gemini">Gemini Flash (Google)</option>
            <option value="mistral">Mistral Small</option>
            <option value="cloudflare">Llama 3.3 70B (Cloudflare)</option>
          </select>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ketik pertanyaan..."
            style={{ flex: 1, padding: 10, borderRadius: "4px", border: "1px solid #ccc" }}
          />
          <input
            type="file"
            accept=".pdf"
            id="file-upload"
            style={{ display: "none" }}
            onChange={handleFileUpload}
            disabled={uploading}
          />
          <label
            htmlFor="file-upload"
            style={{
              padding: "10px 16px",
              background: "#eee",
              border: "1px solid #ccc",
              cursor: uploading ? "wait" : "pointer",
              borderRadius: 4,
              display: "flex",
              alignItems: "center"
            }}
          >
            {uploading ? "Mengunggah..." : "📄 Upload PDF"}
          </label>
          <button
            type="submit"
            disabled={loading}
            style={{
              padding: "10px 20px",
              background: "#0070f3",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: loading ? "not-allowed" : "pointer"
            }}>
            Kirim
          </button>
        </form>
      </div>
    </div>
  );
}