"use client";
// [PENANGGUNG JAWAB: Anggota B]
// TODO: tambahkan sidebar riwayat chat (panggil api.getChatHistory())

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "../../lib/api";

export default function ChatPage() {
  const router = useRouter();
  const [chatId, setChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);

  useEffect(() => {
    // Proteksi halaman: kalau belum login, tendang ke halaman login
    if (!api.isLoggedIn()) {
      router.push("/login");
      return;
    }

    // Ambil info user yang sedang login
    api.getMe()
      .then((user) => setCurrentUser(user))
      .catch(() => {
        // Token invalid/expired -> paksa logout
        api.logout();
        router.push("/login");
      });

    // Buat satu chat baru saat halaman dibuka (versi sederhana untuk F1)
    api.createChat("Percakapan Baru").then((chat) => setChatId(chat.id));
  }, []);

  function handleLogout() {
    api.logout();
    router.push("/login");
  }

  async function handleSend(e) {
    e.preventDefault();
    if (!input.trim() || !chatId) return;

    const userMessage = { sender: "user", content: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    try {
      const result = await api.sendMessage(chatId, userMessage.content);
      setMessages((prev) => [
        ...prev,
        {
          sender: "assistant",
          content: result.reply,
          llm_used: result.llm_used, // "on-prem" atau "commercial" — tampilkan sebagai label kecil
        },
      ]);
    } catch (err) {
      setMessages((prev) => [...prev, { sender: "assistant", content: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 700, margin: "40px auto", padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 style={{ margin: 0 }}>Generic ChatBot AI</h1>
          {currentUser && (
            <p style={{ margin: "4px 0 0", fontSize: 13, color: "#666" }}>
              Masuk sebagai: {currentUser.full_name || currentUser.email}
            </p>
          )}
        </div>
        <button onClick={handleLogout} style={{ padding: "8px 16px", height: "fit-content" }}>
          Keluar
        </button>
      </div>

      <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, minHeight: 400, marginTop: 16 }}>
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 12, textAlign: m.sender === "user" ? "right" : "left" }}>
            <div
              style={{
                display: "inline-block",
                padding: "8px 12px",
                borderRadius: 8,
                background: m.sender === "user" ? "#DCF0FF" : "#F1F1F1",
                maxWidth: "80%",
              }}
            >
              {m.content}
            </div>
            {m.llm_used && (
              <div style={{ fontSize: 11, color: "#888", marginTop: 2 }}>
                sumber: {m.llm_used}
              </div>
            )}
          </div>
        ))}
        {loading && <p style={{ color: "#888" }}>Sedang memproses...</p>}
      </div>

      <form onSubmit={handleSend} style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ketik pertanyaan..."
          style={{ flex: 1, padding: 10 }}
        />
        <button type="submit" disabled={loading}>
          Kirim
        </button>
      </form>
    </div>
  );
}