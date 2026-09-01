"use client";
// Logo aplikasi. Memakai /logo.png dari folder `public/`; kalau berkas itu
// hilang, otomatis jatuh ke lambang SVG bawaan supaya sidebar tidak
// menampilkan gambar rusak.
//
// CATATAN: latar logo.png putih SOLID (bukan transparan), jadi sidebar
// sengaja dibuat putih juga di globals.css — kalau tidak, akan terlihat
// kotak putih yang menempel di sekeliling logo.

import { useState } from "react";

function FallbackMark({ size }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="var(--idx-red)" />
      <path d="M8 21.5 L13 15.5 L17.5 19 L24 10.5" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="24" cy="10.5" r="2.4" fill="#fff" />
    </svg>
  );
}

export default function IdxLogo({ size = 38, showText = true }) {
  const [broken, setBroken] = useState(false);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
      {broken ? (
        <FallbackMark size={size} />
      ) : (
        <img
          src="/logo.png"
          alt="IDX Catalyst"
          width={size}
          height={size}
          onError={() => setBroken(true)}
          style={{ objectFit: "contain", flexShrink: 0 }}
        />
      )}
      {showText && (
        <span style={{ fontSize: 18, fontWeight: 800, letterSpacing: "0.01em", color: "var(--idx-text)", whiteSpace: "nowrap" }}>
          IDX <span style={{ color: "var(--idx-red)" }}>CATALYST</span>
        </span>
      )}
    </div>
  );
}
