"use client";

import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

// O que aconteceu, em linguagem humana. A chave chega no endereço (?toast=sent)
// depois da ação: os formulários funcionam sem JavaScript, não há outro canal.
const TEXT: Record<string, string> = {
  sent: "Resposta enviada",
  ignored: "E-mail removido das pendências",
  snoozed: "Adiado — o e-mail volta na data marcada",
  reopened: "O e-mail voltou para as pendências",
};

/**
 * Mensagem flutuante no canto inferior direito. Some sozinha em três
 * segundos, e a chave sai do endereço: recarregou a página, a mensagem não se repete.
 */
export function Toast({ kind }: { kind?: string }) {
  const [shown, setShown] = useState(false);
  const text = kind ? TEXT[kind] : undefined;

  useEffect(() => {
    if (!text) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("toast");
    window.history.replaceState(null, "", url);

    const show = setTimeout(() => setShown(true), 10);
    const hide = setTimeout(() => setShown(false), 3000);
    return () => {
      clearTimeout(show);
      clearTimeout(hide);
    };
  }, [text]);

  if (!text) return null;
  return (
    <div
      role="status"
      className={`glass pointer-events-none fixed right-6 bottom-6 z-[60] flex items-center gap-2 rounded-2xl border border-white/20 px-4 py-3 text-xs text-white shadow-2xl transition-all duration-300 ${
        shown ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0"
      }`}
    >
      <Sparkles className="h-4 w-4 text-ai-purple" aria-hidden />
      <span>{text}</span>
    </div>
  );
}
