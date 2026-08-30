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
  const [rateLimitDraft, setRateLimitDraft] = useState({ max_messages: 30, window_seconds: 60 });
  const [savingRateLimit, setSavingRateLimit] = useState(false);
  const [retentionDraft, setRetentionDraft] = useState("");
  const [savingRetention, setSavingRetention] = useState(false);
  const [applyingRetention, setApplyingRetention] = useState(false);
  const [retentionResult, setRetentionResult] = useState(null);

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
      setRateLimitDraft({
        max_messages: result.chat_rate_limit_max_messages,
        window_seconds: result.chat_rate_limit_window_seconds,
      });
      setRetentionDraft(result.chat_retention_days ?? "");
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

  async function handleSaveRateLimit() {
    setSavingRateLimit(true);
    setError("");
    try {
      const result = await api.updateRateLimit(
        Number(rateLimitDraft.max_messages),
        Number(rateLimitDraft.window_seconds)
      );
      setSystemSettings(result);
    } catch (err) {
      setError(err.message || "Gagal menyimpan rate limit");
    } finally {
      setSavingRateLimit(false);
    }
  }

  async function handleSaveRetention() {
    setSavingRetention(true);
    setError("");
    try {
      const days = retentionDraft === "" ? null : Number(retentionDraft);
      const result = await api.updateRetention(days);
      setSystemSettings(result);
    } catch (err) {
      setError(err.message || "Gagal menyimpan kebijakan retensi");
    } finally {
      setSavingRetention(false);
    }
  }

  async function handleApplyRetention() {
    setApplyingRetention(true);
    setError("");
    setRetentionResult(null);
    try {
      const result = await api.applyRetention();
      setRetentionResult(result.archived_count);
    } catch (err) {
      setError(err.message || "Gagal menerapkan kebijakan retensi");
    } finally {
      setApplyingRetention(false);
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
            <p style={{ margin: "6px 0 0", fontSize: 12, color: "#b26a00" }}>
              ⚠️ Tombol darurat: berlaku ke <b>SELURUH divisi</b>, bukan cuma divisi Anda.
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

      {/* F2-08 (spesifikasi Tingkat 2): role mana boleh export chat ke PDF.
          Mulai sini semua setelan dikunci admin GLOBAL (backend juga menolak 403) —
          efeknya lintas divisi, jadi bukan wewenang admin divisi. Force-stop di atas
          SENGAJA dikecualikan: emergency kill switch, lihat komentar di admin/routes.py. */}
      {systemSettings && isGlobalAdmin && (
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

      {/* SRS poin 4.c-d: rate limiting & API limiter dikonfigurasi IT Admin (dulu cuma .env + restart) */}
      {systemSettings && isGlobalAdmin && (
        <div style={{ padding: 16, marginBottom: 20, borderRadius: 8, background: "#f9f9f9", border: "1px solid #ddd" }}>
          <b>Rate Limit Chat</b>
          <p style={{ margin: "4px 0 12px", fontSize: 13, color: "#666" }}>
            Batas jumlah pesan per user dalam satu jendela waktu. Melebihi batas ini akan ditolak (429) sementara.
          </p>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
            <label style={{ fontSize: 13 }}>
              Maks. pesan
              <br />
              <input
                type="number"
                min={1}
                value={rateLimitDraft.max_messages}
                onChange={(e) => setRateLimitDraft((prev) => ({ ...prev, max_messages: e.target.value }))}
                style={{ padding: 6, width: 100, marginTop: 4 }}
              />
            </label>
            <label style={{ fontSize: 13 }}>
              per (detik)
              <br />
              <input
                type="number"
                min={1}
                value={rateLimitDraft.window_seconds}
                onChange={(e) => setRateLimitDraft((prev) => ({ ...prev, window_seconds: e.target.value }))}
                style={{ padding: 6, width: 100, marginTop: 4 }}
              />
            </label>
            <button
              onClick={handleSaveRateLimit}
              disabled={savingRateLimit}
              style={{ padding: "8px 16px", border: "none", borderRadius: 4, cursor: savingRateLimit ? "wait" : "pointer", background: "#0070f3", color: "white", fontWeight: "bold" }}
            >
              {savingRateLimit ? "Menyimpan..." : "Simpan"}
            </button>
          </div>
        </div>
      )}

      {/* SRS poin 6: konfigurasi retensi data historis */}
      {systemSettings && isGlobalAdmin && (
        <div style={{ padding: 16, marginBottom: 20, borderRadius: 8, background: "#f9f9f9", border: "1px solid #ddd" }}>
          <b>Retensi Data Historis</b>
          <p style={{ margin: "4px 0 12px", fontSize: 13, color: "#666" }}>
            Chat yang lebih tua dari jumlah hari ini akan diarsipkan (bukan dihapus permanen) saat kebijakan diterapkan.
            Kosongkan untuk tanpa batas (retensi nonaktif).
          </p>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
            <label style={{ fontSize: 13 }}>
              Retensi (hari)
              <br />
              <input
                type="number"
                min={1}
                placeholder="tanpa batas"
                value={retentionDraft}
                onChange={(e) => setRetentionDraft(e.target.value)}
                style={{ padding: 6, width: 120, marginTop: 4 }}
              />
            </label>
            <button
              onClick={handleSaveRetention}
              disabled={savingRetention}
              style={{ padding: "8px 16px", border: "none", borderRadius: 4, cursor: savingRetention ? "wait" : "pointer", background: "#0070f3", color: "white", fontWeight: "bold" }}
            >
              {savingRetention ? "Menyimpan..." : "Simpan Kebijakan"}
            </button>
            <button
              onClick={handleApplyRetention}
              disabled={applyingRetention || !systemSettings.chat_retention_days}
              title={!systemSettings.chat_retention_days ? "Simpan kebijakan retensi (isi jumlah hari) terlebih dahulu" : ""}
              style={{
                padding: "8px 16px", border: "none", borderRadius: 4,
                cursor: applyingRetention || !systemSettings.chat_retention_days ? "not-allowed" : "pointer",
                background: "#555", color: "white", fontWeight: "bold",
                opacity: !systemSettings.chat_retention_days ? 0.5 : 1,
              }}
            >
              {applyingRetention ? "Menerapkan..." : "Terapkan Sekarang"}
            </button>
            {retentionResult !== null && (
              <span style={{ fontSize: 13, color: "#2e7d32" }}>
                ✓ {retentionResult} percakapan diarsipkan
              </span>
            )}
          </div>
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
