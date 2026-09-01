"use client";
// Pengganti window.alert() / window.confirm() bawaan browser.
//
// Dialog bawaan menampilkan judul "localhost:3000 says", memblokir seluruh
// tab, dan tidak bisa ditata mengikuti tema IDX. Hook di bawah menyediakan
// API yang sama enaknya (await konfirmasi()) tapi merender modal sendiri.

import { createContext, useCallback, useContext, useRef, useState } from "react";

const DialogContext = createContext({
  alert: async () => {},
  confirm: async () => false,
});

export const useDialog = () => useContext(DialogContext);

export function DialogProvider({ children }) {
  const [dialog, setDialog] = useState(null);
  const resolverRef = useRef(null);

  const open = useCallback((config) => {
    // Promise-nya di-resolve oleh tombol di modal — inilah yang bikin
    // pemanggilnya bisa `await`, sama seperti confirm() bawaan.
    return new Promise((resolve) => {
      resolverRef.current = resolve;
      setDialog(config);
    });
  }, []);

  const finish = useCallback((value) => {
    setDialog(null);
    resolverRef.current?.(value);
    resolverRef.current = null;
  }, []);

  const api = {
    alert: (message, { title = "Pemberitahuan" } = {}) => open({ kind: "alert", title, message }),
    confirm: (message, { title = "Konfirmasi", confirmLabel = "Ya, lanjutkan", danger = false } = {}) =>
      open({ kind: "confirm", title, message, confirmLabel, danger }),
  };

  return (
    <DialogContext.Provider value={api}>
      {children}
      {dialog && (
        <div
          onClick={() => finish(dialog.kind === "confirm" ? false : undefined)}
          style={{
            position: "fixed", inset: 0, zIndex: 200, background: "rgba(0,0,0,0.38)",
            display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
            className="page-enter"
            style={{
              width: "100%", maxWidth: 420, background: "var(--idx-bg)",
              borderRadius: 12, padding: "22px 24px 20px",
              boxShadow: "0 16px 48px rgba(0,0,0,0.22)",
              borderTop: `4px solid ${dialog.danger ? "var(--idx-danger)" : "var(--idx-red)"}`,
            }}
          >
            <b style={{ fontSize: 15.5, color: "var(--idx-text)" }}>{dialog.title}</b>
            <p style={{ margin: "10px 0 22px", fontSize: 13.5, color: "var(--idx-text-body)", lineHeight: 1.6 }}>
              {dialog.message}
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              {dialog.kind === "confirm" && (
                <button
                  onClick={() => finish(false)}
                  style={{
                    padding: "8px 16px", background: "transparent", color: "var(--idx-text-body)",
                    border: "1px solid var(--idx-border-strong)", borderRadius: 4, fontWeight: 600,
                  }}
                >
                  Batal
                </button>
              )}
              <button
                autoFocus
                onClick={() => finish(dialog.kind === "confirm" ? true : undefined)}
                style={
                  dialog.danger
                    ? { padding: "8px 16px", background: "var(--idx-danger)", color: "#fff", border: "none", borderRadius: 4, fontWeight: 600 }
                    : { padding: "8px 16px" }
                }
              >
                {dialog.kind === "confirm" ? dialog.confirmLabel : "Mengerti"}
              </button>
            </div>
          </div>
        </div>
      )}
    </DialogContext.Provider>
  );
}
