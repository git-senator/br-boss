"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Esc fecha o painel do e-mail. Sem JavaScript, ele é fechado pelo X e
 * pelo fundo — que são links comuns; aqui fica só a tecla.
 */
export function EscapeClose({ href }: { href: string }) {
  const router = useRouter();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Esc no campo de resposta significa «sair do campo», e não «fechar o
      // e-mail junto com o texto pela metade».
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      router.push(href, { scroll: false });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [href, router]);

  return null;
}
