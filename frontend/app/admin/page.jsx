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

export default function AdminUsersPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [users, setUsers] = useState([]);
  const [error, setError] = useState("");
  const [savingId, setSavingId] = useState(null);

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

  const loadUsers = useCallback(async () => {
    try {
      const result = await api.listUsers();
      setUsers(result);
    } catch (err) {
      setError(err.message || "Gagal memuat daftar user");
    }
  }, []);

  useEffect(() => {
    if (hasAccess) loadUsers();
  }, [hasAccess, loadUsers]);

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
        <Link href="/chat">← Kembali ke Chat</Link>
      </div>

      {error && <p style={{ color: "#d32f2f" }}>{error}</p>}

      <div style={{ border: "1px solid #ddd", borderRadius: 8, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f1f1f1", textAlign: "left" }}>
              <th style={{ padding: 10 }}>Email</th>
              <th style={{ padding: 10 }}>Nama</th>
              <th style={{ padding: 10 }}>Terdaftar</th>
              <th style={{ padding: 10 }}>Role</th>
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
