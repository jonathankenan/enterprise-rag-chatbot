"use client";
// [PENANGGUNG JAWAB: Anggota B]

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "../../lib/api";
import { getPasswordError } from "../../lib/validation";

export default function ChangePasswordPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const forcedByExpiry = searchParams.get("expired") === "true"; // SRS ISR-002.c
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!api.isLoggedIn()) {
      router.push("/login");
    }
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setSuccess("");

    const passwordError = getPasswordError(newPassword);
    if (passwordError) {
      setError(passwordError);
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Konfirmasi password baru tidak cocok");
      return;
    }

    setLoading(true);
    try {
      await api.changePassword(oldPassword, newPassword);
      setSuccess("Password berhasil diubah.");
      setOldPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: "80px auto", padding: 24 }}>
      <h1>Ganti Password</h1>
      {forcedByExpiry && (
        <p style={{ background: "#fff3cd", border: "1px solid #ffe69c", padding: 10, borderRadius: 4, fontSize: 13, color: "#664d03" }}>
          Password Anda sudah berumur lebih dari 90 hari dan wajib diganti sebelum melanjutkan (SRS ISR-002.c).
        </p>
      )}
      <form onSubmit={handleSubmit}>
        <input
          type="password"
          placeholder="Password Lama"
          value={oldPassword}
          onChange={(e) => setOldPassword(e.target.value)}
          required
          style={{ width: "100%", padding: 8, marginBottom: 12 }}
        />
        <input
          type="password"
          placeholder="Password Baru"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          required
          style={{ width: "100%", padding: 8, marginBottom: 4 }}
        />
        <p style={{ fontSize: 12, color: "#888", marginTop: 0, marginBottom: 12 }}>
          Minimal 12 karakter, kombinasi huruf besar, huruf kecil, angka, dan karakter khusus
        </p>
        <input
          type="password"
          placeholder="Konfirmasi Password Baru"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          required
          style={{ width: "100%", padding: 8, marginBottom: 12 }}
        />
        {error && <p style={{ color: "red" }}>{error}</p>}
        {success && <p style={{ color: "green" }}>{success}</p>}
        <button type="submit" disabled={loading} style={{ width: "100%", padding: 10 }}>
          {loading ? "Memproses..." : "Ubah Password"}
        </button>
      </form>
      <p style={{ marginTop: 16, fontSize: 14 }}>
        <Link href="/chat">← Kembali ke Chat</Link>
      </p>
    </div>
  );
}