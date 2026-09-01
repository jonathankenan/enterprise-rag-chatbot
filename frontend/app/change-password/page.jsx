"use client";
// Halaman ganti password PAKSA (SRS ISR-002.c: umur password > 90 hari).
// Sengaja DI LUAR shell aplikasi — di alur ini user belum boleh masuk ke
// navigasi utama sampai passwordnya diganti. Untuk ganti password sukarela,
// tempatnya di /profile yang memakai form yang sama persis.

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Suspense } from "react";
import { api } from "../../lib/api";
import ChangePasswordForm from "../components/ChangePasswordForm";

function ChangePasswordInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const forcedByExpiry = searchParams.get("expired") === "true";
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!api.isLoggedIn()) router.push("/login");
  }, []);

  return (
    <div style={{ maxWidth: 380, margin: "80px auto", padding: 24 }}>
      <h1 style={{ fontSize: 22 }}>Ganti Password</h1>
      {forcedByExpiry && (
        <p style={{ background: "var(--idx-warning-tint)", border: "1px solid var(--idx-warning-border)", padding: 10, borderRadius: 4, fontSize: 13, color: "var(--idx-warning)", marginTop: 16 }}>
          Password Anda sudah berumur lebih dari 90 hari dan wajib diganti sebelum melanjutkan.
        </p>
      )}
      <div style={{ marginTop: 16 }}>
        <ChangePasswordForm onSuccess={() => setDone(true)} />
      </div>
      {done && (
        <p style={{ marginTop: 16, fontSize: 14 }}>
          <Link href="/chat">Lanjut ke aplikasi →</Link>
        </p>
      )}
    </div>
  );
}

export default function ChangePasswordPage() {
  return (
    <Suspense fallback={<div style={{ padding: 40 }}>Memuat...</div>}>
      <ChangePasswordInner />
    </Suspense>
  );
}
