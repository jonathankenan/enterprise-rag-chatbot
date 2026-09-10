"use client";
// Panel chat. Sidebar, auth guard, dan riwayat milik (app)/layout.jsx —
// halaman ini murni isi panel kanan. Percakapan aktif ditentukan lewat "?id=".

import { useState, useEffect, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "../../../lib/api";
import { useShell } from "../../components/ShellContext";
import { useDialog } from "../../components/Dialog";
import Composer from "../../components/Composer";

const MODELS = [
  { value: "on-prem", label: "On-Premise (Ollama)" },
  { value: "groq", label: "GPT-OSS 120B (Groq)" },
  { value: "gemini", label: "Gemini Flash (Google)" },
  { value: "mistral", label: "Mistral Small" },
  { value: "cloudflare", label: "Llama 3.3 70B (Cloudflare)" },
];

function ChatPanel() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const chatId = searchParams.get("id");
  const { refreshHistory, refreshTickets } = useShell();
  const dialog = useDialog();

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [llmProvider, setLlmProvider] = useState("on-prem");
  const [expandedSource, setExpandedSource] = useState(null); // "${messageIndex}-${sourceIndex}" citation yang sedang dibuka -- lihat blok Referensi di bawah
  const [loginInfo, setLoginInfo] = useState(null); // SRS ISR-001.g
  const fileRef = useRef(null);
  const bottomRef = useRef(null);

  // Tanpa ?id=, pakai percakapan terbaru; kalau memang belum ada, buatkan.
  useEffect(() => {
    if (chatId) return;
    (async () => {
      const history = await api.getChatHistory(false);
      if (history.length > 0) {
        router.replace(`/chat?id=${history[0].id}`);
      } else {
        const chat = await api.createChat("Percakapan Baru");
        await refreshHistory();
        router.replace(`/chat?id=${chat.id}`);
      }
    })().catch((err) => console.error("Gagal menyiapkan percakapan:", err));
  }, [chatId]);

  useEffect(() => {
    if (!chatId) return;
    setMessages([]);
    api.getMessages(chatId)
      .then(setMessages)
      .catch((err) => console.error("Gagal memuat pesan:", err));
  }, [chatId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, loading]);

  useEffect(() => {
    const raw = sessionStorage.getItem("login_info");
    if (!raw) return;
    sessionStorage.removeItem("login_info");
    try { setLoginInfo(JSON.parse(raw)); } catch { /* abaikan kalau rusak */ }
  }, []);

  async function handleSend(e) {
    e.preventDefault();
    if (!input.trim() || !chatId) return;

    const content = input;
    setMessages((prev) => [...prev, { sender: "user", content }]);
    setInput("");
    setLoading(true);

    try {
      const result = await api.sendMessage(chatId, content, llmProvider);
      if (result.new_title) refreshHistory();
      setMessages((prev) => [
        ...prev,
        {
          sender: "assistant",
          content: result.reply,
          llm_used: result.llm_used,
          confidence_score: result.confidence_score,
          pii_detected: result.pii_detected,
          message_id: result.message_id,
          escalation_status: result.escalation_offered ? "offered" : null,
          sources: result.sources, // SRS poin 12.a
        },
      ]);
    } catch (err) {
      setMessages((prev) => [...prev, { sender: "assistant", content: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  }

  async function handleEscalate(messageId) {
    setMessages((prev) => prev.map((m) => (m.message_id === messageId ? { ...m, escalation_status: "creating" } : m)));
    try {
      await api.escalateMessage(chatId, messageId);
      refreshTickets();
      // Ke /helpdesk/chat (sisi USER), bukan /helpdesk/tickets/... yang
      // merupakan tampilan ADMIN untuk menangani antrean.
      router.push("/helpdesk/chat");
    } catch (err) {
      setMessages((prev) => prev.map((m) => (m.message_id === messageId ? { ...m, escalation_status: "offered" } : m)));
      dialog.alert(err.message || "Gagal membuat tiket eskalasi");
    }
  }

  function handleDismissEscalation(messageId) {
    setMessages((prev) => prev.map((m) => (m.message_id === messageId ? { ...m, escalation_status: "dismissed" } : m)));
  }

  async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    try {
      const result = await api.uploadDocument(file, chatId);
      setMessages((prev) => [...prev, { sender: "assistant", content: `Dokumen "${result.filename}" berhasil diunggah dan diindeks (${result.chunks_indexed} potongan teks).` }]);
    } catch (err) {
      setMessages((prev) => [...prev, { sender: "assistant", content: `Gagal mengunggah dokumen: ${err.message}` }]);
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
      dialog.alert("Gagal mengekspor PDF: " + err.message);
    } finally {
      setExportingPdf(false);
    }
  }

  const composer = (
    <Composer
      value={input}
      onChange={setInput}
      onSubmit={handleSend}
      disabled={loading}
      placeholder={uploading ? "Mengunggah dokumen..." : "Ketik pertanyaan..."}
      plusMenu={[
        { label: "Unggah dokumen PDF", onSelect: () => fileRef.current?.click() },
        // Export sengaja ikut di menu "+" (bukan tombol terpisah di header):
        // keduanya sama-sama urusan berkas untuk percakapan ini.
        ...(messages.length > 0
          ? [{ label: exportingPdf ? "Mengekspor..." : "Export percakapan ke PDF", onSelect: handleExportPdf }]
          : []),
      ]}
      models={MODELS}
      model={llmProvider}
      onModelChange={setLlmProvider}
    />
  );

  const isEmpty = messages.length === 0 && !loading;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "20px 32px 24px" }}>
      <input ref={fileRef} type="file" accept=".pdf" style={{ display: "none" }} onChange={handleFileUpload} disabled={uploading} />

      {loginInfo && (
        <div style={{
          padding: "8px 12px", marginBottom: 12, borderRadius: 6, fontSize: 13,
          background: loginInfo.failed_attempts_since_last_login > 0 ? "var(--idx-warning-tint)" : "var(--idx-info-tint)",
          border: `1px solid ${loginInfo.failed_attempts_since_last_login > 0 ? "var(--idx-warning-border)" : "var(--idx-info-border)"}`,
          display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0,
        }}>
          <span>
            {loginInfo.previous_login_at
              ? `Login sebelumnya: ${new Date(loginInfo.previous_login_at.endsWith("Z") ? loginInfo.previous_login_at : loginInfo.previous_login_at + "Z").toLocaleString()}`
              : "Ini adalah login pertama Anda."}
            {loginInfo.failed_attempts_since_last_login > 0 && (
              <> — <b>{loginInfo.failed_attempts_since_last_login} percobaan login gagal</b> tercatat sejak saat itu.</>
            )}
          </span>
          <button onClick={() => setLoginInfo(null)} style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: 14, color: "var(--idx-text-muted)" }}>✕</button>
        </div>
      )}

      {isEmpty ? (
        /* Keadaan kosong: sapaan + composer di TENGAH layar (pola Gemini).
           Begitu ada pesan pertama, layout berpindah ke mode percakapan —
           key="empty"/"chat" bikin React me-mount ulang supaya animasinya jalan. */
        <div key="empty" className="page-enter empty-glow" style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 28 }}>
          <h1 style={{ fontSize: 30, margin: 0, border: "none", padding: 0, textAlign: "center" }}>
            Apa yang bisa saya bantu?
          </h1>
          <div style={{ width: "100%", maxWidth: 720 }}>{composer}</div>
        </div>
      ) : (
        <div key="chat" className="page-enter" style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, maxWidth: 820, width: "100%", margin: "0 auto" }}>
          <div style={{ flex: 1, overflowY: "auto", minHeight: 0, paddingRight: 4, marginBottom: 16 }}>
            {messages.map((m, i) => (
              <div key={i} className="collapse-enter" style={{ marginBottom: 14, textAlign: m.sender === "user" ? "right" : "left" }}>
                <div style={{
                  display: "inline-block", padding: "10px 14px", borderRadius: 12,
                  background: m.sender === "user" ? "var(--idx-red-tint)" : "var(--idx-surface-alt)",
                  maxWidth: "82%", textAlign: "left", whiteSpace: "pre-wrap",
                }}>
                  {m.content}
                </div>
                {m.llm_used && (
                  <div style={{ fontSize: 11, color: "var(--idx-text-subtle)", marginTop: 3 }}>
                    sumber: {m.llm_used}
                    {m.confidence_score !== undefined && m.confidence_score !== null && (
                      <span style={{ marginLeft: 8, fontWeight: 700, color: m.confidence_score >= 80 ? "var(--idx-success)" : m.confidence_score >= 50 ? "var(--idx-warning)" : "var(--idx-danger)" }}>
                        • keyakinan: {m.confidence_score}%
                      </span>
                    )}
                  </div>
                )}
                {m.sources && m.sources.length > 0 && (() => {
                  const expandedIdx = expandedSource && expandedSource.startsWith(`${i}-`)
                    ? Number(expandedSource.slice(String(i).length + 1))
                    : null;
                  const expandedObj = expandedIdx !== null ? m.sources[expandedIdx] : null;
                  return (
                    <>
                      <div style={{ fontSize: 11, color: "var(--idx-text-body)", marginTop: 2 }}>
                        Referensi:{" "}
                        {m.sources.map((s, si) => {
                          const hasChunks = s.chunks && s.chunks.length > 0;
                          const key = `${i}-${si}`;
                          return (
                            <span key={si}>
                              {si > 0 && ", "}
                              <button
                                type="button"
                                onClick={() => hasChunks && setExpandedSource(expandedSource === key ? null : key)}
                                disabled={!hasChunks}
                                title={hasChunks ? "Lihat isi yang dikutip" : undefined}
                                style={{
                                  background: "none", border: "none", padding: 0, font: "inherit",
                                  color: hasChunks ? "var(--idx-red)" : "inherit",
                                  cursor: hasChunks ? "pointer" : "default",
                                  textDecoration: hasChunks ? "underline" : "none",
                                }}
                              >
                                {s.label}
                              </button>
                            </span>
                          );
                        })}
                      </div>
                      {expandedObj && (
                        <div style={{
                          marginTop: 6, padding: "10px 12px", maxWidth: "82%",
                          background: "var(--idx-surface-alt)", border: "1px solid var(--idx-border)",
                          borderRadius: 8, fontSize: 12.5,
                        }}>
                          {/* Isi apa adanya yang sudah dikirim retrieve_context() -- sudah lolos filter divisi,
                              tidak ada endpoint/permintaan baru di sini, cuma menampilkan yang sudah ada di respons. */}
                          {expandedObj.chunks.map((c, ci) => (
                            <div key={ci} style={{ marginBottom: ci < expandedObj.chunks.length - 1 ? 10 : 0 }}>
                              {c.page !== null && c.page !== undefined && (
                                <div style={{ fontWeight: 700, fontSize: 11, color: "var(--idx-text-subtle)", marginBottom: 3 }}>
                                  Hal. {c.page}
                                </div>
                              )}
                              <div style={{ whiteSpace: "pre-wrap", color: "var(--idx-text-body)" }}>{c.text}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  );
                })()}
                {m.pii_detected && (
                  <div style={{ fontSize: 11, color: "var(--idx-warning)", marginTop: 2, fontWeight: 500 }}>
                    Data pribadi terdeteksi pada pesan ini — disamarkan otomatis sebelum diproses AI.
                  </div>
                )}
                {m.escalation_status && m.escalation_status !== "dismissed" && (
                  <div style={{ fontSize: 12, color: "var(--idx-info-text)", marginTop: 6, padding: 10, background: "var(--idx-info-tint)", border: "1px solid var(--idx-info-border)", borderRadius: 8, maxWidth: "82%" }}>
                    <div style={{ marginBottom: 8 }}>Jawaban ini kurang meyakinkan. Ingin eskalasi ke tim helpdesk?</div>
                    <button
                      disabled={m.escalation_status === "creating"}
                      onClick={() => handleEscalate(m.message_id)}
                      style={{ marginRight: 8, padding: "5px 12px", fontSize: 12 }}
                    >
                      {m.escalation_status === "creating" ? "Membuat tiket..." : "Ya, eskalasi"}
                    </button>
                    <button
                      disabled={m.escalation_status === "creating"}
                      onClick={() => handleDismissEscalation(m.message_id)}
                      style={{ padding: "5px 12px", fontSize: 12, background: "transparent", color: "var(--idx-text-body)", border: "1px solid var(--idx-border-strong)", borderRadius: 4 }}
                    >
                      Tidak, terima kasih
                    </button>
                  </div>
                )}
              </div>
            ))}
            {loading && <p style={{ color: "var(--idx-text-subtle)", fontSize: 13 }}>Sedang memproses...</p>}
            <div ref={bottomRef} />
          </div>

          <div style={{ flexShrink: 0 }}>{composer}</div>
        </div>
      )}
    </div>
  );
}

export default function ChatPage() {
  // useSearchParams() wajib di bawah Suspense (syarat Next.js App Router)
  return (
    <Suspense fallback={<div style={{ padding: 32, color: "var(--idx-text-subtle)" }}>Memuat...</div>}>
      <ChatPanel />
    </Suspense>
  );
}
