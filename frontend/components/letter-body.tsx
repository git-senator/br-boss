"use client";

import { Languages } from "lucide-react";
import { useState } from "react";

import { linkParts, shortLink } from "@/lib/format";

/** Texto do e-mail com links. O React escapa o texto sozinho: montar HTML
 * como string a partir de um e-mail alheio não é permitido em hipótese alguma. */
function Text({ text }: { text: string }) {
  return (
    <pre className="font-sans text-xs leading-relaxed break-words whitespace-pre-wrap text-white/80">
      {linkParts(text).map((part, at) =>
        part.href ? (
          <a
            key={at}
            href={part.href}
            target="_blank"
            // noreferrer e nofollow: o site alheio não deve saber de onde
            // a pessoa veio nem ganhar relevância conosco. noopener —
            // para que a aba aberta não consiga controlar a nossa.
            rel="noopener noreferrer nofollow"
            title={part.href}
            className="text-link underline decoration-link/40 underline-offset-2 transition-colors duration-150 hover:decoration-link"
          >
            {shortLink(part.text)}
          </a>
        ) : (
          <span key={at}>{part.text}</span>
        ),
      )}
    </pre>
  );
}

/**
 * Corpo do e-mail. Se há tradução, mostramos a tradução, e o original fica
 * a um clique: a troca é instantânea, sem requisição ao servidor.
 */
export function LetterBody({ original, translated }: { original: string; translated: string | null }) {
  const [showOriginal, setShowOriginal] = useState(false);

  if (!translated) {
    return (
      <article className="glass-card rounded-2xl p-5">
        <Text text={original} />
      </article>
    );
  }

  return (
    <article className="glass-card rounded-2xl p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-white/10 pb-3 text-[11px]">
        <span className="flex items-center gap-1.5 text-ink-dim">
          <Languages className="h-3.5 w-3.5 text-ai-purple" aria-hidden />
          {showOriginal ? "E-mail original" : "Tradução para o português — feita automaticamente"}
        </span>
        <button
          type="button"
          onClick={() => setShowOriginal((now) => !now)}
          className="rounded-lg bg-white/10 px-2.5 py-1 font-medium text-white/85 transition-colors hover:bg-white/15"
        >
          {showOriginal ? "Mostrar tradução" : "Mostrar original"}
        </button>
      </div>
      <Text text={showOriginal ? original : translated} />
    </article>
  );
}
