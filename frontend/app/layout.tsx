import type { Metadata, Viewport } from "next";

import "./globals.css";

// Fonte do sistema — a mesma do próprio sistema operacional: no Mac
// e no iPhone é a SF, no Windows é a Segoe. Nada é baixado, a página
// abre na hora, e o CSP rígido do next.config.ts não bloqueia nada.

export const metadata: Metadata = {
  title: "BR BOSS",
  description: "Central única da sua caixa de entrada",
};

// Vai ser usado no celular e no iPad — largura do dispositivo, sem zoom.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#000000",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="min-h-screen bg-ground font-sans text-ink antialiased selection:bg-link/30 selection:text-white">
        {children}
      </body>
    </html>
  );
}
