"use client";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const justRegistered = searchParams.get("registered") === "true";
  // Dipasang oleh lib/api.js waktu ada request yang balas 401 — termasuk
  // idle-timeout ISR-005 (sesi tidak aktif >15 menit) maupun token JWT yang
  // sudah lewat masa berlaku biasa. Tidak dibedakan pesannya karena dari
  // sisi user, keduanya sama-sama "harus login ulang".
  const sessionExpired = searchParams.get("expired") === "true";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleLogin(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.login(email, password);
      localStorage.setItem("access_token", data.access_token);

      // SRS ISR-002.c: password lewat 90 hari -> paksa ganti dulu, tidak
      // boleh langsung ke /chat.
      if (data.password_expired) {
        router.push("/change-password?expired=true");
        return;
      }

      // SRS ISR-001.g: simpan info login sebelumnya di sessionStorage (bukan
      // localStorage — sengaja cuma bertahan untuk tab ini, sekali ditampilkan
      // di halaman chat langsung dihapus, lihat chat/page.jsx).
      sessionStorage.setItem("login_info", JSON.stringify({
        previous_login_at: data.previous_login_at,
        failed_attempts_since_last_login: data.failed_attempts_since_last_login,
      }));

      router.push("/chat");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: "80px auto", padding: 24 }}>
      <h1>Masuk</h1>
      {sessionExpired && (
        <p style={{ background: "#fff3cd", border: "1px solid #ffe69c", padding: 10, borderRadius: 4, fontSize: 13, color: "#664d03", marginBottom: 12 }}>
          Sesi Anda berakhir (tidak ada aktivitas selama 15 menit atau token kadaluarsa). Silakan login kembali.
        </p>
      )}
      {justRegistered && (
        <p style={{ color: "green", marginBottom: 12 }}>
          Akun berhasil dibuat, silakan masuk.
        </p>
      )}
      <form onSubmit={handleLogin}>
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          style={{ width: "100%", padding: 8, marginBottom: 12 }}
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          style={{ width: "100%", padding: 8, marginBottom: 12 }}
        />
        {error && <p style={{ color: "red" }}>{error}</p>}
        <button type="submit" disabled={loading} style={{ width: "100%", padding: 10 }}>
          {loading ? "Memproses..." : "Masuk"}
        </button>
      </form>
      <p style={{ marginTop: 16, fontSize: 14 }}>
        Belum punya akun? <Link href="/register">Daftar di sini</Link>
      </p>
    </div>
  );
}