"use client";
// [PENANGGUNG JAWAB: Anggota B]
// Halaman ini yang didaftarkan sebagai Redirect URI di Azure Portal (App
// Registration > Authentication) — Microsoft mengarahkan browser ke sini
// SETELAH user login/consent di halaman Microsoft, membawa `?code=...` di
// URL. Kode itu ditukar ke backend (api.azureCallback) buat jadi access
// token beneran — halaman ini sendiri tidak pernah pegang password akun
// Microsoft-nya sama sekali (prinsip OAuth: cuma Microsoft yang tahu itu).

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "../../../../lib/api";

function completeLogin(router, data) {
  localStorage.setItem("access_token", data.access_token);
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

export default function AzureCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState("");

  useEffect(() => {
    const code = searchParams.get("code");
    const msError = searchParams.get("error_description");

    if (msError) {
      setError(msError);
      return;
    }
    if (!code) {
      setError("Kode otorisasi tidak ditemukan di URL. Coba login ulang dari awal.");
      return;
    }

    api.azureCallback(code)
      .then((data) => {
        // SRS ISR-001.d: IT Admin tetap wajib MFA walau lolos SSO Azure AD —
        // SSO cuma menggantikan verifikasi password, bukan menggantikan MFA.
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
        completeLogin(router, data);
      })
      .catch((err) => {
        setError(err.message || "Login Azure AD gagal");
      });
  }, []);

  return (
    <div style={{ maxWidth: 400, margin: "80px auto", padding: 24, textAlign: "center" }}>
      {error ? (
        <>
          <h1>Login Azure AD Gagal</h1>
          <p style={{ color: "#d32f2f", fontSize: 14 }}>{error}</p>
          <Link href="/login">← Kembali ke halaman login</Link>
        </>
      ) : (
        <>
          <h1>Menyelesaikan Login...</h1>
          <p style={{ color: "#666", fontSize: 14 }}>Memverifikasi identitas Azure AD Anda, mohon tunggu.</p>
        </>
      )}
    </div>
  );
}
