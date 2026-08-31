"use client";
// Pengaturan profil — identitas akun (read-only, karena role/divisi hanya
// boleh diubah IT Admin lewat Kelola User) + ganti password di satu tempat.

import { useShell } from "../../components/ShellContext";
import ChangePasswordForm from "../../components/ChangePasswordForm";

const ROLE_LABEL = {
  it_admin: "IT Admin",
  designer: "Designer",
  mlops: "MLOps",
  consumer_internal: "Consumer Internal BEI",
  consumer_eipo: "Consumer Internet (E-IPO)",
  business_user_designer: "Business User Designer",
  compliance: "Compliance User",
  auditor: "Auditor View",
};

function Card({ title, description, children }) {
  return (
    <div style={{ border: "1px solid var(--idx-border)", borderRadius: 8, padding: 20, marginBottom: 20, background: "var(--idx-surface)" }}>
      <b style={{ color: "var(--idx-text)" }}>{title}</b>
      {description && (
        <p style={{ margin: "4px 0 16px", fontSize: 13, color: "var(--idx-text-muted)" }}>{description}</p>
      )}
      {children}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div style={{ display: "flex", padding: "9px 0", borderBottom: "1px solid var(--idx-border-light)", fontSize: 13.5 }}>
      <span style={{ width: 150, color: "var(--idx-text-muted)", flexShrink: 0 }}>{label}</span>
      <span style={{ color: "var(--idx-text)", fontWeight: 500 }}>{value}</span>
    </div>
  );
}

export default function ProfilePage() {
  const { currentUser } = useShell();

  if (!currentUser) {
    return <div style={{ padding: 32, color: "var(--idx-text-subtle)" }}>Memuat...</div>;
  }

  return (
    <div style={{ padding: "24px 32px", maxWidth: 640, margin: "0 auto" }}>
      <h1 style={{ fontSize: 22 }}>Pengaturan Profil</h1>

      <div style={{ display: "flex", alignItems: "center", gap: 14, margin: "20px 0 24px" }}>
        <span style={{
          width: 52, height: 52, borderRadius: "50%", background: "var(--idx-red)", color: "#fff",
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, fontWeight: 700,
        }}>
          {(currentUser.full_name || currentUser.email).charAt(0).toUpperCase()}
        </span>
        <div>
          <div style={{ fontSize: 17, fontWeight: 700, color: "var(--idx-text)" }}>
            {currentUser.full_name || "(nama belum diisi)"}
          </div>
          <div style={{ fontSize: 13, color: "var(--idx-text-muted)" }}>{currentUser.email}</div>
        </div>
      </div>

      <Card
        title="Identitas Akun"
        description="Role dan divisi hanya bisa diubah oleh IT Admin melalui halaman Kelola User, jadi ditampilkan sebagai informasi saja di sini."
      >
        <Row label="Email" value={currentUser.email} />
        <Row label="Nama Lengkap" value={currentUser.full_name || "—"} />
        <Row label="Role" value={ROLE_LABEL[currentUser.role] || currentUser.role} />
        <Row
          label="Divisi"
          value={currentUser.divisi || (currentUser.role === "it_admin" ? "— (Admin Global)" : "—")}
        />
      </Card>

      <Card
        title="Ganti Password"
        description="Password baru harus minimal 12 karakter dan mengandung huruf besar, huruf kecil, angka, serta karakter khusus."
      >
        <ChangePasswordForm />
      </Card>
    </div>
  );
}
