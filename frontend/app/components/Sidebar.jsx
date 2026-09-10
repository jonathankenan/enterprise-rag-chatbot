"use client";
// Navigasi kiri yang PERSISTEN — dirender sekali di (app)/layout.jsx, jadi
// pindah menu cuma mengganti isi panel kanan tanpa sidebar ikut di-mount ulang.

import { useState, useEffect, useRef } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "../../lib/api";
import IdxLogo from "./IdxLogo";
import { IconNewChat, IconAudit, IconUsers, IconBook, IconHeadset, IconArchive, IconChats, IconPanel } from "./Icons";
import { useShell } from "./ShellContext";
import { roleLabel } from "../../lib/roles";
import { useDialog } from "./Dialog";

const AUDIT_VIEWERS = ["it_admin", "compliance", "auditor"]; // samakan dgn Role.AUDIT_VIEWERS di backend

function Caret({ open }) {
  return <span className={`nav-caret${open ? " open" : ""}`}>▼</span>;
}

function Section({ label, icon, open, onToggle, collapsed, children }) {
  // Saat sidebar ciut, judul grup jadi tombol ikon yang MEMBENTANGKAN lagi —
  // isinya tidak muat ditampilkan, tapi menunya tetap bisa dijangkau.
  if (collapsed) {
    return (
      <button className="nav-item nav-icon-only" onClick={onToggle} title={label} aria-label={label}>
        {icon}
      </button>
    );
  }
  return (
    <>
      <button className="nav-item nav-parent" onClick={onToggle} aria-expanded={open}>
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>{icon}{label}</span>
        <Caret open={open} />
      </button>
      {open && <div className="collapse-enter nav-children">{children}</div>}
    </>
  );
}

// Satu baris percakapan + menu titik-tiga yang muncul saat hover.
function ChatRow({ chat, active, archived, onRename, onArchive, onUnarchive, onDelete }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(chat.title);
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);

  function submitRename() {
    const trimmed = draft.trim();
    setRenaming(false);
    if (trimmed && trimmed !== chat.title) onRename(chat.id, trimmed);
    else setDraft(chat.title);
  }

  if (renaming) {
    return (
      <div className="chat-row" style={{ padding: "2px 6px 2px 8px" }}>
        <input
          autoFocus
          value={draft}
          maxLength={100}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={submitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") submitRename();
            if (e.key === "Escape") { setDraft(chat.title); setRenaming(false); }
          }}
          style={{ width: "100%", fontSize: 13, padding: "4px 6px" }}
        />
      </div>
    );
  }

  return (
    <div className={`chat-row${active ? " active" : ""}`} ref={wrapRef}>
      <Link href={`/chat?id=${chat.id}`} className="chat-row-link" title={chat.title}>
        {chat.title}
      </Link>
      <button
        className={`chat-row-menu-btn${menuOpen ? " open" : ""}`}
        onClick={(e) => { e.preventDefault(); setMenuOpen((v) => !v); }}
        title="Opsi percakapan"
        aria-label="Opsi percakapan"
      >
        ⋮
      </button>
      {menuOpen && (
        <div className="popup-menu" style={{ top: "100%", right: 4 }}>
          <button className="popup-item" onClick={() => { setMenuOpen(false); setDraft(chat.title); setRenaming(true); }}>
            Ubah nama
          </button>
          {archived ? (
            <button className="popup-item" onClick={() => { setMenuOpen(false); onUnarchive(chat.id); }}>
              Batalkan arsip
            </button>
          ) : (
            <button className="popup-item" onClick={() => { setMenuOpen(false); onArchive(chat.id); }}>
              Arsipkan
            </button>
          )}
          <button className="popup-item danger" onClick={() => { setMenuOpen(false); onDelete(chat.id); }}>
            Hapus
          </button>
        </div>
      )}
    </div>
  );
}

export default function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeChatId = searchParams.get("id");
  const { currentUser, chatHistory, archivedChats, refreshHistory, refreshArchived } = useShell();
  const dialog = useDialog();

  const [kelolaOpen, setKelolaOpen] = useState(pathname.startsWith("/admin") || pathname.startsWith("/helpdesk/tickets"));
  const [kbOpen, setKbOpen] = useState(pathname.startsWith("/admin/kb") || pathname.startsWith("/helpdesk/faq"));
  const [arsipOpen, setArsipOpen] = useState(false);
  const [riwayatOpen, setRiwayatOpen] = useState(true);
  const [profileOpen, setProfileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const profileRef = useRef(null);

  // Pilihan ciut/bentang diingat antar-kunjungan. Dibaca di effect (bukan saat
  // useState) supaya render server & klien tetap sama dan tidak hydration error.
  useEffect(() => {
    try { setCollapsed(localStorage.getItem("sidebar_collapsed") === "1"); } catch { /* storage diblokir */ }
  }, []);

  function toggleCollapsed() {
    setCollapsed((v) => {
      const next = !v;
      try { localStorage.setItem("sidebar_collapsed", next ? "1" : "0"); } catch { /* abaikan */ }
      return next;
    });
  }

  const isAdmin = currentUser?.role === "it_admin";
  const canAudit = AUDIT_VIEWERS.includes(currentUser?.role);

  useEffect(() => {
    if (!profileOpen) return;
    const close = (e) => {
      if (profileRef.current && !profileRef.current.contains(e.target)) setProfileOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [profileOpen]);

  // Arsip baru diambil saat dropdown-nya pertama kali dibuka — tidak perlu
  // membebani load awal shell dengan data yang jarang dilihat.
  useEffect(() => {
    if (arsipOpen) refreshArchived();
  }, [arsipOpen]);

  async function handleNewChat() {
    try {
      const chat = await api.createChat("Percakapan Baru");
      await refreshHistory();
      router.push(`/chat?id=${chat.id}`);
    } catch (err) {
      dialog.alert("Gagal membuat percakapan baru: " + err.message);
    }
  }

  async function handleRename(id, title) {
    try {
      await api.renameChat(id, title);
      await Promise.all([refreshHistory(), refreshArchived()]);
    } catch (err) {
      dialog.alert("Gagal mengubah nama: " + err.message);
    }
  }

  async function handleArchive(id) {
    try {
      await api.archiveChat(id);
      await Promise.all([refreshHistory(), refreshArchived()]);
      if (id === activeChatId) router.push("/chat");
    } catch (err) {
      dialog.alert("Gagal mengarsipkan: " + err.message);
    }
  }

  async function handleUnarchive(id) {
    try {
      await api.unarchiveChat(id);
      await Promise.all([refreshHistory(), refreshArchived()]);
    } catch (err) {
      dialog.alert("Gagal membatalkan arsip: " + err.message);
    }
  }

  async function handleDelete(id) {
    const ok = await dialog.confirm(
      "Hapus percakapan ini secara permanen? Tindakan ini tidak bisa dibatalkan.",
      { title: "Hapus Percakapan", confirmLabel: "Hapus", danger: true }
    );
    if (!ok) return;
    try {
      await api.deleteChat(id);
      await Promise.all([refreshHistory(), refreshArchived()]);
      if (id === activeChatId) router.push("/chat");
    } catch (err) {
      dialog.alert("Gagal menghapus: " + err.message);
    }
  }

  function handleLogout() {
    api.logout();
    router.push("/login");
  }

  const rowProps = { onRename: handleRename, onArchive: handleArchive, onUnarchive: handleUnarchive, onDelete: handleDelete };

  return (
    <aside
      style={{
        width: collapsed ? 68 : 268, flexShrink: 0, height: "100vh",
        borderRight: "1px solid var(--idx-border)", background: "var(--idx-bg)",
        display: "flex", flexDirection: "column", padding: "16px 10px 10px",
        transition: "width 0.18s ease", overflow: "hidden",
      }}
    >
      {/* Saat ciut, logo & tombol ditumpuk vertikal — berdampingan tidak muat
          di lebar 68px dan logonya jadi terpotong. */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8, padding: "0 6px 14px",
        flexDirection: collapsed ? "column" : "row",
        justifyContent: collapsed ? "center" : "space-between",
      }}>
        <Link href="/chat" style={{ textDecoration: "none", minWidth: 0 }}>
          <IdxLogo showText={!collapsed} size={collapsed ? 32 : 38} />
        </Link>
        <button
          onClick={toggleCollapsed}
          className="sidebar-toggle"
          title={collapsed ? "Bentangkan sidebar" : "Ciutkan sidebar"}
          aria-label={collapsed ? "Bentangkan sidebar" : "Ciutkan sidebar"}
        >
          <IconPanel />
        </button>
      </div>

      <div style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
        <button
          className={`nav-item ${collapsed ? "nav-icon-only" : "nav-parent"}`}
          onClick={handleNewChat}
          title="Percakapan Baru"
        >
          {collapsed ? <IconNewChat /> : <span style={{ display: "flex", alignItems: "center", gap: 10 }}><IconNewChat />Percakapan Baru</span>}
        </button>

        {canAudit && (
          <Link
            href="/audit"
            title="Audit Log"
            className={`nav-item ${collapsed ? "nav-icon-only" : "nav-parent"}${pathname === "/audit" ? " active" : ""}`}
          >
            {collapsed ? <IconAudit /> : <span style={{ display: "flex", alignItems: "center", gap: 10 }}><IconAudit />Audit Log</span>}
          </Link>
        )}

        {isAdmin && (
          <Section label="Kelola User" icon={<IconUsers />} collapsed={collapsed} open={kelolaOpen} onToggle={() => { if (collapsed) toggleCollapsed(); setKelolaOpen(collapsed ? true : !kelolaOpen); }}>
            <div>
              <Link href="/admin" className={`nav-item${pathname === "/admin" ? " active" : ""}`}>Manajemen User</Link>
              <Link href="/helpdesk/tickets" className={`nav-item${pathname.startsWith("/helpdesk/tickets") ? " active" : ""}`}>Tiket Helpdesk</Link>
            </div>
          </Section>
        )}

        {isAdmin && (
          <Section label="Knowledge Base" icon={<IconBook />} collapsed={collapsed} open={kbOpen} onToggle={() => { if (collapsed) toggleCollapsed(); setKbOpen(collapsed ? true : !kbOpen); }}>
            <div>
              <Link href="/helpdesk/faq" className={`nav-item${pathname === "/helpdesk/faq" ? " active" : ""}`}>FAQ Helpdesk</Link>
              <Link href="/admin/kb" className={`nav-item${pathname === "/admin/kb" ? " active" : ""}`}>Knowledge Base Divisi</Link>
            </div>
          </Section>
        )}

        {/* IT Admin global tidak punya admin di atasnya, jadi menu ini
            memang tidak berlaku untuknya (backend juga menolak, 400). */}
        {!(isAdmin && !currentUser?.divisi) && (
          <Link
            href="/helpdesk/chat"
            title="Hubungi Admin"
            className={`nav-item ${collapsed ? "nav-icon-only" : "nav-parent"}${pathname === "/helpdesk/chat" ? " active" : ""}`}
          >
            {collapsed ? <IconHeadset /> : <span style={{ display: "flex", alignItems: "center", gap: 10 }}><IconHeadset />Hubungi Admin</span>}
          </Link>
        )}

        <Section label="Arsip Percakapan" icon={<IconArchive />} collapsed={collapsed} open={arsipOpen} onToggle={() => { if (collapsed) toggleCollapsed(); setArsipOpen(collapsed ? true : !arsipOpen); }}>
          <div>
            {archivedChats.length === 0 ? (
              <p style={{ fontSize: 12.5, color: "var(--idx-text-subtle)", padding: "4px 12px" }}>Belum ada arsip.</p>
            ) : (
              archivedChats.map((c) => (
                <ChatRow key={c.id} chat={c} archived active={c.id === activeChatId && pathname === "/chat"} {...rowProps} />
              ))
            )}
          </div>
        </Section>

        <Section label="Percakapan" icon={<IconChats />} collapsed={collapsed} open={riwayatOpen} onToggle={() => { if (collapsed) toggleCollapsed(); setRiwayatOpen(collapsed ? true : !riwayatOpen); }}>
          <div>
            {chatHistory.length === 0 ? (
              <p style={{ fontSize: 12.5, color: "var(--idx-text-subtle)", padding: "4px 12px" }}>Belum ada percakapan.</p>
            ) : (
              chatHistory.map((c) => (
                <ChatRow key={c.id} chat={c} active={c.id === activeChatId && pathname === "/chat"} {...rowProps} />
              ))
            )}
          </div>
        </Section>
      </div>

      {/* Profil di paling bawah */}
      <div style={{ position: "relative", borderTop: "1px solid var(--idx-border)", paddingTop: 8, marginTop: 8 }} ref={profileRef}>
        {profileOpen && (
          <div className="popup-menu" style={{ bottom: "100%", left: 4, right: 4, marginBottom: 6 }}>
            <Link href="/profile" className="popup-item" onClick={() => setProfileOpen(false)}>Pengaturan Profil</Link>
            <button className="popup-item danger" onClick={handleLogout}>Keluar</button>
          </div>
        )}
        <button
          onClick={() => setProfileOpen((v) => !v)}
          style={{
            display: "flex", alignItems: "center", gap: 10, width: "100%",
            padding: "8px 10px", borderRadius: 8, border: "none",
            background: profileOpen ? "var(--idx-surface-active)" : "transparent",
            cursor: "pointer", textAlign: "left",
          }}
        >
          <span style={{
            width: 30, height: 30, borderRadius: "50%", flexShrink: 0,
            background: "var(--idx-red)", color: "#fff",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 12, fontWeight: 700,
          }}>
            {(currentUser?.full_name || currentUser?.email || "?").charAt(0).toUpperCase()}
          </span>
          {!collapsed && <span style={{ minWidth: 0, flex: 1 }}>
            <span style={{ display: "block", fontSize: 13, fontWeight: 600, color: "var(--idx-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {currentUser?.full_name || currentUser?.email || "—"}
            </span>
            <span style={{ display: "block", fontSize: 11.5, color: "var(--idx-text-subtle)" }}>
              {roleLabel(currentUser?.role)}{currentUser?.divisi ? ` · ${currentUser.divisi}` : ""}
            </span>
          </span>}
        </button>
      </div>
    </aside>
  );
}
