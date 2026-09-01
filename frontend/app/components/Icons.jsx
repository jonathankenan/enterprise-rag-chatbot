// Ikon garis sederhana untuk item navigasi. Dibuat inline (bukan library
// ikon) supaya tidak menambah dependensi; ukurannya seragam 18px dan mewarisi
// warna teks lewat currentColor sehingga otomatis ikut state aktif/hover.

const base = {
  width: 18, height: 18, viewBox: "0 0 24 24", fill: "none",
  stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round",
};

export const IconNewChat = () => (
  <svg {...base}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>
);
export const IconAudit = () => (
  <svg {...base}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6" /><path d="M8 13h8M8 17h5" /></svg>
);
export const IconUsers = () => (
  <svg {...base}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>
);
export const IconBook = () => (
  <svg {...base}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /></svg>
);
export const IconHeadset = () => (
  <svg {...base}><path d="M3 18v-6a9 9 0 0 1 18 0v6" /><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3ZM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3Z" /></svg>
);
export const IconArchive = () => (
  <svg {...base}><rect x="2" y="4" width="20" height="5" rx="1" /><path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9" /><path d="M10 13h4" /></svg>
);
export const IconChats = () => (
  <svg {...base}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z" /></svg>
);
export const IconPanel = () => (
  <svg {...base}><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 3v18" /></svg>
);
export const IconMail = () => (
  <svg {...base}><rect x="2" y="4" width="20" height="16" rx="2" /><path d="m22 7-10 6L2 7" /></svg>
);
export const IconLock = () => (
  <svg {...base}><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
);
export const IconEye = ({ off }) => (
  <svg {...base}>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
    <circle cx="12" cy="12" r="3" />
    {off && <path d="m3 3 18 18" />}
  </svg>
);
