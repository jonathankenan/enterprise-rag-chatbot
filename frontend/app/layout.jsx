export const metadata = {
  title: "Generic ChatBot AI",
  description: "Purwarupa chatbot AI berbasis RAG — Tingkat 1",
};

export default function RootLayout({ children }) {
  return (
    <html lang="id">
      <body style={{ fontFamily: "sans-serif", margin: 0 }}>{children}</body>
    </html>
  );
}
