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
import { api } from "../../../lib/api";

// Samakan dengan Role.AUDIT_VIEWERS di backend/app/models.py
const AUDIT_VIEWER_ROLES = ["it_admin", "compliance", "auditor"];

const SEVERITY_COLORS = {
  low: "var(--idx-success)",
  medium: "var(--idx-warning)",
  high: "var(--idx-danger)",
  critical: "var(--idx-danger)",
};

// Samakan dengan _SEVERITY_MAP di backend/app/guardrail/audit_log.py.
// Dipakai untuk aksen warna kartu ringkasan & daftar filter — sengaja satu
// sumber di frontend supaya keduanya tidak bisa diam-diam beda isi.
const EVENT_SEVERITY = {
  injection_blocked: "critical", commercial_llm_toggled: "critical",
  prompt_blocked: "high", output_blocked: "high", document_blocked: "high",
  rate_limit_hit: "high", user_role_changed: "high", user_divisi_changed: "high",
  pii_detected: "medium", helpdesk_escalated: "medium", export_roles_changed: "medium",
  helpdesk_ticket_deleted: "medium", rate_limit_config_changed: "medium",
  retention_policy_changed: "medium", retention_policy_applied: "medium",
  login_failed: "low", login_success: "low", chat_created: "low", chat_deleted: "low",
  chat_renamed: "low", chat_archived: "low", chat_unarchived: "low",
  document_uploaded: "low", chat_exported: "low", user_registered: "low",
  password_changed: "low", helpdesk_ticket_closed: "low",
  faq_created: "low", faq_deleted: "low",
  kb_document_uploaded: "low", kb_document_deleted: "low",
};

const EVENT_TYPES = Object.keys(EVENT_SEVERITY).sort();
const SEVERITY_BY_EVENT = Object.fromEntries(
  Object.entries(EVENT_SEVERITY).map(([type, sev]) => [type, SEVERITY_COLORS[sev]])
);

const fieldStyle = { width: "100%", padding: "8px 10px", fontSize: 13 };

const DEFAULT_FILTERS = {
  event_type: "", severity: "", q: "", since: "", until: "",
  sort_by: "created_at", sort_order: "desc", limit: 100,
};

function Field({ label, children }) {
  return (
    <label style={{ display: "block", minWidth: 0 }}>
      <span style={{ display: "block", fontSize: 11.5, fontWeight: 600, color: "var(--idx-text-muted)", marginBottom: 5 }}>
        {label}
      </span>
      {children}
    </label>
  );
}

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

  const [filters, setFilters] = useState(DEFAULT_FILTERS);

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
        <p style={{ color: "var(--idx-text-muted)" }}>
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
          <h1 className="page-title" style={{ margin: 0 }}>Audit Log</h1>
          <p style={{ margin: "10px 0 0", color: "var(--idx-text-muted)", fontSize: 13, maxWidth: 760 }}>
            Catatan seluruh aktivitas penting di sistem: percobaan login, pemblokiran konten,
            deteksi data pribadi, perubahan hak akses, dan pengaturan sistem. Gunakan filter di
            bawah untuk mempersempit pencarian, lalu <b>Export CSV</b> bila perlu dibawa ke laporan.
          </p>
        </div>
      </div>

      {/* Ringkasan 24 jam terakhir — GET /api/audit/summary.
          Grid seragam, bukan chip mengambang: jumlahnya bisa belasan dan
          panjang labelnya beda-beda, jadi ukuran tetap jauh lebih mudah
          dipindai. Keterangan "24j terakhir" ditulis SEKALI di judul, bukan
          diulang di tiap kartu. */}
      {summary && Object.keys(summary.counts_by_type).length > 0 && (
        <section style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 10 }}>
            <b style={{ fontSize: 13, color: "var(--idx-text)" }}>Ringkasan Aktivitas</b>
            <span style={{ fontSize: 12, color: "var(--idx-text-subtle)" }}>{summary.since_hours} jam terakhir</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 10 }}>
            {Object.entries(summary.counts_by_type)
              .sort((a, b) => b[1] - a[1])
              .map(([type, count]) => {
                const sev = SEVERITY_BY_EVENT[type];
                return (
                  <div
                    key={type}
                    style={{
                      padding: "12px 14px", background: "var(--idx-bg)",
                      border: "1px solid var(--idx-border)", borderRadius: 8,
                      borderLeft: `3px solid ${sev || "var(--idx-border-strong)"}`,
                    }}
                  >
                    <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1, color: "var(--idx-text)" }}>{count}</div>
                    <div style={{ fontSize: 12, color: "var(--idx-text-muted)", marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={type}>
                      {type.replace(/_/g, " ")}
                    </div>
                  </div>
                );
              })}
          </div>
        </section>
      )}

      {/* Panel filter: grid berlabel, bukan deretan kontrol mengambang.
          Sebelumnya semuanya flex-wrap tanpa label — lebarnya tidak rata dan
          maksud tiap kotak (apalagi dua kotak tanggal) cuma ketahuan dari
          tooltip. */}
      <div style={{ marginBottom: 16, padding: 16, background: "var(--idx-surface)", borderRadius: 8, border: "1px solid var(--idx-border)" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
          <Field label="Jenis Event">
            <select value={filters.event_type} onChange={(e) => updateFilter("event_type", e.target.value)} style={fieldStyle}>
              <option value="">Semua jenis event</option>
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
              ))}
            </select>
          </Field>

          <Field label="Severity">
            <select value={filters.severity} onChange={(e) => updateFilter("severity", e.target.value)} style={fieldStyle}>
              <option value="">Semua severity</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </Field>

          <Field label="Dari Tanggal">
            <input type="datetime-local" value={filters.since} onChange={(e) => updateFilter("since", e.target.value)} style={fieldStyle} />
          </Field>

          <Field label="Sampai Tanggal">
            <input type="datetime-local" value={filters.until} onChange={(e) => updateFilter("until", e.target.value)} style={fieldStyle} />
          </Field>

          <Field label="Urutkan">
            <select value={filters.sort_by} onChange={(e) => updateFilter("sort_by", e.target.value)} style={fieldStyle}>
              <option value="created_at">Waktu</option>
              <option value="severity">Severity</option>
              <option value="event_type">Jenis Event</option>
            </select>
          </Field>

          <Field label="Arah">
            <select value={filters.sort_order} onChange={(e) => updateFilter("sort_order", e.target.value)} style={fieldStyle}>
              <option value="desc">Terbaru dulu</option>
              <option value="asc">Terlama dulu</option>
            </select>
          </Field>
        </div>

        {/* Pencarian teks dibuat selebar panel: isinya kalimat, bukan pilihan pendek */}
        <div style={{ marginTop: 12 }}>
          <Field label="Cari Teks">
            <input
              type="text"
              placeholder="Kata kunci pada kolom detail, mis. nama file atau email"
              value={filters.q}
              onChange={(e) => updateFilter("q", e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") loadEvents(); }}
              style={fieldStyle}
            />
          </Field>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--idx-border)" }}>
          <button onClick={loadEvents} disabled={loading} style={{ padding: "8px 18px" }}>
            {loading ? "Memuat..." : "Terapkan"}
          </button>
          <button
            onClick={() => setFilters(DEFAULT_FILTERS)}
            style={{ padding: "8px 18px", background: "transparent", color: "var(--idx-text-body)", border: "1px solid var(--idx-border-strong)", borderRadius: 4, fontWeight: 600 }}
          >
            Reset
          </button>
          <button
            onClick={handleExport}
            style={{ padding: "8px 18px", background: "var(--idx-bg)", color: "var(--idx-red)", border: "1px solid var(--idx-red)", borderRadius: 4, fontWeight: 600, marginLeft: "auto" }}
          >
            Export CSV
          </button>
        </div>
      </div>

      {error && <p style={{ color: "var(--idx-danger)" }}>{error}</p>}

      {/* ---------- Tabel hasil ---------- */}
      <div style={{ border: "1px solid var(--idx-border)", borderRadius: 8, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--idx-surface-alt)", textAlign: "left" }}>
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
                <tr key={e.id} style={{ borderTop: "1px solid var(--idx-border-light)" }}>
                  <td style={{ padding: 10, whiteSpace: "nowrap" }}>
                    {new Date(e.created_at.endsWith("Z") ? e.created_at : e.created_at + "Z").toLocaleString()}
                  </td>
                  <td style={{ padding: 10, fontFamily: "monospace", fontSize: 11 }}>{e.user_id ? e.user_id.slice(0, 8) : "-"}</td>
                  <td style={{ padding: 10 }}>{e.event_type}</td>
                  <td style={{ padding: 10 }}>
                    <span style={{ color: SEVERITY_COLORS[e.severity] || "var(--idx-text-muted)", fontWeight: "bold" }}>{e.severity}</span>
                  </td>
                  <td style={{ padding: 10, maxWidth: 400, wordBreak: "break-word" }}>
                    {detail.message}
                    {detail.metadata && (
                      <div style={{ color: "var(--idx-text-subtle)", fontSize: 11, marginTop: 2 }}>
                        {JSON.stringify(detail.metadata)}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
            {events.length === 0 && !loading && (
              <tr>
                <td colSpan={5} style={{ padding: 20, textAlign: "center", color: "var(--idx-text-subtle)" }}>
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
