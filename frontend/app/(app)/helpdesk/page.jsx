"use client";
// [PENANGGUNG JAWAB: Anggota B]
// Hub navigasi Helpdesk — menaungi 2 fitur beda arah data yang sering
// tertukar namanya: Tiket Helpdesk (eskalasi KELUAR ke manusia, lihat
// helpdesk/tickets/page.jsx) dan FAQ Helpdesk (pengetahuan MASUK ke RAG,
// lihat helpdesk/faq/page.jsx). Keduanya dibatasi Role.IT_ADMIN.

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "../../../lib/api";

export default function HelpdeskHubPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);

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

  if (checkingSession) return <div style={{ padding: 40 }}>Memuat...</div>;

  if (!hasAccess) {
    return (
      <div style={{ padding: 40, maxWidth: 600, margin: "0 auto", textAlign: "center" }}>
        <h1>Akses Ditolak</h1>
        <p style={{ color: "var(--idx-text-muted)" }}>Halaman ini hanya untuk role IT Admin.</p>
        <Link href="/chat">Kembali ke Chat</Link>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px 40px", maxWidth: 900, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ margin: 0 }}>Helpdesk</h1>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Link
          href="/helpdesk/tickets"
          style={{ display: "block", padding: 24, borderRadius: 8, border: "1px solid var(--idx-border)", background: "var(--idx-surface)", textDecoration: "none", color: "inherit" }}
        >
          <div style={{ fontSize: 28, marginBottom: 8 }}></div>
          <b style={{ fontSize: 16 }}>Tiket Helpdesk</b>
          <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--idx-text-muted)" }}>
            Antrian eskalasi dari user — jawaban AI kurang meyakinkan, chat langsung dengan admin.
          </p>
        </Link>

        <Link
          href="/helpdesk/faq"
          style={{ display: "block", padding: 24, borderRadius: 8, border: "1px solid var(--idx-border)", background: "var(--idx-surface)", textDecoration: "none", color: "inherit" }}
        >
          <div style={{ fontSize: 28, marginBottom: 8 }}></div>
          <b style={{ fontSize: 16 }}>FAQ Helpdesk</b>
          <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--idx-text-muted)" }}>
            Kelola tanya-jawab yang otomatis jadi sumber jawaban AI di semua chat.
          </p>
        </Link>
      </div>
    </div>
  );
}
