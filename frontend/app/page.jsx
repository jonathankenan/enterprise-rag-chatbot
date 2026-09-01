import { redirect } from "next/navigation";

// Halaman root tidak menampilkan apa pun sendiri: pengguna yang sudah masuk
// langsung ke chat, dan yang belum masuk otomatis dilempar ke /login oleh
// shell aplikasi. Landing page terpisah cuma menambah satu klik tanpa
// memberi informasi baru.
export default function HomePage() {
  redirect("/chat");
}
