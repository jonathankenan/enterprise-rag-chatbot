"use client";
// [PENANGGUNG JAWAB: Anggota B]
// Kelola FAQ Helpdesk — SRS FCR-003 poin 10.b: FAQ jadi salah satu sumber
// RAG yang ditarik ke SEMUA chat (bukan cuma dokumen upload per-chat).
// Dibatasi Role.IT_ADMIN (backend jadi penegak sesungguhnya, halaman ini
// cuma sembunyikan UI-nya).

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "../../../lib/api";

export default function FaqAdminPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [faqs, setFaqs] = useState([]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);

  useEffect(() => {
    if (!api.isLoggedIn()) {
      router.push("/login");
      return;
    }
    api.getMe()
      .then((user) => {
        setCurrentUser(user);
        setCheckingSession(false);
      })
      .catch(() => {
        api.logout();
        router.push("/login");
      });
  }, []);

  const hasAccess = currentUser && currentUser.role === "it_admin";

  const loadFaqs = useCallback(async () => {
    try {
      const result = await api.listFaqs();
      setFaqs(result);
    } catch (err) {
      setError(err.message || "Gagal memuat daftar FAQ");
    }
  }, []);

  useEffect(() => {
    if (hasAccess) loadFaqs();
  }, [hasAccess, loadFaqs]);

  async function handleCreate(e) {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await api.createFaq(question, answer);
      setQuestion("");
      setAnswer("");
      await loadFaqs();
    } catch (err) {
      setError(err.message || "Gagal menambah FAQ");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleUploadPdf(e) {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setError("");
    setUploadResult(null);
    try {
      const result = await api.uploadFaqPdf(file);
      setUploadResult(result);
      await loadFaqs();
    } catch (err) {
      setError(err.message || "Gagal mengunggah PDF");
    } finally {
      setUploading(false);
      e.target.value = ""; // supaya file yang sama bisa dipilih ulang kalau perlu
    }
  }

  async function handleDelete(id) {
    try {
      await api.deleteFaq(id);
      setFaqs((prev) => prev.filter((f) => f.id !== id));
    } catch (err) {
      setError(err.message || "Gagal menghapus FAQ");
    }
  }

  if (checkingSession) return <div style={{ padding: 40 }}>Memuat...</div>;

  if (!hasAccess) {
    return (
      <div style={{ padding: 40, maxWidth: 600, margin: "0 auto", textAlign: "center" }}>
        <h1>Akses Ditolak</h1>
        <p style={{ color: "#666" }}>Halaman ini hanya untuk role IT Admin.</p>
        <Link href="/chat">Kembali ke Chat</Link>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px 40px", maxWidth: 900, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ margin: 0 }}>FAQ Helpdesk</h1>
        <Link href="/helpdesk">← Kembali ke Helpdesk</Link>
      </div>
      <p style={{ color: "#666", fontSize: 13, marginTop: -12 }}>
        Entri di sini otomatis ditarik sebagai konteks jawaban AI di SEMUA chat (SRS poin 10.b) — beda dari dokumen
        upload biasa yang cuma berlaku untuk satu percakapan.
      </p>

      {error && <p style={{ color: "#d32f2f" }}>{error}</p>}

      <form onSubmit={handleCreate} style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, marginBottom: 20, background: "#f9f9f9" }}>
        <div style={{ marginBottom: 10 }}>
          <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Pertanyaan</label>
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            required
            style={{ width: "100%", padding: 8, boxSizing: "border-box" }}
          />
        </div>
        <div style={{ marginBottom: 10 }}>
          <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Jawaban</label>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            required
            rows={3}
            style={{ width: "100%", padding: 8, boxSizing: "border-box", fontFamily: "inherit" }}
          />
        </div>
        <button
          type="submit"
          disabled={submitting}
          style={{ padding: "8px 16px", border: "none", borderRadius: 4, cursor: submitting ? "wait" : "pointer", background: "#0070f3", color: "white", fontWeight: "bold" }}
        >
          {submitting ? "Menyimpan..." : "+ Tambah FAQ"}
        </button>
      </form>

      <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, marginBottom: 20, background: "#f9f9f9" }}>
        <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
          Atau Import Banyak Sekaligus dari PDF
        </label>
        <p style={{ margin: "0 0 10px", fontSize: 12, color: "#666" }}>
          PDF berisi daftar tanya-jawab (format "Q: .../A: ...", "Pertanyaan: .../Jawaban: ...", atau baris
          pertanyaan diakhiri "?" diikuti jawabannya). Tiap pasangan yang ketemu jadi 1 FAQ terpisah.
        </p>
        <input type="file" accept="application/pdf" onChange={handleUploadPdf} disabled={uploading} />
        {uploading && <p style={{ fontSize: 13, color: "#666" }}>Mengekstrak & mengindeks...</p>}
        {uploadResult && (
          <p style={{ fontSize: 13, color: "#2e7d32", marginTop: 8 }}>
            ✅ {uploadResult.count} FAQ berhasil diimpor dari "{uploadResult.filename}".
          </p>
        )}
      </div>

      <div style={{ border: "1px solid #ddd", borderRadius: 8, overflow: "hidden" }}>
        {faqs.map((f) => (
          <div key={f.id} style={{ padding: 14, borderBottom: "1px solid #eee", display: "flex", justifyContent: "space-between", gap: 12 }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{f.question}</div>
              <div style={{ fontSize: 13, color: "#555", marginTop: 4 }}>{f.answer}</div>
            </div>
            <button
              onClick={() => handleDelete(f.id)}
              style={{ background: "transparent", border: "none", color: "#d32f2f", cursor: "pointer", fontSize: 13, whiteSpace: "nowrap" }}
            >
              Hapus
            </button>
          </div>
        ))}
        {faqs.length === 0 && (
          <div style={{ padding: 20, textAlign: "center", color: "#888", fontSize: 13 }}>Belum ada FAQ.</div>
        )}
      </div>
    </div>
  );
}
