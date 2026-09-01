"use client";
// [PENANGGUNG JAWAB: Anggota B]
// Multi-Tenant Knowledge Base — SRS poin 11 & hal. 68/70. Admin GLOBAL
// (currentUser.divisi kosong) bisa upload ke divisi mana pun atau Company
// Wide; admin DIVISI (currentUser.divisi terisi) cuma bisa upload/hapus
// dokumen divisinya sendiri (backend jadi penegak sesungguhnya lewat
// kb/routes.py _assert_can_manage — halaman ini cuma sembunyikan UI-nya).

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "../../../../lib/api";
import FileInput from "../../../components/FileInput";

const ALL_DIVISI = ["WAS", "PLP", "PPT", "PP1", "PP2", "PP3", "PTI", "SDI", "OTP"];

export default function KbAdminPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [docs, setDocs] = useState([]);
  const [uploadDivisi, setUploadDivisi] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!api.isLoggedIn()) {
      router.push("/login");
      return;
    }
    api.getMe()
      .then((user) => {
        setCurrentUser(user);
        setCheckingSession(false);
        if (user.divisi) setUploadDivisi(user.divisi); // admin divisi: target upload terkunci ke divisinya
      })
      .catch(() => {
        api.logout();
        router.push("/login");
      });
  }, []);

  const hasAccess = currentUser && currentUser.role === "it_admin";
  const isGlobalAdmin = currentUser && !currentUser.divisi;

  const loadDocs = useCallback(async () => {
    try {
      const result = await api.listKbDocuments();
      setDocs(result);
    } catch (err) {
      setError(err.message || "Gagal memuat daftar dokumen");
    }
  }, []);

  useEffect(() => {
    if (hasAccess) loadDocs();
  }, [hasAccess, loadDocs]);

  async function handleUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      await api.uploadKbDocument(file, uploadDivisi || null);
      await loadDocs();
    } catch (err) {
      setError(err.message || "Gagal mengunggah dokumen");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function handleDelete(id) {
    try {
      await api.deleteKbDocument(id);
      setDocs((prev) => prev.filter((d) => d.id !== id));
    } catch (err) {
      setError(err.message || "Gagal menghapus dokumen");
    }
  }

  if (checkingSession) return <div style={{ padding: 40 }}>Memuat...</div>;

  if (!hasAccess) {
    return (
      <div style={{ padding: 40, maxWidth: 600, margin: "0 auto", textAlign: "center" }}>
        <h1>Akses Ditolak</h1>
        <p style={{ color: "var(--idx-text-muted)" }}>Halaman ini hanya untuk role IT Admin.</p>
        <Link href="/chat">Kembali ke Chat</Link>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px 40px", maxWidth: 900, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h1 className="page-title" style={{ margin: 0 }}>Knowledge Base Divisi</h1>
      </div>
      <p style={{ color: "var(--idx-text-muted)", fontSize: 13, marginTop: 0, marginBottom: 16 }}>
        Dokumen di sini ditarik sebagai konteks jawaban AI cuma untuk user divisi yang sama (+ dokumen Company Wide,
        bisa diakses semua divisi).
      </p>

      {error && <p style={{ color: "var(--idx-danger)" }}>{error}</p>}

      <div style={{ border: "1px solid var(--idx-border)", borderRadius: 8, padding: 16, marginBottom: 20, background: "var(--idx-surface)" }}>
        <label className="card-label">Upload Dokumen PDF</label>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
          <span style={{ fontSize: 13 }}>Target:</span>
          {isGlobalAdmin ? (
            <select value={uploadDivisi} onChange={(e) => setUploadDivisi(e.target.value)} style={{ padding: 6 }}>
              <option value="">Company Wide (semua divisi)</option>
              {ALL_DIVISI.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          ) : (
            <b>{currentUser.divisi}</b>
          )}
        </div>
        <FileInput onChange={handleUpload} disabled={uploading} label="Pilih Berkas PDF" />
        {uploading && <p style={{ fontSize: 13, color: "var(--idx-text-muted)" }}>Mengekstrak & mengindeks...</p>}
      </div>

      <div style={{ border: "1px solid var(--idx-border)", borderRadius: 8, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--idx-surface-alt)", textAlign: "left" }}>
              <th style={{ padding: 10 }}>Nama File</th>
              <th style={{ padding: 10 }}>Divisi</th>
              <th style={{ padding: 10 }}>Jumlah Chunk</th>
              <th style={{ padding: 10 }}>Diunggah</th>
              <th style={{ padding: 10 }}></th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => {
              // Admin divisi cuma boleh hapus dokumen divisinya sendiri —
              // dokumen Company Wide/divisi lain di daftar ini read-only
              // buat dia (backend akan 403 kalau dipaksa lewat API langsung).
              const canDelete = isGlobalAdmin || d.divisi === currentUser.divisi;
              return (
                <tr key={d.id} style={{ borderTop: "1px solid var(--idx-border-light)" }}>
                  <td style={{ padding: 10 }}>{d.filename}</td>
                  <td style={{ padding: 10 }}>{d.divisi || "Company Wide"}</td>
                  <td style={{ padding: 10 }}>{d.chunk_count}</td>
                  <td style={{ padding: 10 }}>{new Date(d.created_at.endsWith("Z") ? d.created_at : d.created_at + "Z").toLocaleString()}</td>
                  <td style={{ padding: 10 }}>
                    {canDelete && (
                      <button
                        onClick={() => handleDelete(d.id)}
                        style={{ background: "transparent", border: "none", color: "var(--idx-danger)", cursor: "pointer" }}
                      >
                        Hapus
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {docs.length === 0 && (
              <tr><td colSpan={5} style={{ padding: 20, textAlign: "center", color: "var(--idx-text-subtle)" }}>Belum ada dokumen.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
