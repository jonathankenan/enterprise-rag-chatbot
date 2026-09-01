"use client";
// Pengganti <input type="file"> bawaan browser.
//
// Kontrol bawaan tidak bisa ditata (tombol "Choose File" tampilannya
// ditentukan OS, bukan CSS), jadi input aslinya disembunyikan dan yang
// terlihat adalah <label> bergaya tombol — klik pada label tetap membuka
// dialog berkas seperti biasa, tanpa JavaScript tambahan.

import { useId, useState } from "react";

export default function FileInput({
  accept = "application/pdf",
  onChange,
  disabled,
  label = "Pilih Berkas",
  hint,
}) {
  const id = useId();
  const [fileName, setFileName] = useState("");

  function handleChange(e) {
    setFileName(e.target.files?.[0]?.name || "");
    onChange(e);
    // Reset supaya memilih berkas yang SAMA dua kali tetap memicu onChange.
    e.target.value = "";
  }

  return (
    <div>
      <input id={id} type="file" accept={accept} onChange={handleChange} disabled={disabled} style={{ display: "none" }} />
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        {/* Warna & hover sepenuhnya dari kelas btn-outline. Dulu background
            dan color ditulis inline, sehingga hover CSS hanya berhasil
            mengubah warna teks jadi putih tapi TIDAK backgroundnya (inline
            style menang) — hasilnya tulisan putih di atas putih. */}
        <label htmlFor={id} className={`btn-outline${disabled ? " is-disabled" : ""}`} style={{ fontSize: 13 }}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <path d="M17 8l-5-5-5 5" />
            <path d="M12 3v12" />
          </svg>
          {disabled ? "Mengunggah..." : label}
        </label>
        <span style={{ fontSize: 12.5, color: fileName ? "var(--idx-text-body)" : "var(--idx-text-subtle)" }}>
          {fileName || "Belum ada berkas dipilih"}
        </span>
      </div>
      {hint && (
        <p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--idx-text-subtle)" }}>{hint}</p>
      )}
    </div>
  );
}
