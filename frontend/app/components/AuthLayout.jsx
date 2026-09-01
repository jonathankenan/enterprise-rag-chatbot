"use client";
// Kerangka halaman login & daftar: ilustrasi di kiri, kartu form di kanan.
// Di layar sempit ilustrasi disembunyikan supaya formnya tetap lega.

import { useState } from "react";
import { IconEye } from "./Icons";

export function AuthShell({ children }) {
  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      gap: 40, padding: "40px 24px", background: "var(--idx-bg)",
    }}>
      <img
        src="/loginidx.png"
        alt=""
        className="auth-illustration"
        style={{ width: "min(46vw, 560px)", maxHeight: "70vh", objectFit: "contain", flexShrink: 1 }}
      />
      <div style={{
        width: "100%", maxWidth: 460, flexShrink: 0,
        border: "1px solid var(--idx-border)", borderRadius: 14,
        padding: "38px 36px", boxShadow: "0 6px 28px rgba(0,0,0,0.06)",
      }}>
        {children}
      </div>
    </div>
  );
}

export function AuthTitle({ children, sub }) {
  return (
    <div style={{ textAlign: "center", marginBottom: 26 }}>
      {/* border:none — h1 global punya garis merah bawah yang tidak cocok di sini */}
      <h1 style={{ fontSize: 32, margin: 0, border: "none", padding: 0, display: "block", color: "var(--idx-text-muted)" }}>
        {children}
      </h1>
      {sub && <p style={{ margin: "10px 0 0", fontSize: 14, color: "var(--idx-text-muted)" }}>{sub}</p>}
    </div>
  );
}

const fieldWrap = {
  display: "flex", alignItems: "center", gap: 10,
  background: "var(--idx-surface-alt)", borderRadius: 8,
  padding: "0 14px", marginBottom: 14,
};
const bareInput = {
  flex: 1, minWidth: 0, border: "none", background: "transparent",
  padding: "14px 0", fontSize: 14.5, outline: "none", boxShadow: "none",
};

export function AuthField({ icon, ...props }) {
  return (
    <div style={fieldWrap}>
      <span style={{ color: "var(--idx-text-subtle)", display: "flex" }}>{icon}</span>
      <input {...props} style={bareInput} />
    </div>
  );
}

export function AuthPasswordField({ icon, ...props }) {
  const [show, setShow] = useState(false);
  return (
    <div style={fieldWrap}>
      <span style={{ color: "var(--idx-text-subtle)", display: "flex" }}>{icon}</span>
      <input {...props} type={show ? "text" : "password"} style={bareInput} />
      <button
        type="button"
        onClick={() => setShow((v) => !v)}
        aria-label={show ? "Sembunyikan password" : "Tampilkan password"}
        style={{ background: "transparent", border: "none", padding: 0, color: "var(--idx-text-subtle)", display: "flex", cursor: "pointer" }}
      >
        <IconEye off={show} />
      </button>
    </div>
  );
}

export function AuthSubmit({ children, ...props }) {
  return (
    <button
      type="submit"
      {...props}
      style={{
        width: "100%", padding: "14px 0", marginTop: 6,
        background: "var(--idx-red-soft)", color: "#fff",
        border: "none", borderRadius: 8, fontSize: 15, fontWeight: 600,
      }}
    >
      {children}
    </button>
  );
}
