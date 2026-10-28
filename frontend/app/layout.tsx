import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Idea Evolution Engine",
  description: "Avaliação rastreável e limitada de ideias.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <body>
        <header className="topbar">
          <Link className="brand" href="/" aria-label="Idea Evolution Engine — início">
            <span className="brand-mark">IE</span>
            <span>
              <strong>Idea Evolution</strong>
              <small>Engine</small>
            </span>
          </Link>
          <nav aria-label="Navegação principal">
            <Link href="/">Projetos</Link>
            <Link href="/discover">Descobrir</Link>
            <Link href="/profiles">Perfis</Link>
            <Link href="/prompts">Prompts</Link>
            <Link href="/finance">Financeiro</Link>
            <Link className="button button-small" href="/new">
              Nova ideia
            </Link>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
