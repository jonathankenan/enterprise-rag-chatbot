"use client";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "../../lib/api";
import { AuthShell, AuthTitle, AuthField, AuthPasswordField, AuthSubmit } from "../components/AuthLayout";
import { IconMail, IconLock } from "../components/Icons";

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
  const [azureLoading, setAzureLoading] = useState(false);
  const [showResetHint, setShowResetHint] = useState(false);

  // SRS hal. 64: "User dapat login menggunakan credential Azure AD
  // (primary) atau user internal platform (alternative)" — tombol ini
  // redirect ke Microsoft, browser kembali lagi ke /auth/azure/callback
  // setelah user login di sana (lihat app/auth/azure/callback/page.jsx).
  async function handleAzureLogin() {
    setError("");
    setAzureLoading(true);
    try {
      const { auth_url } = await api.getAzureLoginUrl();
      window.location.href = auth_url;
    } catch (err) {
      setError(err.message || "SSO Azure AD belum tersedia");
      setAzureLoading(false);
    }
  }

  async function handleLogin(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.login(email, password);

      // SRS ISR-001.d: password benar, tapi ini akun IT Admin yang WAJIB
      // MFA — belum ada access_token sama sekali di titik ini, jangan
      // simpan apa-apa ke localStorage dulu. mfa_token (bukan access_token)
      // disimpan sebentar di sessionStorage buat dipakai halaman MFA.
      if (data.mfa_setup_required) {
        sessionStorage.setItem("mfa_token", data.mfa_token);
        router.push("/mfa-setup");
        return;
      }
      if (data.mfa_required) {
        sessionStorage.setItem("mfa_token", data.mfa_token);
        router.push("/mfa-verify");
        return;
      }

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
    <AuthShell>
      <AuthTitle sub={<>Baru di Website IDX? <Link href="/register">Daftar disini</Link></>}>
        Masuk ke akun Anda
      </AuthTitle>

      {sessionExpired && (
        <p style={{ background: "var(--idx-warning-tint)", border: "1px solid var(--idx-warning-border)", padding: 10, borderRadius: 6, fontSize: 13, color: "var(--idx-warning)", marginBottom: 14 }}>
          Sesi Anda berakhir (tidak ada aktivitas selama 15 menit atau token kadaluarsa). Silakan login kembali.
        </p>
      )}
      {justRegistered && (
        <p style={{ color: "var(--idx-success)", marginBottom: 14, fontSize: 13.5 }}>
          Akun berhasil dibuat, silakan masuk.
        </p>
      )}

      <form onSubmit={handleLogin}>
        <AuthField
          icon={<IconMail />}
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <AuthPasswordField
          icon={<IconLock />}
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error && <p style={{ color: "var(--idx-danger)", fontSize: 13 }}>{error}</p>}
        <AuthSubmit disabled={loading}>{loading ? "Memproses..." : "Masuk"}</AuthSubmit>
      </form>

      <div style={{ textAlign: "right", marginTop: 12 }}>
        <button
          type="button"
          onClick={() => setShowResetHint((v) => !v)}
          style={{ background: "transparent", border: "none", padding: 0, color: "var(--idx-red)", fontSize: 14, cursor: "pointer" }}
        >
          Lupa Kata Sandi?
        </button>
      </div>
      {/* Belum ada alur reset mandiri di backend — diarahkan ke IT Admin,
          bukan tombol yang tidak melakukan apa-apa. */}
      {showResetHint && (
        <p style={{ marginTop: 8, fontSize: 12.5, color: "var(--idx-text-muted)", background: "var(--idx-surface-alt)", padding: 10, borderRadius: 6 }}>
          Reset password dilakukan oleh IT Admin. Hubungi IT Admin divisi Anda untuk mengatur ulang kata sandi.
        </p>
      )}

      <div style={{ display: "flex", alignItems: "center", margin: "20px 0 14px", color: "var(--idx-text-subtle)", fontSize: 12 }}>
        <div style={{ flex: 1, borderTop: "1px solid var(--idx-border)" }} />
        <span style={{ padding: "0 10px" }}>atau</span>
        <div style={{ flex: 1, borderTop: "1px solid var(--idx-border)" }} />
      </div>

      <button
        type="button"
        onClick={handleAzureLogin}
        disabled={azureLoading}
        style={{
          width: "100%", padding: "13px 0", background: "var(--idx-text)", color: "var(--idx-bg)",
          border: "none", borderRadius: 8, cursor: azureLoading ? "wait" : "pointer",
          display: "flex", alignItems: "center", justifyContent: "center", gap: 8, fontSize: 14, fontWeight: 600,
        }}
      >
        <span style={{ fontWeight: "bold", fontSize: 15 }}>⊞</span>
        {azureLoading ? "Mengalihkan ke Microsoft..." : "Login dengan Microsoft"}
      </button>
    </AuthShell>
  );
}
