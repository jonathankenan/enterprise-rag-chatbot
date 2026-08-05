"use client";
// [PENANGGUNG JAWAB: Anggota B]

import { useState, useEffect } from "react";
import { api } from "../../lib/api";

export default function ChatPage() {
  const [chatId, setChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [chatHistory, setChatHistory] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Load chat history on mount
  useEffect(() => {
    loadChatHistory();
  }, []);

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
      const result = await api.sendMessage(chatId, userMessage.content);
      
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
      const result = await api.uploadDocument(file);
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
      e.target.value = null; // reset input
    }
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
                {new Date(chat.created_at).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* MAIN CHAT AREA */}
      <div style={{ flex: 1, padding: "20px 40px", display: "flex", flexDirection: "column", maxWidth: "900px", margin: "0 auto" }}>
        <h1>Generic ChatBot AI</h1>

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
                      • Yakin: {m.confidence_score}%
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
          {loading && <p style={{ color: "#888" }}>Sedang memproses...</p>}
        </div>

        <form onSubmit={handleSend} style={{ display: "flex", gap: 8 }}>
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
