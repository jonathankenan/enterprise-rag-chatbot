"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "../../lib/api";
import { getPasswordError } from "../../lib/validation";
import { AuthShell, AuthTitle, AuthField, AuthPasswordField, AuthSubmit } from "../components/AuthLayout";
import { IconMail, IconLock } from "../components/Icons";

// Semua role KECUALI IT Admin — samakan dengan Role.SELF_REGISTERABLE di
// backend/app/models.py, yang juga menolak it_admin kalau dipaksa lewat API.
const SELF_ROLES = [
  { value: "designer", label: "Designer" },
  { value: "mlops", label: "MLOps" },
  { value: "consumer_internal", label: "Consumer Internal BEI" },
  { value: "consumer_eipo", label: "Consumer Internet (E-IPO)" },
  { value: "business_user_designer", label: "Business User Designer" },
  { value: "compliance", label: "Compliance User" },
  { value: "auditor", label: "Auditor View" },
];

// Samakan dengan Divisi.ALL di backend/app/models.py
const DIVISI = ["WAS", "PLP", "PPT", "PP1", "PP2", "PP3", "PTI", "SDI", "OTP"];

const selectWrap = { background: "var(--idx-surface-alt)", borderRadius: 8, padding: "0 14px", marginBottom: 14 };
const bareSelect = { width: "100%", border: "none", background: "transparent", padding: "14px 0", fontSize: 14.5, outline: "none", boxShadow: "none" };

export default function RegisterPage() {
  const router = useRouter();
  const [role, setRole] = useState("");
  const [divisi, setDivisi] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleRegister(e) {
    e.preventDefault();
    setError("");

    if (!role) {
      setError("Silakan pilih role terlebih dahulu");
      return;
    }
    // Divisi wajib: eskalasi helpdesk diarahkan ke IT Admin divisi, jadi akun
    // tanpa divisi tidak akan bisa menghubungi admin sama sekali.
    if (!divisi) {
      setError("Silakan pilih divisi terlebih dahulu");
      return;
    }
    const passwordError = getPasswordError(password);
    if (passwordError) {
      setError(passwordError);
      return;
    }
    if (password !== confirmPassword) {
      setError("Konfirmasi password tidak cocok");
      return;
    }
    if (!agreed) {
      setError("Anda harus menyetujui Syarat dan Ketentuan");
      return;
    }

    setLoading(true);
    try {
      await api.register(email, password, null, role, divisi);
      router.push("/login?registered=true");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell>
      <AuthTitle sub={<>Sudah punya akun? <Link href="/login">Masuk</Link></>}>
        Daftar Akun Baru
      </AuthTitle>

      <form onSubmit={handleRegister}>
        <div style={selectWrap}>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            required
            style={{ ...bareSelect, color: role ? "var(--idx-text-body)" : "var(--idx-text-subtle)" }}
          >
            <option value="">Pilih Role</option>
            {SELF_ROLES.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
        </div>

        <div style={selectWrap}>
          <select
            value={divisi}
            onChange={(e) => setDivisi(e.target.value)}
            required
            style={{ ...bareSelect, color: divisi ? "var(--idx-text-body)" : "var(--idx-text-subtle)" }}
          >
            <option value="">Pilih Divisi</option>
            {DIVISI.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>

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
        <p style={{ fontSize: 12.5, color: "var(--idx-text-muted)", margin: "-6px 0 14px", lineHeight: 1.55 }}>
          Ketentuan : minimal 12 karakter. Mengandung huruf besar, huruf kecil,
          angka, dan simbol (*&amp;^%$#@!, dan lain-lain)
        </p>

        <AuthPasswordField
          icon={<IconLock />}
          placeholder="Konfirmasi Password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          required
        />

        <label style={{ display: "flex", alignItems: "flex-start", gap: 10, fontSize: 13.5, color: "var(--idx-text-body)", margin: "6px 0 4px", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            style={{ marginTop: 3, width: 16, height: 16, flexShrink: 0 }}
          />
          <span>
            Saya telah membaca dan menyetujui{" "}
            <a href="https://www.idx.co.id/id/syarat-dan-ketentuan" target="_blank" rel="noopener noreferrer">
              Syarat dan Ketentuan
            </a>{" "}
            IDX Website
          </span>
        </label>

        {error && <p style={{ color: "var(--idx-danger)", fontSize: 13 }}>{error}</p>}
        <AuthSubmit disabled={loading}>{loading ? "Memproses..." : "Daftar"}</AuthSubmit>
      </form>
    </AuthShell>
  );
}
