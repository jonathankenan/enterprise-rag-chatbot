"use client";
// Chat real-time user<->admin untuk satu tiket helpdesk (SRS poin 7).
//
// REST (api.getTicket) dipakai sekali di awal untuk histori; WebSocket
// SETELAHNYA cuma untuk pesan baru — bukan dua sumber data yang tumpang tindih.
//
// Konteks percakapan AI TIDAK lagi ditempel otomatis di atas: user memilih
// sendiri percakapan mana yang dicantumkan (tombol + di composer), dan admin
// membukanya lewat chip lampiran pada pesan tersebut.

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { api } from "../../../../../lib/api";
import { useShell } from "../../../../components/ShellContext";
import { useDialog } from "../../../../components/Dialog";
import Composer from "../../../../components/Composer";

export default function TicketChatPage({ params }) {
  const { id: ticketId } = params;
  const router = useRouter();
  const { currentUser, chatHistory } = useShell();
  const dialog = useDialog();

  const [ticket, setTicket] = useState(null);
  const [ticketMessages, setTicketMessages] = useState([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [wsStatus, setWsStatus] = useState("connecting"); // connecting | open | closed
  const [attached, setAttached] = useState(null);         // { id, title }
  const [picking, setPicking] = useState(false);
  const [viewingChat, setViewingChat] = useState(null);   // { title, messages }
  const wsRef = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    api.getTicket(ticketId)
      .then((detail) => {
        if (cancelled) return;
        setTicket(detail);
        setTicketMessages(detail.ticket_messages);
      })
      .catch((err) => setError(err.message || "Gagal memuat tiket"));
    return () => { cancelled = true; };
  }, [ticketId]);

  // WebSocket dibuka SETELAH detail tiket dimuat — kalau tiket sudah closed,
  // tidak perlu buka koneksi live sama sekali.
  useEffect(() => {
    if (!ticket || ticket.status === "closed") return;
    const ws = new WebSocket(api.ticketSocketUrl(ticketId));
    wsRef.current = ws;
    setWsStatus("connecting");
    ws.onopen = () => setWsStatus("open");
    ws.onclose = () => setWsStatus("closed");
    ws.onerror = () => setWsStatus("closed");
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.error) { setError(data.error); return; }
      setTicketMessages((prev) => [...prev, data]);
    };
    return () => ws.close();
  }, [ticket?.id, ticket?.status]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [ticketMessages]);

  function handleSend(e) {
    e.preventDefault();
    if (!input.trim() || wsStatus !== "open") return;
    wsRef.current.send(JSON.stringify({ content: input, attached_chat_id: attached?.id || null }));
    setInput("");
    setAttached(null);
  }

  async function handleClose() {
    try {
      const updated = await api.closeTicket(ticketId);
      setTicket((prev) => ({ ...prev, status: updated.status }));
    } catch (err) {
      setError(err.message || "Gagal menutup tiket");
    }
  }

  async function handleDelete() {
    const ok = await dialog.confirm(
      "Hapus tiket ini beserta seluruh pesannya? Tindakan ini tidak bisa dibatalkan.",
      { title: "Hapus Tiket", confirmLabel: "Hapus", danger: true }
    );
    if (!ok) return;
    try {
      await api.deleteTicket(ticketId);
      router.push("/helpdesk/tickets");
    } catch (err) {
      setError(err.message || "Gagal menghapus tiket");
    }
  }

  async function openAttachedChat(chatId, title) {
    try {
      const messages = await api.getAttachedChat(ticketId, chatId);
      setViewingChat({ title, messages });
    } catch (err) {
      setError(err.message || "Gagal membuka percakapan yang dilampirkan");
    }
  }

  if (!ticket) return <div style={{ padding: 40 }}>{error || "Memuat..."}</div>;

  const isAdmin = currentUser?.role === "it_admin";
  // Yang boleh menutup/menghapus adalah pihak YANG DIHUBUNGI: admin divisi X
  // untuk tiket target_divisi="X", admin global untuk target_divisi=null.
  const isHandler = isAdmin && (currentUser?.divisi ?? null) === (ticket.target_divisi ?? null);
  // Yang boleh melampirkan percakapan adalah PEMILIK tiket, bukan "bukan admin":
  // admin divisi yang sedang menghubungi admin global juga pemilik tiket.
  const isOwner = currentUser?.id === ticket.user_id;
  const isClosed = ticket.status === "closed";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "20px 32px 24px", maxWidth: 820, margin: "0 auto", width: "100%" }}>
      <div style={{ flexShrink: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
          <h1 style={{ margin: 0, fontSize: 21 }}>Tiket Helpdesk</h1>
          <div style={{ display: "flex", gap: 8 }}>
            {isHandler && !isClosed && (
              <button onClick={handleClose} style={{ padding: "6px 14px", fontSize: 12.5 }}>Tutup Tiket</button>
            )}
            {isHandler && isClosed && (
              <button
                onClick={handleDelete}
                style={{ padding: "6px 14px", fontSize: 12.5, background: "transparent", color: "var(--idx-danger)", border: "1px solid var(--idx-danger-border)", borderRadius: 4 }}
              >
                Hapus Tiket
              </button>
            )}
          </div>
        </div>

        <p style={{ fontSize: 12.5, color: "var(--idx-text-muted)", margin: "10px 0 14px" }}>
          {isAdmin && <>Dari: {ticket.user_email} · </>}
          {ticket.confidence_score !== null && ticket.confidence_score !== undefined && (
            <>Confidence jawaban: <b style={{ color: "var(--idx-danger)" }}>{ticket.confidence_score}%</b> · </>
          )}
          Status: <b>{isClosed ? "Ditutup" : "Terbuka"}</b>
          {!isClosed && (
            <> · koneksi: <span style={{ color: wsStatus === "open" ? "var(--idx-success)" : "var(--idx-warning)" }}>
              {wsStatus === "open" ? "tersambung" : wsStatus === "connecting" ? "menyambungkan..." : "terputus"}
            </span></>
          )}
        </p>

        {error && <p style={{ color: "var(--idx-danger)", fontSize: 13 }}>{error}</p>}
      </div>

      <div style={{ flex: 1, overflowY: "auto", minHeight: 0, border: "1px solid var(--idx-border)", borderRadius: 8, padding: 16, background: "var(--idx-bg)", marginBottom: 14 }}>
        {ticketMessages.length === 0 && (
          <p style={{ color: "var(--idx-text-subtle)", fontSize: 13, textAlign: "center" }}>
            Belum ada pesan. {isAdmin ? "Balas pertanyaan user di bawah." : "Tim helpdesk akan segera membalas."}
          </p>
        )}
        {ticketMessages.map((m) => (
          <div key={m.id} className="collapse-enter" style={{ marginBottom: 12, textAlign: m.sender_role === "admin" ? "left" : "right" }}>
            <div style={{
              display: "inline-block", padding: "10px 14px", borderRadius: 12, maxWidth: "82%", textAlign: "left",
              background: m.sender_role === "admin" ? "var(--idx-warning-tint)" : "var(--idx-red-tint)",
            }}>
              <div style={{ fontSize: 10, color: "var(--idx-text-subtle)", marginBottom: 3, fontWeight: 700 }}>
                {m.sender_role === "admin" ? "Admin Helpdesk" : isAdmin ? "User" : "Anda"}
              </div>
              <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
              {m.attached_chat_id && (
                <button
                  onClick={() => openAttachedChat(m.attached_chat_id, m.attached_chat_title)}
                  style={{
                    marginTop: 8, padding: "5px 10px", fontSize: 12, borderRadius: 999,
                    background: "var(--idx-bg)", color: "var(--idx-red)",
                    border: "1px solid var(--idx-danger-border)", cursor: "pointer",
                  }}
                >
                  Percakapan: {m.attached_chat_title} — lihat
                </button>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div style={{ flexShrink: 0 }}>
        {isClosed ? (
          <p style={{ textAlign: "center", color: "var(--idx-text-muted)", fontSize: 13 }}>Tiket ini sudah ditutup.</p>
        ) : (
          <Composer
            value={input}
            onChange={setInput}
            onSubmit={handleSend}
            disabled={wsStatus !== "open"}
            placeholder={wsStatus === "open" ? "Ketik pesan..." : "Menyambungkan..."}
            plusMenu={isOwner ? [{ label: "Cantumkan percakapan", onSelect: () => setPicking(true) }] : []}
            attachment={attached ? `Percakapan: ${attached.title}` : null}
            onClearAttachment={() => setAttached(null)}
          />
        )}
      </div>

      {picking && (
        <div onClick={() => setPicking(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 60 }}>
          <div onClick={(e) => e.stopPropagation()} className="page-enter" style={{ width: 460, maxHeight: "70vh", overflowY: "auto", background: "var(--idx-bg)", borderRadius: 10, padding: 20, boxShadow: "0 10px 40px rgba(0,0,0,0.2)" }}>
            <b style={{ color: "var(--idx-text)" }}>Cantumkan percakapan</b>
            <p style={{ fontSize: 12.5, color: "var(--idx-text-muted)", margin: "6px 0 14px" }}>
              Admin hanya bisa membaca percakapan yang Anda cantumkan.
            </p>
            {chatHistory.length === 0 && <p style={{ fontSize: 13, color: "var(--idx-text-subtle)" }}>Belum ada percakapan.</p>}
            {chatHistory.map((c) => (
              <button key={c.id} className="popup-item" style={{ width: "100%", marginBottom: 2 }}
                onClick={() => { setAttached({ id: c.id, title: c.title }); setPicking(false); }}>
                {c.title}
              </button>
            ))}
            <button onClick={() => setPicking(false)} style={{ marginTop: 12, background: "transparent", color: "var(--idx-text-body)", border: "1px solid var(--idx-border-strong)" }}>Batal</button>
          </div>
        </div>
      )}

      {viewingChat && (
        <div onClick={() => setViewingChat(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 60 }}>
          <div onClick={(e) => e.stopPropagation()} className="page-enter" style={{ width: 620, maxHeight: "76vh", display: "flex", flexDirection: "column", background: "var(--idx-bg)", borderRadius: 10, padding: 20, boxShadow: "0 10px 40px rgba(0,0,0,0.2)" }}>
            <b style={{ color: "var(--idx-text)", marginBottom: 12 }}>{viewingChat.title}</b>
            <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
              {viewingChat.messages.map((m) => (
                <div key={m.id} style={{ marginBottom: 10, textAlign: m.sender === "user" ? "right" : "left" }}>
                  <div style={{ display: "inline-block", padding: "8px 12px", borderRadius: 10, maxWidth: "82%", textAlign: "left", whiteSpace: "pre-wrap",
                    background: m.sender === "user" ? "var(--idx-red-tint)" : "var(--idx-surface-alt)" }}>
                    {m.content}
                  </div>
                </div>
              ))}
            </div>
            <button onClick={() => setViewingChat(null)} style={{ marginTop: 14, alignSelf: "flex-start" }}>Tutup</button>
          </div>
        </div>
      )}
    </div>
  );
}
