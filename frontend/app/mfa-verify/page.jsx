"use client";
// [PENANGGUNG JAWAB: Anggota B]
// Verifikasi MFA (akun yang MFA-nya SUDAH aktif) — SRS ISR-001.d.

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "../../lib/api";

function completeLogin(router, data) {
  localStorage.setItem("access_token", data.access_token);
  sessionStorage.removeItem("mfa_token");
  if (data.password_expired) {
    router.push("/change-password?expired=true");
    return;
  }
  sessionStorage.setItem("login_info", JSON.stringify({
    previous_login_at: data.previous_login_at,
    failed_attempts_since_last_login: data.failed_attempts_since_last_login,
  }));
  router.push("/chat");
}

export default function MfaVerifyPage() {
  const router = useRouter();
  const [mfaToken, setMfaToken] = useState(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const token = sessionStorage.getItem("mfa_token");
    if (!token) {
      router.push("/login");
      return;
    }
    setMfaToken(token);
  }, []);

  async function handleVerify(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const data = await api.mfaVerify(mfaToken, code);
      completeLogin(router, data);
    } catch (err) {
      setError(err.message || "Kode salah, coba lagi");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: "80px auto", padding: 24 }}>
      <h1 className="page-title">Verifikasi Dua Faktor</h1>
      <p style={{ color: "var(--idx-text-muted)", fontSize: 14 }}>
        Masukkan kode 6 digit dari aplikasi authenticator Anda.
      </p>
      <form onSubmit={handleVerify}>
        <input
          type="text"
          inputMode="numeric"
          placeholder="Kode 6 digit"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          required
          autoFocus
          maxLength={6}
          style={{ width: "100%", padding: 8, marginBottom: 12, fontSize: 18, textAlign: "center", letterSpacing: 4 }}
        />
        {error && <p style={{ color: "var(--idx-danger)" }}>{error}</p>}
        <button type="submit" disabled={submitting} style={{ width: "100%", padding: 10 }}>
          {submitting ? "Memverifikasi..." : "Verifikasi"}
        </button>
      </form>
    </div>
  );
}
