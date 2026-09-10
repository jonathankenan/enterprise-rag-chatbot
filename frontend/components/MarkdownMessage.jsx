"use client";

/**
 * Render isi pesan ASISTEN sebagai markdown.
 *
 * Sebelum ini pesan ditampilkan lewat {m.content} apa adanya, jadi jawaban
 * yang formatnya benar pun tampil mentah: pipa tabel berjejer sebagai teks,
 * "**Document Source Inventory**" muncul lengkap dengan bintangnya. Bukan
 * model yang salah format -- keluarannya memang markdown, cuma tidak pernah
 * ada yang merender.
 *
 * remark-gfm WAJIB ada: tabel, strikethrough, dan task list itu GitHub
 * Flavored Markdown, bukan markdown standar. Tanpa plugin ini tabel tetap
 * tampil sebagai baris berpipa.
 *
 * KEAMANAN -- rehype-raw JANGAN ditambahkan.
 * Tanpa plugin itu react-markdown tidak pernah merender HTML mentah, dan itu
 * yang kita mau: isi pesan asisten bisa memuat potongan dokumen yang diunggah
 * pengguna (indirect prompt injection sudah jadi masalah nyata di proyek ini
 * -- lihat guardrail/prompt_injection.py). Kalau HTML mentah dirender, dokumen
 * berisi <script> atau <img onerror=...> jadi jalur XSS yang melewati seluruh
 * guardrail backend, karena guardrail memeriksa TEKS, bukan markup.
 * react-markdown juga sudah membuang URL berskema berbahaya (javascript:)
 * secara bawaan.
 *
 * Pesan MANUSIA (ketikan user, balasan admin helpdesk) sengaja TIDAK lewat
 * sini. Orang yang menempelkan data berpipa atau berbintang harus melihatnya
 * persis seperti yang dia ketik, bukan berubah bentuk jadi tabel.
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Jarak antar blok diatur lewat grid gap, bukan margin tiap elemen: margin
// bawah elemen terakhir selalu menyisakan ruang kosong di dalam bubble, dan
// itu tidak bisa dihilangkan dengan inline style (tidak ada :last-child).
const wrap = { display: "grid", gap: 8, lineHeight: 1.5 };

const components = {
  // Tabel dibungkus kotak yang bisa digeser: Document Source Inventory punya
  // 6 kolom dan pasti lebih lebar dari bubble di layar sempit. Tanpa ini
  // seluruh halaman yang ikut melebar.
  table: ({ node, ...p }) => (
    <div style={{ overflowX: "auto", maxWidth: "100%" }}>
      <table style={{ borderCollapse: "collapse", fontSize: 13 }} {...p} />
    </div>
  ),
  th: ({ node, ...p }) => (
    <th style={{ border: "1px solid #c8c8c8", background: "#e6e6e6",
                 padding: "6px 10px", textAlign: "left", fontWeight: 600 }} {...p} />
  ),
  td: ({ node, ...p }) => (
    <td style={{ border: "1px solid #d8d8d8", padding: "6px 10px",
                 verticalAlign: "top" }} {...p} />
  ),

  p: ({ node, ...p }) => <p style={{ margin: 0 }} {...p} />,
  ul: ({ node, ...p }) => <ul style={{ margin: 0, paddingLeft: 20 }} {...p} />,
  ol: ({ node, ...p }) => <ol style={{ margin: 0, paddingLeft: 20 }} {...p} />,
  li: ({ node, ...p }) => <li style={{ marginBottom: 2 }} {...p} />,

  // Ukuran heading diturunkan: h1 bawaan browser lebih besar daripada bubble
  // chat-nya sendiri.
  h1: ({ node, ...p }) => <h3 style={{ margin: 0, fontSize: 16 }} {...p} />,
  h2: ({ node, ...p }) => <h4 style={{ margin: 0, fontSize: 15 }} {...p} />,
  h3: ({ node, ...p }) => <h5 style={{ margin: 0, fontSize: 14 }} {...p} />,

  // react-markdown v9+ TIDAK lagi mengirim prop `inline` (dulu ada, banyak
  // contoh di internet masih memakainya dan diam-diam selalu falsy). Blok kode
  // dibedakan dari dua penanda yang tersedia: kelas bahasa dari pagar ```lang,
  // atau adanya baris baru di isinya.
  code: ({ node, className, children, ...p }) => {
    const blok = /language-/.test(className || "") || String(children).includes("\n");
    return blok ? (
      <code className={className} style={{ fontSize: "0.9em" }} {...p}>{children}</code>
    ) : (
      <code className={className}
            style={{ background: "#e4e4e4", padding: "1px 4px", borderRadius: 3,
                     fontSize: "0.9em" }} {...p}>{children}</code>
    );
  },
  pre: ({ node, ...p }) => (
    <pre style={{ background: "#eaeaea", padding: 10, borderRadius: 6,
                  overflowX: "auto", margin: 0, fontSize: 12 }} {...p} />
  ),

  blockquote: ({ node, ...p }) => (
    <blockquote style={{ margin: 0, paddingLeft: 10, borderLeft: "3px solid #ccc",
                         color: "#555" }} {...p} />
  ),
  hr: ({ node, ...p }) => (
    <hr style={{ border: "none", borderTop: "1px solid #ddd", margin: 0 }} {...p} />
  ),
  // rel wajib: tanpa noopener, tab tujuan bisa menyetir tab asal lewat
  // window.opener.
  a: ({ node, ...p }) => (
    <a target="_blank" rel="noopener noreferrer" style={{ color: "#0070f3" }} {...p} />
  ),
};

export default function MarkdownMessage({ children }) {
  if (!children) return null;
  return (
    <div style={wrap}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
