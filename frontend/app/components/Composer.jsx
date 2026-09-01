"use client";
// Input bar gaya Gemini: tombol "+" di kiri (lampiran), dropdown model di
// kanan, tombol kirim paling kanan yang baru aktif setelah ada teks.
// Dipakai dua tempat: chat AI (lampiran = upload PDF) dan chat admin
// (lampiran = mencantumkan percakapan AI).

import { useState, useRef, useEffect } from "react";

export default function Composer({
  value,
  onChange,
  onSubmit,
  disabled,
  placeholder = "Ketik pertanyaan...",
  // Menu "+": daftar { label, onSelect } — isinya beda antara chat AI & chat admin
  plusMenu = [],
  // Dropdown model (opsional — chat admin tidak memilih model)
  models,
  model,
  onModelChange,
  // Chip lampiran yang sedang terpasang (opsional)
  attachment,
  onClearAttachment,
}) {
  const [plusOpen, setPlusOpen] = useState(false);
  const wrapRef = useRef(null);
  const canSend = value.trim().length > 0 && !disabled;

  useEffect(() => {
    if (!plusOpen) return;
    const close = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setPlusOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [plusOpen]);

  return (
    <form onSubmit={onSubmit} style={{ width: "100%" }}>
      {attachment && (
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 8, marginBottom: 8,
          padding: "5px 10px", borderRadius: 999, fontSize: 12.5,
          background: "var(--idx-red-tint)", color: "var(--idx-red)", border: "1px solid var(--idx-danger-border)",
        }}>
          {attachment}
          <button
            type="button"
            onClick={onClearAttachment}
            style={{ background: "transparent", border: "none", color: "var(--idx-red)", cursor: "pointer", fontSize: 14, padding: 0, lineHeight: 1 }}
            aria-label="Hapus lampiran"
          >
            ✕
          </button>
        </div>
      )}

      <div
        ref={wrapRef}
        style={{
          position: "relative", display: "flex", alignItems: "center", gap: 8,
          padding: "6px 8px 6px 6px", borderRadius: 999,
          border: "1px solid var(--idx-border-strong)", background: "var(--idx-bg)",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
        }}
      >
        {plusMenu.length > 0 && (
          <>
            <button
              type="button"
              onClick={() => setPlusOpen((v) => !v)}
              title="Lampirkan"
              aria-label="Lampirkan"
              style={{
                width: 34, height: 34, flexShrink: 0, borderRadius: "50%",
                border: "none", background: "transparent", color: "var(--idx-text-muted)",
                fontSize: 20, lineHeight: 1, cursor: "pointer", padding: 0,
              }}
            >
              +
            </button>
            {plusOpen && (
              <div className="popup-menu" style={{ bottom: "100%", left: 0, marginBottom: 8 }}>
                {plusMenu.map((item) => (
                  <button
                    key={item.label}
                    type="button"
                    className="popup-item"
                    onClick={() => { setPlusOpen(false); item.onSelect(); }}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            // Enter dipasang eksplisit, tidak mengandalkan implicit form
            // submission — perilaku itu tidak konsisten begitu form berisi
            // tombol/kontrol lain seperti dropdown model di sebelah kanan.
            if (e.key === "Enter" && !e.shiftKey && canSend) {
              e.preventDefault();
              onSubmit(e);
            }
          }}
          placeholder={placeholder}
          style={{ flex: 1, minWidth: 0, border: "none", outline: "none", background: "transparent", padding: "8px 4px", fontSize: 14, boxShadow: "none" }}
        />

        {models && (
          <select
            value={model}
            onChange={(e) => onModelChange(e.target.value)}
            title="Pilih model AI"
            style={{ border: "none", background: "transparent", fontSize: 12.5, color: "var(--idx-text-muted)", cursor: "pointer", maxWidth: 150, boxShadow: "none" }}
          >
            {models.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        )}

        <button
          type="submit"
          disabled={!canSend}
          title="Kirim"
          aria-label="Kirim"
          style={{
            width: 34, height: 34, flexShrink: 0, borderRadius: "50%", padding: 0,
            border: "none", cursor: canSend ? "pointer" : "not-allowed",
            background: canSend ? "var(--idx-red)" : "var(--idx-border)",
            color: canSend ? "#fff" : "var(--idx-text-subtle)",
            display: "flex", alignItems: "center", justifyContent: "center",
            transition: "background 0.15s ease",
          }}
        >
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 19V5M12 5l-6 6M12 5l6 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
    </form>
  );
}
