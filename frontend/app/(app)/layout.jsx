"use client";
// Shell aplikasi: sidebar PERSISTEN di kiri + panel isi di kanan.
//
// Route group "(app)" tidak muncul di URL — /chat tetap /chat. Bedanya, semua
// halaman di dalamnya kini berbagi layout ini, jadi berpindah menu hanya
// menukar isi panel kanan; sidebar tidak di-mount ulang. Halaman di luar shell
// (login, register, MFA, ganti password paksa) sengaja TIDAK ikut, karena di
// alur itu user belum boleh melihat navigasi aplikasi.

import { useState, useEffect, useCallback, Suspense } from "react";
import { useRouter, usePathname } from "next/navigation";
import { api } from "../../lib/api";
import Sidebar from "../components/Sidebar";
import { ShellContext } from "../components/ShellContext";
import { DialogProvider } from "../components/Dialog";

export default function AppShellLayout({ children }) {
  const router = useRouter();
  const pathname = usePathname();
  const [currentUser, setCurrentUser] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [archivedChats, setArchivedChats] = useState([]);
  const [activeTickets, setActiveTickets] = useState([]);
  const [checkingSession, setCheckingSession] = useState(true);

  const refreshHistory = useCallback(async () => {
    try {
      setChatHistory(await api.getChatHistory(false));
    } catch (err) {
      console.error("Gagal memuat riwayat:", err);
    }
  }, []);

  const refreshArchived = useCallback(async () => {
    try {
      setArchivedChats(await api.getChatHistory(true));
    } catch (err) {
      console.error("Gagal memuat arsip:", err);
    }
  }, []);

  const refreshTickets = useCallback(async () => {
    try {
      setActiveTickets(await api.listTickets("open"));
    } catch {
      /* tiket bukan fitur kritis untuk render shell — diamkan saja kalau gagal */
    }
  }, []);

  useEffect(() => {
    if (!api.isLoggedIn()) {
      router.push("/login");
      return;
    }
    api.getMe()
      .then((user) => {
        setCurrentUser(user);
        setCheckingSession(false);
        refreshHistory();
        if (user.role !== "it_admin") refreshTickets();
      })
      .catch(() => {
        api.logout();
        router.push("/login");
      });
  }, []);

  if (checkingSession) {
    return (
      <div style={{ padding: 40, color: "var(--idx-text-subtle)" }}>Memeriksa sesi...</div>
    );
  }

  return (
    <ShellContext.Provider value={{ currentUser, chatHistory, archivedChats, refreshHistory, refreshArchived, activeTickets, refreshTickets }}>
      <DialogProvider>
        <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
          <Suspense fallback={<div style={{ width: 268, flexShrink: 0 }} />}>
            <Sidebar />
          </Suspense>
          {/* key={pathname} memaksa remount tiap pindah halaman, supaya animasi
              masuknya benar-benar jalan lagi (bukan cuma sekali di awal). */}
          <main key={pathname} className="page-enter" style={{ flex: 1, minWidth: 0, overflowY: "auto" }}>
            {children}
          </main>
        </div>
      </DialogProvider>
    </ShellContext.Provider>
  );
}
