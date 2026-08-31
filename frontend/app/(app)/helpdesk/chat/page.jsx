"use client";
// "Hubungi Admin" — RUANG PERCAKAPAN user dengan admin, bukan sekadar form.
//
// User tetap di halaman ini sepanjang percakapan: sebelum ada tiket tampil
// layar tulis pesan, dan begitu pesan pertama terkirim halaman langsung
// berubah jadi chat di tempat (tanpa pindah URL ke /helpdesk/tickets/...).
// Halaman tiket itu adalah sisi ADMIN — pihak yang dihubungi melihat dan
// membalas dari sana.
//
// Tiket sengaja baru dibuat saat pesan pertama dikirim, supaya sekadar
// membuka menu ini tidak memunculkan tiket kosong di antrean admin.

import { useState, useEffect, useRef } from "react";
import { api } from "../../../../lib/api";
import { useShell } from "../../../components/ShellContext";
import { useDialog } from "../../../components/Dialog";
import Composer from "../../../components/Composer";

export default function HubungiAdminPage() {
  const { chatHistory, refreshTickets } = useShell();
  const dialog = useDialog();

  const [ticket, setTicket] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [attached, setAttached] = useState(null); // { id, title }
  const [picking, setPicking] = useState(false);
  const [checking, setChecking] = useState(true);
  const [wsStatus, setWsStatus] = useState("connecting");
  const [error, setError] = useState("");
  const [closedNotice, setClosedNotice] = useState(false);
  const wsRef = useRef(null);
  const bottomRef = useRef(null);

  // getMyOpenTicket() -- BUKAN listTickets(). Untuk IT Admin divisi,
  // listTickets berisi ANTREAN divisinya, bukan percakapannya sendiri
  // dengan admin global.
  useEffect(() => {
    let cancelled = false;
    api.getMyOpenTicket()
      .then((t) => {
        if (cancelled) return;
        if (t) {
          setTicket(t);
          setMessages(t.ticket_messages);
        }
        setChecking(false);
      })
      .catch(() => { if (!cancelled) setChecking(false); });
    return () => { cancelled = true; };
  }, []);

  // Tiket ditutup admin -> kembalikan ke layar awal + pemberitahuan. Sebelumnya
  // halaman berhenti di pesan "Tiket ini sudah ditutup" tanpa jalan keluar:
  // user tidak bisa membalas, dan juga tidak bisa memulai percakapan baru.
  function resetToFresh() {
    wsRef.current?.close();
    setTicket(null);
    setMessages([]);
    setInput("");
    setAttached(null);
    setError("");
    setClosedNotice(true);
  }

  // WebSocket baru dibuka setelah tiket ada (yaitu setelah pesan pertama).
  useEffect(() => {
    if (ticket?.status === "closed") { resetToFresh(); return; }
    if (!ticket) return;
    const ws = new WebSocket(api.ticketSocketUrl(ticket.id));
    wsRef.current = ws;
    setWsStatus("connecting");
    ws.onopen = () => setWsStatus("open");
    ws.onclose = () => setWsStatus("closed");
    ws.onerror = () => setWsStatus("closed");
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.error) {
        // Backend menolak pesan karena tiket keburu ditutup admin.
        if (data.error.toLowerCase().includes("ditutup")) resetToFresh();
        else setError(data.error);
        return;
      }
      setMessages((prev) => [...prev, data]);
    };
    return () => ws.close();
  }, [ticket?.id, ticket?.status]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!input.trim() || sending) return;

    // Sudah ada tiket -> kirim lewat WebSocket seperti chat biasa.
    if (ticket && wsRef.current && wsStatus === "open") {
      wsRef.current.send(JSON.stringify({ content: input, attached_chat_id: attached?.id || null }));
      setInput("");
      setAttached(null);
      return;
    }

    // Belum ada tiket -> pesan pertama sekaligus membuat tiketnya.
    setSending(true);
    try {
      const created = await api.createTicketWithMessage(input.trim(), attached?.id || null);
      setTicket(created);
      setMessages(created.ticket_messages);
      setInput("");
      setAttached(null);
      refreshTickets();
    } catch (err) {
      dialog.alert(err.message || "Gagal mengirim pesan ke admin");
    } finally {
      setSending(false);
    }
  }

  const composer = (
    <Composer
      value={input}
      onChange={setInput}
      onSubmit={handleSubmit}
      disabled={sending || (ticket && wsStatus !== "open")}
      placeholder={sending ? "Mengirim..." : "Tulis pesan untuk admin..."}
      plusMenu={[{ label: "Cantumkan percakapan", onSelect: () => setPicking(true) }]}
      attachment={attached ? `Percakapan: ${attached.title}` : null}
      onClearAttachment={() => setAttached(null)}
    />
  );

  if (checking) {
    return <div style={{ padding: 32, color: "var(--idx-text-subtle)" }}>Memuat...</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "20px 32px 24px", maxWidth: 820, margin: "0 auto", width: "100%" }}>
      {!ticket ? (
        /* Belum ada tiket: sapaan + composer di tengah */
        <div key="empty" className="page-enter empty-glow" style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
          <div style={{ textAlign: "center" }}>
            <h1 style={{ fontSize: 28, margin: 0, border: "none", padding: 0 }}>Hubungi Admin</h1>
            <p style={{ color: "var(--idx-text-muted)", fontSize: 13.5, marginTop: 10, maxWidth: 520 }}>
              Tulis pertanyaan Anda untuk tim helpdesk. Tiket baru dibuat setelah pesan ini terkirim.
              Gunakan tombol <b>+</b> untuk mencantumkan percakapan AI sebagai konteks.
            </p>
          </div>
          <div style={{ width: "100%", maxWidth: 720 }}>{composer}</div>
          {closedNotice && (
            <p style={{
              margin: 0, fontSize: 13, color: "var(--idx-text-muted)", textAlign: "center",
              background: "var(--idx-surface-alt)", padding: "10px 16px", borderRadius: 8,
            }}>
              Tiket terakhir Anda sudah ditutup admin. Kirim pesan di atas untuk memulai percakapan baru.
            </p>
          )}
        </div>
      ) : (
        <div key="chat" className="page-enter" style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ flexShrink: 0, marginBottom: 12 }}>
            <h1 style={{ margin: 0, fontSize: 21 }}>Hubungi Admin</h1>
            <p style={{ fontSize: 12.5, color: "var(--idx-text-muted)", margin: "10px 0 0" }}>
              Ditangani oleh <b>{ticket.target_divisi ? `IT Admin ${ticket.target_divisi}` : "IT Admin Global"}</b> ·
              Status: <b>Terbuka</b>
              {" · koneksi: "}
              <span style={{ color: wsStatus === "open" ? "var(--idx-success)" : "var(--idx-warning)" }}>
                {wsStatus === "open" ? "tersambung" : wsStatus === "connecting" ? "menyambungkan..." : "terputus"}
              </span>
            </p>
            {error && <p style={{ color: "var(--idx-danger)", fontSize: 13 }}>{error}</p>}
          </div>

          <div style={{ flex: 1, overflowY: "auto", minHeight: 0, border: "1px solid var(--idx-border)", borderRadius: 8, padding: 16, background: "var(--idx-bg)", marginBottom: 14 }}>
            {messages.length === 0 && (
              <p style={{ color: "var(--idx-text-subtle)", fontSize: 13, textAlign: "center" }}>
                Tim helpdesk akan segera membalas.
              </p>
            )}
            {messages.map((m) => (
              <div key={m.id} className="collapse-enter" style={{ marginBottom: 12, textAlign: m.sender_role === "admin" ? "left" : "right" }}>
                <div style={{
                  display: "inline-block", padding: "10px 14px", borderRadius: 12, maxWidth: "82%", textAlign: "left",
                  background: m.sender_role === "admin" ? "var(--idx-warning-tint)" : "var(--idx-red-tint)",
                }}>
                  <div style={{ fontSize: 10, color: "var(--idx-text-subtle)", marginBottom: 3, fontWeight: 700 }}>
                    {m.sender_role === "admin" ? "Admin Helpdesk" : "Anda"}
                  </div>
                  <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
                  {m.attached_chat_title && (
                    <div style={{ marginTop: 8, fontSize: 12, color: "var(--idx-red)" }}>
                      Percakapan dilampirkan: {m.attached_chat_title}
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>

          <div style={{ flexShrink: 0 }}>{composer}</div>
        </div>
      )}

      {picking && (
        <div
          onClick={() => setPicking(false)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 60 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="page-enter"
            style={{ width: 460, maxHeight: "70vh", overflowY: "auto", background: "var(--idx-bg)", borderRadius: 10, padding: 20, boxShadow: "0 10px 40px rgba(0,0,0,0.2)" }}
          >
            <b style={{ color: "var(--idx-text)" }}>Cantumkan percakapan</b>
            <p style={{ fontSize: 12.5, color: "var(--idx-text-muted)", margin: "6px 0 14px" }}>
              Admin hanya bisa membaca percakapan yang Anda cantumkan di sini.
            </p>
            {chatHistory.length === 0 && (
              <p style={{ fontSize: 13, color: "var(--idx-text-subtle)" }}>Belum ada percakapan.</p>
            )}
            {chatHistory.map((c) => (
              <button
                key={c.id}
                className="popup-item"
                onClick={() => { setAttached({ id: c.id, title: c.title }); setPicking(false); }}
                style={{ width: "100%", marginBottom: 2 }}
              >
                {c.title}
              </button>
            ))}
            <button
              onClick={() => setPicking(false)}
              style={{ marginTop: 12, background: "transparent", color: "var(--idx-text-body)", border: "1px solid var(--idx-border-strong)" }}
            >
              Batal
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
