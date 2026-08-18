"use client";
// [PENANGGUNG JAWAB: Anggota B]
// Halaman audit log — SRS ISR-004: GUI audit trail untuk role terotorisasi
// (IT Admin, Compliance, Auditor). Pembatasan SESUNGGUHNYA ada di backend
// (require_role() di guardrail/routes.py, balas 403 kalau role tidak cocok)
// — pengecekan role di sini CUMA untuk UX (sembunyikan menu & tampilkan
// pesan yang jelas), BUKAN mekanisme keamanan. Backend tetap jadi penjaga
// sesungguhnya walau seseorang memaksa buka halaman ini lewat URL langsung.

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "../../lib/api";

// Samakan dengan Role.AUDIT_VIEWERS di backend/app/models.py
const AUDIT_VIEWER_ROLES = ["it_admin", "compliance", "auditor"];

const EVENT_TYPES = [
  "prompt_blocked", "injection_blocked", "pii_detected", "output_blocked",
  "document_blocked", "rate_limit_hit", "login_failed", "login_success",
  "chat_created", "chat_deleted", "document_uploaded", "chat_exported",
  "user_registered", "password_changed", "helpdesk_escalated", "user_role_changed",
];

const SEVERITY_COLORS = {
  low: "#2e7d32",
  medium: "#ed6c02",
  high: "#d32f2f",
  critical: "#b71c1c",
};

function parseDetail(raw) {
  // detail disimpan sebagai JSON string: {"message": "...", "metadata": {...}}
  try {
    const parsed = JSON.parse(raw);
    return parsed;
  } catch {
    return { message: raw };
  }
}

export default function AuditPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState(null); // GET /api/audit/summary

  const [filters, setFilters] = useState({
    event_type: "",
    severity: "",
    q: "",
    since: "",
    until: "",
    sort_by: "created_at",
    sort_order: "desc",
    limit: 100,
  });

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

  const hasAccess = currentUser && AUDIT_VIEWER_ROLES.includes(currentUser.role);

  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = { ...filters };
      if (params.since) params.since = new Date(params.since).toISOString();
      if (params.until) params.until = new Date(params.until).toISOString();
      const result = await api.searchAudit(params);
      setEvents(result);
    } catch (err) {
      setError(err.message || "Gagal memuat audit log");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    if (hasAccess) {
      api.getAuditSummary(24).then(setSummary).catch(() => {});
    }
  }, [hasAccess]);

  useEffect(() => {
    if (hasAccess) loadEvents();
  }, [hasAccess]);

  function updateFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  async function handleExport() {
    try {
      const params = { ...filters };
      delete params.limit;
      delete params.sort_by;
      delete params.sort_order;
      if (params.since) params.since = new Date(params.since).toISOString();
      if (params.until) params.until = new Date(params.until).toISOString();
      const blob = await api.exportAuditCsv(params);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit_log_export_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || "Gagal export CSV");
    }
  }

  if (checkingSession) {
    return <div style={{ padding: 40 }}>Memuat...</div>;
  }

  if (!hasAccess) {
    return (
      <div style={{ padding: 40, maxWidth: 600, margin: "0 auto", textAlign: "center" }}>
        <h1>Akses Ditolak</h1>
        <p style={{ color: "#666" }}>
          Halaman ini hanya untuk role IT Admin, Compliance, atau Auditor.
          Akun Anda ({currentUser?.email}) punya role <b>{currentUser?.role}</b>,
          yang tidak termasuk kategori tersebut.
        </p>
        <Link href="/chat">Kembali ke Chat</Link>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px 40px", maxWidth: 1100, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div>
          <h1 style={{ margin: 0 }}>Audit Log</h1>
          <p style={{ margin: "4px 0 0", color: "#666", fontSize: 13 }}>
            Login sebagai {currentUser.email} ({currentUser.role})
          </p>
        </div>
        <Link href="/chat">← Kembali ke Chat</Link>
      </div>

      {/* Ringkasan 24 jam terakhir — GET /api/audit/summary */}
      {summary && Object.keys(summary.counts_by_type).length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 16 }}>
          {Object.entries(summary.counts_by_type)
            .sort((a, b) => b[1] - a[1])
            .map(([type, count]) => (
              <div key={type} style={{ padding: "8px 14px", background: "white", border: "1px solid #ddd", borderRadius: 8, fontSize: 13 }}>
                <b style={{ fontSize: 18 }}>{count}</b> {type} <span style={{ color: "#888" }}>({summary.since_hours}j terakhir)</span>
              </div>
            ))}
        </div>
      )}

      {/* ---------- Filter & Search (SRS ISR-004.d) ---------- */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 16, padding: 16, background: "#f9f9f9", borderRadius: 8, border: "1px solid #ddd" }}>
        <select value={filters.event_type} onChange={(e) => updateFilter("event_type", e.target.value)} style={{ padding: 8 }}>
          <option value="">Semua jenis event</option>
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>

        <select value={filters.severity} onChange={(e) => updateFilter("severity", e.target.value)} style={{ padding: 8 }}>
          <option value="">Semua severity</option>
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
          <option value="critical">critical</option>
        </select>

        <input
          type="text"
          placeholder="Cari teks di detail..."
          value={filters.q}
          onChange={(e) => updateFilter("q", e.target.value)}
          style={{ padding: 8, flex: 1, minWidth: 160 }}
        />

        <input type="datetime-local" value={filters.since} onChange={(e) => updateFilter("since", e.target.value)} style={{ padding: 8 }} title="Sejak" />
        <input type="datetime-local" value={filters.until} onChange={(e) => updateFilter("until", e.target.value)} style={{ padding: 8 }} title="Sampai" />

        <select value={filters.sort_by} onChange={(e) => updateFilter("sort_by", e.target.value)} style={{ padding: 8 }}>
          <option value="created_at">Urutkan: Waktu</option>
          <option value="severity">Urutkan: Severity</option>
          <option value="event_type">Urutkan: Jenis Event</option>
        </select>
        <select value={filters.sort_order} onChange={(e) => updateFilter("sort_order", e.target.value)} style={{ padding: 8 }}>
          <option value="desc">Menurun</option>
          <option value="asc">Menaik</option>
        </select>

        <button onClick={loadEvents} disabled={loading} style={{ padding: "8px 16px", background: "#0070f3", color: "white", border: "none", borderRadius: 4, cursor: "pointer" }}>
          {loading ? "Memuat..." : "Terapkan"}
        </button>
        <button onClick={handleExport} style={{ padding: "8px 16px", background: "#28a745", color: "white", border: "none", borderRadius: 4, cursor: "pointer" }}>
          ⬇ Export CSV
        </button>
      </div>

      {error && <p style={{ color: "#d32f2f" }}>{error}</p>}

      {/* ---------- Tabel hasil ---------- */}
      <div style={{ border: "1px solid #ddd", borderRadius: 8, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f1f1f1", textAlign: "left" }}>
              <th style={{ padding: 10 }}>Waktu</th>
              <th style={{ padding: 10 }}>Akun</th>
              <th style={{ padding: 10 }}>Jenis Event</th>
              <th style={{ padding: 10 }}>Severity</th>
              <th style={{ padding: 10 }}>Detail</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => {
              const detail = parseDetail(e.detail);
              return (
                <tr key={e.id} style={{ borderTop: "1px solid #eee" }}>
                  <td style={{ padding: 10, whiteSpace: "nowrap" }}>
                    {new Date(e.created_at.endsWith("Z") ? e.created_at : e.created_at + "Z").toLocaleString()}
                  </td>
                  <td style={{ padding: 10, fontFamily: "monospace", fontSize: 11 }}>{e.user_id ? e.user_id.slice(0, 8) : "-"}</td>
                  <td style={{ padding: 10 }}>{e.event_type}</td>
                  <td style={{ padding: 10 }}>
                    <span style={{ color: SEVERITY_COLORS[e.severity] || "#666", fontWeight: "bold" }}>{e.severity}</span>
                  </td>
                  <td style={{ padding: 10, maxWidth: 400, wordBreak: "break-word" }}>
                    {detail.message}
                    {detail.metadata && (
                      <div style={{ color: "#888", fontSize: 11, marginTop: 2 }}>
                        {JSON.stringify(detail.metadata)}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
            {events.length === 0 && !loading && (
              <tr>
                <td colSpan={5} style={{ padding: 20, textAlign: "center", color: "#888" }}>
                  Tidak ada kejadian yang cocok dengan filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
