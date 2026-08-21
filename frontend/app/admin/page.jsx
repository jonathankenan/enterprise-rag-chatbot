"use client";
// [PENANGGUNG JAWAB: Anggota B]
// Halaman manajemen user — sebelumnya ganti role user cuma bisa manual
// lewat SQL langsung ke database, sekarang lewat UI (dibatasi IT Admin).

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "../../lib/api";

// Samakan dengan Role.ALL di backend/app/models.py
const ALL_ROLES = [
  "it_admin", "designer", "mlops", "consumer_internal",
  "consumer_eipo", "business_user_designer", "compliance", "auditor",
];

// Samakan dengan Divisi.ALL di backend/app/models.py
const ALL_DIVISI = ["WAS", "PLP", "PPT", "PP1", "PP2", "PP3", "PTI", "SDI", "OTP"];

export default function AdminUsersPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [users, setUsers] = useState([]);
  const [error, setError] = useState("");
  const [savingId, setSavingId] = useState(null);
  const [systemSettings, setSystemSettings] = useState(null);
  const [togglingLlm, setTogglingLlm] = useState(false);
  const [exportRolesDraft, setExportRolesDraft] = useState([]);
  const [savingExportRoles, setSavingExportRoles] = useState(false);

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
  // SRS hal. 64/68/70: divisi KOSONG di akun IT_ADMIN = admin GLOBAL,
  // divisi TERISI = admin TERBATAS ke divisi itu saja. Bukan flag terpisah,
  // cuma baca field divisi milik akun sendiri.
  const isGlobalAdmin = currentUser && !currentUser.divisi;

  const loadUsers = useCallback(async () => {
    try {
      const result = await api.listUsers();
      setUsers(result);
    } catch (err) {
      setError(err.message || "Gagal memuat daftar user");
    }
  }, []);

  const loadSystemSettings = useCallback(async () => {
    try {
      const result = await api.getSystemSettings();
      setSystemSettings(result);
      setExportRolesDraft(result.export_allowed_roles);
    } catch (err) {
      setError(err.message || "Gagal memuat pengaturan sistem");
    }
  }, []);

  useEffect(() => {
    if (hasAccess) {
      loadUsers();
      loadSystemSettings();
    }
  }, [hasAccess, loadUsers, loadSystemSettings]);

  async function handleRoleChange(userId, newRole) {
    setSavingId(userId);
    setError("");
    try {
      await api.updateUserRole(userId, newRole);
      await loadUsers();
    } catch (err) {
      setError(err.message || "Gagal mengubah role");
    } finally {
      setSavingId(null);
    }
  }

  async function handleDivisiChange(userId, newDivisi) {
    setSavingId(userId);
    setError("");
    try {
      await api.updateUserDivisi(userId, newDivisi || null);
      await loadUsers();
    } catch (err) {
      setError(err.message || "Gagal mengubah divisi");
    } finally {
      setSavingId(null);
    }
  }

  async function handleToggleCommercialLlm() {
    setTogglingLlm(true);
    setError("");
    try {
      const result = await api.toggleCommercialLlm();
      setSystemSettings(result);
    } catch (err) {
      setError(err.message || "Gagal mengubah pengaturan");
    } finally {
      setTogglingLlm(false);
    }
  }

  function toggleExportRoleDraft(role) {
    setExportRolesDraft((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]
    );
  }

  async function handleSaveExportRoles() {
    setSavingExportRoles(true);
    setError("");
    try {
      const result = await api.updateExportRoles(exportRolesDraft);
      setSystemSettings(result);
      setExportRolesDraft(result.export_allowed_roles); // it_admin bisa ke-tambah otomatis di backend
    } catch (err) {
      setError(err.message || "Gagal menyimpan pengaturan export");
    } finally {
      setSavingExportRoles(false);
    }
  }

  if (checkingSession) return <div style={{ padding: 40 }}>Memuat...</div>;

  if (!hasAccess) {
    return (
      <div style={{ padding: 40, maxWidth: 600, margin: "0 auto", textAlign: "center" }}>
        <h1>Akses Ditolak</h1>
        <p style={{ color: "#666" }}>Halaman ini hanya untuk role IT Admin.</p>
        <Link href="/chat">Kembali ke Chat</Link>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px 40px", maxWidth: 1000, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ margin: 0 }}>Manajemen User</h1>
        <div>
          <Link href="/admin/kb">Knowledge Base Divisi</Link>
          {" · "}
          <Link href="/helpdesk">Helpdesk</Link>
          {" · "}
          <Link href="/chat">← Kembali ke Chat</Link>
        </div>
      </div>

      <p style={{ margin: "-12px 0 16px", fontSize: 13, color: "#666" }}>
        Anda: {isGlobalAdmin ? <b>IT Admin Global</b> : <>IT Admin Divisi <b>{currentUser.divisi}</b> (cuma kelola user &amp; KB divisi ini)</>}
      </p>

      {error && <p style={{ color: "#d32f2f" }}>{error}</p>}

      {/* SRS FCR-003 Rules poin 2: button force-stop LLM Commercial */}
      {systemSettings && (
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: 16, marginBottom: 20, borderRadius: 8,
          background: systemSettings.commercial_llm_force_stopped ? "#f8d7da" : "#f9f9f9",
          border: `1px solid ${systemSettings.commercial_llm_force_stopped ? "#f5c2c7" : "#ddd"}`,
        }}>
          <div>
            <b>Force-Stop LLM Commercial</b>
            <p style={{ margin: "4px 0 0", fontSize: 13, color: "#666" }}>
              {systemSettings.commercial_llm_force_stopped
                ? "🔴 AKTIF — semua chat dipaksa ke on-prem, apa pun provider yang dipilih user (Groq/Gemini/Mistral/Cloudflare dimatikan sementara)."
                : "🟢 Tidak aktif — user bebas pilih provider commercial seperti biasa."}
            </p>
          </div>
          <button
            onClick={handleToggleCommercialLlm}
            disabled={togglingLlm}
            style={{
              padding: "10px 20px", border: "none", borderRadius: 4, cursor: togglingLlm ? "wait" : "pointer",
              background: systemSettings.commercial_llm_force_stopped ? "#28a745" : "#d32f2f",
              color: "white", fontWeight: "bold",
            }}
          >
            {togglingLlm ? "Memproses..." : systemSettings.commercial_llm_force_stopped ? "Nyalakan Kembali" : "⛔ Force Stop"}
          </button>
        </div>
      )}

      {/* F2-08 (spesifikasi Tingkat 2): role mana boleh export chat ke PDF */}
      {systemSettings && (
        <div style={{ padding: 16, marginBottom: 20, borderRadius: 8, background: "#f9f9f9", border: "1px solid #ddd" }}>
          <b>Role yang Boleh Export PDF</b>
          <p style={{ margin: "4px 0 12px", fontSize: 13, color: "#666" }}>
            User dengan role di luar daftar ini akan ditolak (403) saat mencoba export percakapan ke PDF.
            IT Admin selalu ikut otomatis supaya tidak terkunci dari fitur ini.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 12 }}>
            {ALL_ROLES.map((role) => (
              <label key={role} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={exportRolesDraft.includes(role)}
                  disabled={role === "it_admin"}
                  onChange={() => toggleExportRoleDraft(role)}
                />
                {role}
              </label>
            ))}
          </div>
          <button
            onClick={handleSaveExportRoles}
            disabled={savingExportRoles}
            style={{ padding: "8px 16px", border: "none", borderRadius: 4, cursor: savingExportRoles ? "wait" : "pointer", background: "#0070f3", color: "white", fontWeight: "bold" }}
          >
            {savingExportRoles ? "Menyimpan..." : "Simpan"}
          </button>
        </div>
      )}

      <div style={{ border: "1px solid #ddd", borderRadius: 8, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f1f1f1", textAlign: "left" }}>
              <th style={{ padding: 10 }}>Email</th>
              <th style={{ padding: 10 }}>Nama</th>
              <th style={{ padding: 10 }}>Terdaftar</th>
              <th style={{ padding: 10 }}>Role</th>
              <th style={{ padding: 10 }}>Divisi</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} style={{ borderTop: "1px solid #eee" }}>
                <td style={{ padding: 10 }}>{u.email}</td>
                <td style={{ padding: 10 }}>{u.full_name || "-"}</td>
                <td style={{ padding: 10 }}>{new Date(u.created_at.endsWith("Z") ? u.created_at : u.created_at + "Z").toLocaleDateString()}</td>
                <td style={{ padding: 10 }}>
                  {u.id === currentUser.id ? (
                    <span title="Tidak bisa ubah role akun sendiri">{u.role} (Anda)</span>
                  ) : (
                    <select
                      value={u.role}
                      disabled={savingId === u.id}
                      onChange={(e) => handleRoleChange(u.id, e.target.value)}
                      style={{ padding: 4 }}
                    >
                      {ALL_ROLES.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  )}
                </td>
                <td style={{ padding: 10 }}>
                  {/* Endpoint /divisi cuma diizinkan backend untuk admin
                      GLOBAL (lihat admin/routes.py update_user_divisi) —
                      admin divisi lihat kolom ini read-only saja. */}
                  {u.id === currentUser.id || !isGlobalAdmin ? (
                    <span>{u.divisi || "—"}</span>
                  ) : (
                    <select
                      value={u.divisi || ""}
                      disabled={savingId === u.id}
                      onChange={(e) => handleDivisiChange(u.id, e.target.value)}
                      style={{ padding: 4 }}
                    >
                      <option value="">— (global/tanpa divisi)</option>
                      {ALL_DIVISI.map((d) => (
                        <option key={d} value={d}>{d}</option>
                      ))}
                    </select>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
