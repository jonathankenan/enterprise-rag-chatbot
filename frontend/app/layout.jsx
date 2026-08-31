import { Open_Sans } from "next/font/google";
import "./globals.css";

// Open Sans = font yang dipakai www.idx.co.id (dicek lewat computed style),
// dimuat via next/font supaya di-self-host, bukan request ke Google saat runtime.
const openSans = Open_Sans({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  display: "swap",
});

export const metadata = {
  title: "Generic ChatBot AI",
  description: "Purwarupa chatbot AI berbasis RAG — Tingkat 1",
};

export default function RootLayout({ children }) {
  return (
    <html lang="id" className={openSans.className}>
      <body>{children}</body>
    </html>
  );
}
