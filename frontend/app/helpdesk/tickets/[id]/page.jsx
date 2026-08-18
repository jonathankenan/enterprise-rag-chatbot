"use client";
// [PENANGGUNG JAWAB: Anggota B]
// Chat real-time user<->admin untuk satu tiket helpdesk — implementasi
// "human helpdesk" SRS FCR-003 poin 7. Bisa diakses PEMILIK tiket (user
// yang mengalami jawaban low-confidence) ATAU IT_ADMIN (backend yang
// menegakkan otorisasi ini, lihat helpdesk/routes.py _get_ticket_or_403).
//
// REST (api.getTicket) dipakai sekali di awal untuk histori lengkap
// (chat AI + percakapan tiket yang sudah ada); WebSocket dipakai SETELAHNYA
// cuma untuk pesan BARU yang masuk real-time — bukan dua sumber data yang
// saling tumpang tindih.

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "../../../../lib/api";

export default function TicketChatPage({ params }) {
  const { id: ticketId } = params;
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [ticket, setTicket] = useState(null);
  const [ticketMessages, setTicketMessages] = useState([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [wsStatus, setWsStatus] = useState("connecting"); // connecting | open | closed
  const wsRef = useRef(null);
  const bottomRef = useRef(null);

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
  }, []);

  useEffect(() => {
    if (!currentUser) return;

    let cancelled = false;
    api.getTicket(ticketId)
      .then((detail) => {
        if (cancelled) return;
        setTicket(detail);
        setTicketMessages(detail.ticket_messages);
      })
      .catch((err) => setError(err.message || "Gagal memuat tiket"));

    return () => { cancelled = true; };
  }, [currentUser, ticketId]);

  // WebSocket dibuka SETELAH detail tiket berhasil dimuat (butuh tahu
  // status tiket dulu — kalau sudah closed, tidak perlu buka koneksi live).
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
      if (data.error) {
        setError(data.error);
        return;
      }
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
    wsRef.current.send(JSON.stringify({ content: input }));
    setInput("");
  }

  async function handleClose() {
    try {
      const updated = await api.closeTicket(ticketId);
      setTicket((prev) => ({ ...prev, status: updated.status }));
    } catch (err) {
      setError(err.message || "Gagal menutup tiket");
    }
  }

  if (checkingSession || !ticket) {
    return <div style={{ padding: 40 }}>{error || "Memuat..."}</div>;
  }

  const isAdmin = currentUser.role === "it_admin";
  const isClosed = ticket.status === "closed";
  const backHref = isAdmin ? "/helpdesk" : "/chat";

  return (
    <div style={{ padding: "20px 40px", maxWidth: 800, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>Tiket Helpdesk — {ticket.chat_title}</h1>
        <Link href={backHref}>← Kembali</Link>
      </div>

      <p style={{ fontSize: 13, color: "#666" }}>
        {isAdmin && <>Dari: {ticket.user_email} · </>}
        Confidence jawaban: <b style={{ color: "#d32f2f" }}>{ticket.confidence_score}%</b> ·
        Status: <b>{isClosed ? "Ditutup" : "Terbuka"}</b>
        {!isClosed && <> · koneksi: <span style={{ color: wsStatus === "open" ? "#2e7d32" : "#ed6c02" }}>{wsStatus === "open" ? "tersambung" : wsStatus === "connecting" ? "menyambungkan..." : "terputus"}</span></>}
      </p>

      {error && <p style={{ color: "#d32f2f" }}>{error}</p>}

      {/* Terbuka default untuk SEMUA pihak (admin & user) — konteks kenapa
          tiket ini dibuka (jawaban AI yang kurang meyakinkan) relevan buat
          keduanya, jangan disembunyikan di balik klik dulu. */}
      <details open style={{ marginBottom: 16, fontSize: 13 }}>
        <summary style={{ cursor: "pointer", color: "#666", fontWeight: 600 }}>Riwayat percakapan AI (konteks awal)</summary>
        <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 16, marginTop: 8, maxHeight: 250, overflowY: "auto" }}>
          {ticket.messages.map((m) => (
            <div key={m.id} style={{ marginBottom: 10, textAlign: m.sender === "user" ? "right" : "left" }}>
              <div style={{ display: "inline-block", padding: "8px 12px", borderRadius: 8, background: m.sender === "user" ? "#DCF0FF" : "#F1F1F1", maxWidth: "80%", textAlign: "left" }}>
                {m.content}
              </div>
            </div>
          ))}
        </div>
      </details>

      <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, minHeight: 300, maxHeight: 450, overflowY: "auto", background: "white" }}>
        {ticketMessages.length === 0 && (
          <p style={{ color: "#888", fontSize: 13, textAlign: "center" }}>
            Belum ada pesan. {isAdmin ? "Balas pertanyaan user di bawah." : "Tim helpdesk akan segera membalas."}
          </p>
        )}
        {ticketMessages.map((m) => (
          <div key={m.id} style={{ marginBottom: 10, textAlign: m.sender_role === "admin" ? "left" : "right" }}>
            <div style={{ display: "inline-block", padding: "8px 12px", borderRadius: 8, background: m.sender_role === "admin" ? "#FEF3C7" : "#DCF0FF", maxWidth: "80%", textAlign: "left" }}>
              <div style={{ fontSize: 10, color: "#888", marginBottom: 2, fontWeight: 600 }}>
                {m.sender_role === "admin" ? "Admin Helpdesk" : "Anda"}
              </div>
              {m.content}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {isClosed ? (
        <p style={{ textAlign: "center", color: "#666", marginTop: 12 }}>Tiket ini sudah ditutup.</p>
      ) : (
        <form onSubmit={handleSend} style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ketik pesan..."
            disabled={wsStatus !== "open"}
            style={{ flex: 1, padding: 10 }}
          />
          <button type="submit" disabled={wsStatus !== "open"} style={{ padding: "10px 20px" }}>Kirim</button>
        </form>
      )}

      {isAdmin && !isClosed && (
        <button onClick={handleClose} style={{ marginTop: 12, padding: "8px 16px", background: "#28a745", color: "white", border: "none", borderRadius: 4, cursor: "pointer" }}>
          Tutup Tiket
        </button>
      )}
    </div>
  );
}
