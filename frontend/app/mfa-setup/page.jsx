"use client";
// [PENANGGUNG JAWAB: Anggota B]
// Setup MFA pertama kali — SRS ISR-001.d. Halaman ini cuma bisa dicapai
// lewat mfa_token sementara yang dikasih login/page.jsx (kalau langsung
// dibuka tanpa lewat login, mfa_token kosong -> lempar balik ke /login).

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

export default function MfaSetupPage() {
  const router = useRouter();
  const [mfaToken, setMfaToken] = useState(null);
  const [secret, setSecret] = useState("");
  const [qrCode, setQrCode] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const token = sessionStorage.getItem("mfa_token");
    if (!token) {
      router.push("/login");
      return;
    }
    setMfaToken(token);
    api.mfaSetup(token)
      .then((result) => {
        setSecret(result.secret);
        setQrCode(result.qr_code_base64);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Gagal memuat data setup MFA");
        setLoading(false);
      });
  }, []);

  async function handleConfirm(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const data = await api.mfaSetupConfirm(mfaToken, secret, code);
      completeLogin(router, data);
    } catch (err) {
      setError(err.message || "Kode salah, coba lagi");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ maxWidth: 400, margin: "60px auto", padding: 24 }}>
      <h1>Setup Autentikasi Dua Faktor</h1>
      <p style={{ color: "#666", fontSize: 14 }}>
        Akun Anda (IT Admin) wajib mengaktifkan MFA sebelum bisa masuk (SRS ISR-001.d).
        Scan QR code ini pakai aplikasi authenticator (Google Authenticator, Authy, dll).
      </p>

      {loading && <p>Memuat...</p>}
      {error && <p style={{ color: "red" }}>{error}</p>}

      {qrCode && (
        <>
          <div style={{ textAlign: "center", margin: "20px 0" }}>
            <img src={qrCode} alt="QR Code MFA" style={{ width: 200, height: 200 }} />
          </div>
          <p style={{ fontSize: 12, color: "#666" }}>
            Tidak bisa scan? Masukkan kode ini secara manual: <code style={{ background: "#f1f1f1", padding: "2px 6px" }}>{secret}</code>
          </p>

          <form onSubmit={handleConfirm}>
            <input
              type="text"
              inputMode="numeric"
              placeholder="Kode 6 digit dari aplikasi"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              maxLength={6}
              style={{ width: "100%", padding: 8, marginBottom: 12, marginTop: 12, fontSize: 18, textAlign: "center", letterSpacing: 4 }}
            />
            <button type="submit" disabled={submitting} style={{ width: "100%", padding: 10 }}>
              {submitting ? "Memverifikasi..." : "Aktifkan & Masuk"}
            </button>
          </form>
        </>
      )}
    </div>
  );
}
