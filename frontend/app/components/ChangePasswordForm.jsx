"use client";
// Form ganti password — dipakai DUA tempat: halaman /profile (sukarela) dan
// /change-password?expired=true (alur paksa SRS ISR-002.c). Dijadikan satu
// komponen supaya aturan validasinya tidak sempat beda antara dua jalur itu.

import { useState } from "react";
import { api } from "../../lib/api";
import { getPasswordError } from "../../lib/validation";

export default function ChangePasswordForm({ onSuccess }) {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

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
      if (onSuccess) onSuccess();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const field = { width: "100%", padding: 9, marginBottom: 12 };

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="password"
        placeholder="Password Lama"
        value={oldPassword}
        onChange={(e) => setOldPassword(e.target.value)}
        required
        style={field}
      />
      <input
        type="password"
        placeholder="Password Baru"
        value={newPassword}
        onChange={(e) => setNewPassword(e.target.value)}
        required
        style={{ ...field, marginBottom: 4 }}
      />
      <p style={{ fontSize: 12, color: "var(--idx-text-subtle)", margin: "0 0 12px" }}>
        Minimal 12 karakter, kombinasi huruf besar, huruf kecil, angka, dan karakter khusus
      </p>
      <input
        type="password"
        placeholder="Konfirmasi Password Baru"
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
        required
        style={field}
      />
      {error && <p style={{ color: "var(--idx-danger)", fontSize: 13 }}>{error}</p>}
      {success && <p style={{ color: "var(--idx-success)", fontSize: 13 }}>{success}</p>}
      <button type="submit" disabled={loading}>
        {loading ? "Memproses..." : "Ubah Password"}
      </button>
    </form>
  );
}
