import Link from "next/link";

export default function HomePage() {
  return (
    <div style={{ maxWidth: 500, margin: "100px auto", textAlign: "center" }}>
      <h1>Generic ChatBot AI</h1>
      <p>Purwarupa Tingkat 1 — RAG + LLM Switching</p>
      <Link href="/login">Masuk untuk memulai →</Link>
    </div>
  );
}
