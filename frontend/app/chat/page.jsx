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
          escalated: result.escalated,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [...prev, { sender: "assistant", content: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
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
                <div style={{ fontWeight: "bold", fontSize: "14px", flex: 1, paddingRight: "8px" }}>{chat.title}</div>
                <button
                  onClick={(e) => handleDeleteChat(e, chat.id)}
                  style={{
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                    color: "#d32f2f",
                    padding: "0 4px",
                    fontSize: "14px",
                    lineHeight: "1"
                  }}
                  title="Hapus percakapan"
                >
                  ✕
                </button>
              </div>
              <div style={{ fontSize: "11px", color: "#888", marginTop: "4px" }}>
                {new Date(chat.created_at.endsWith("Z") ? chat.created_at : chat.created_at + "Z").toLocaleString()}
              </div>
            </div>
          ))}
        </div>

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
              {m.escalated && (
                <div style={{ fontSize: 11, color: "#0070f3", marginTop: 2, fontWeight: 500 }}>
                  🎫 Jawaban ini kurang meyakinkan — pertanyaan Anda otomatis dieskalasi ke tim helpdesk.
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