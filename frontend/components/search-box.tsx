"use client";

import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/**
 * Busca no cabeçalho. Formulário comum: Enter abre a caixa de entrada com a
 * busca no endereço, funciona até sem JavaScript. O JavaScript acrescenta só
 * uma coisa — Ctrl+K (⌘K no Mac) de qualquer lugar coloca o cursor no campo.
 */
export function SearchBox({ query = "", compact = false }: { query?: string; compact?: boolean }) {
  const field = useRef<HTMLInputElement>(null);
  const [mac, setMac] = useState(false);

  useEffect(() => {
    setMac(/Mac|iPhone|iPad/.test(navigator.platform));
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        field.current?.focus();
        field.current?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <form action="/" role="search" className="relative w-full">
      {/* z-10: o campo com vidro (backdrop-filter) é desenhado em camada própria
          e, sem isso, cobre o ícone, que vem antes na marcação. */}
      <span className="pointer-events-none absolute inset-y-0 left-0 z-10 flex items-center pl-3.5 text-ink-faint">
        <Search className="h-4 w-4" aria-hidden />
      </span>
      <input
        ref={field}
        type="search"
        name="q"
        defaultValue={query}
        maxLength={200}
        aria-label="Buscar em todos os e-mails"
        placeholder={compact ? "Buscar e-mails" : "Buscar em todos os e-mails: remetente, assunto, texto"}
        className="glass-pill w-full rounded-xl py-2 pr-14 pl-9 text-xs text-white placeholder:text-white/45 focus:border-link/60! focus:ring-2 focus:ring-link/30 focus:outline-none"
      />
      <span className="pointer-events-none absolute inset-y-0 right-0 z-10 hidden items-center pr-2.5 sm:flex">
        <kbd className="rounded-md border border-white/10 bg-white/10 px-1.5 py-0.5 font-mono text-[10px] text-ink-faint">
          {mac ? "⌘K" : "Ctrl K"}
        </kbd>
      </span>
    </form>
  );
}
