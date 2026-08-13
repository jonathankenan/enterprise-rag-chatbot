"use client";
// [PENANGGUNG JAWAB: Anggota B]
// Halaman tiket helpdesk — SRS FCR-003 poin 7 "Eskalasi otomatis". Tiket
// dibuat backend sendiri (chat/routes.py) saat confidence AI rendah;
// halaman ini cuma untuk MELIHAT & menutup tiket, tidak ada form "buat
// tiket manual" (sesuai SRS: pembuatannya otomatis, bukan aksi user).

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "../../lib/api";

export default function HelpdeskPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [tickets, setTickets] = useState([]);
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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

  const hasAccess = currentUser && currentUser.role === "it_admin";

  const loadTickets = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await api.listTickets(statusFilter || undefined);
      setTickets(result);
    } catch (err) {
      setError(err.message || "Gagal memuat tiket");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    if (hasAccess) loadTickets();
  }, [hasAccess, loadTickets]);

  async function openTicket(id) {
    try {
      const detail = await api.getTicket(id);
      setSelectedTicket(detail);
    } catch (err) {
      setError(err.message || "Gagal memuat detail tiket");
    }
  }

  async function handleClose(id) {
    try {
      await api.closeTicket(id);
      setSelectedTicket(null);
      loadTickets();
    } catch (err) {
      setError(err.message || "Gagal menutup tiket");
    }
  }

  if (checkingSession) return <div style={{ padding: 40 }}>Memuat...</div>;

  if (!hasAccess) {
    return (
      <div style={{ padding: 40, maxWidth: 600, margin: "0 auto", textAlign: "center" }}>
        <h1>Akses Ditolak</h1>
        <p style={{ color: "#666" }}>
          Halaman ini hanya untuk role IT Admin. Akun Anda ({currentUser?.email}) punya role <b>{currentUser?.role}</b>.
        </p>
        <Link href="/chat">Kembali ke Chat</Link>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px 40px", maxWidth: 1000, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ margin: 0 }}>Tiket Helpdesk</h1>
        <Link href="/chat">← Kembali ke Chat</Link>
      </div>

      {error && <p style={{ color: "#d32f2f" }}>{error}</p>}

      {selectedTicket ? (
        <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 20, background: "white" }}>
          <button onClick={() => setSelectedTicket(null)} style={{ marginBottom: 12, background: "transparent", border: "none", color: "#0070f3", cursor: "pointer" }}>
            ← Kembali ke daftar tiket
          </button>
          <h2 style={{ marginTop: 0 }}>{selectedTicket.chat_title}</h2>
          <p style={{ fontSize: 13, color: "#666" }}>
            Dari: {selectedTicket.user_email} · Confidence: {selectedTicket.confidence_score}% ·
            Status: <b>{selectedTicket.status}</b> · {new Date(selectedTicket.created_at.endsWith("Z") ? selectedTicket.created_at : selectedTicket.created_at + "Z").toLocaleString()}
          </p>

          <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 16, marginBottom: 16, maxHeight: 400, overflowY: "auto" }}>
            {selectedTicket.messages.map((m) => (
              <div key={m.id} style={{ marginBottom: 10, textAlign: m.sender === "user" ? "right" : "left" }}>
                <div style={{ display: "inline-block", padding: "8px 12px", borderRadius: 8, background: m.sender === "user" ? "#DCF0FF" : "#F1F1F1", maxWidth: "80%", textAlign: "left" }}>
                  {m.content}
                </div>
              </div>
            ))}
          </div>

          {selectedTicket.status === "open" && (
            <button onClick={() => handleClose(selectedTicket.id)} style={{ padding: "8px 16px", background: "#28a745", color: "white", border: "none", borderRadius: 4, cursor: "pointer" }}>
              Tutup Tiket
            </button>
          )}
        </div>
      ) : (
        <>
          <div style={{ marginBottom: 16 }}>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{ padding: 8 }}>
              <option value="">Semua status</option>
              <option value="open">Open</option>
              <option value="closed">Closed</option>
            </select>
          </div>

          <div style={{ border: "1px solid #ddd", borderRadius: 8, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f1f1f1", textAlign: "left" }}>
                  <th style={{ padding: 10 }}>Waktu</th>
                  <th style={{ padding: 10 }}>User</th>
                  <th style={{ padding: 10 }}>Confidence</th>
                  <th style={{ padding: 10 }}>Status</th>
                  <th style={{ padding: 10 }}></th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((t) => (
                  <tr key={t.id} style={{ borderTop: "1px solid #eee" }}>
                    <td style={{ padding: 10 }}>{new Date(t.created_at.endsWith("Z") ? t.created_at : t.created_at + "Z").toLocaleString()}</td>
                    <td style={{ padding: 10 }}>{t.user_email}</td>
                    <td style={{ padding: 10, color: "#d32f2f", fontWeight: "bold" }}>{t.confidence_score}%</td>
                    <td style={{ padding: 10 }}>{t.status}</td>
                    <td style={{ padding: 10 }}>
                      <button onClick={() => openTicket(t.id)} style={{ padding: "4px 10px", cursor: "pointer" }}>Lihat</button>
                    </td>
                  </tr>
                ))}
                {tickets.length === 0 && !loading && (
                  <tr><td colSpan={5} style={{ padding: 20, textAlign: "center", color: "#888" }}>Tidak ada tiket.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
