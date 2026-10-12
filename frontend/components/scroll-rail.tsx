"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Faixa com rolagem horizontal: abas, contas, seções no cabeçalho.
 *
 * As abas tendem a aumentar (o cliente pede uma, depois mais outra) e,
 * cedo ou tarde, não cabem em nenhuma tela. Por isso: as setas nas bordas
 * só aparecem quando há algo além da borda; um clique rola uma página,
 * um duplo clique vai direto ao fim; a roda do mouse sobre a faixa rola
 * na horizontal; a aba aberta entra sozinha no campo de visão. Sem
 * JavaScript, a faixa rola normalmente com o dedo ou o touchpad.
 */
export function ScrollRail({
  children,
  className = "",
  label,
  compact = false,
}: {
  children: React.ReactNode;
  className?: string;
  label?: string;
  /** Faixa estreita (seções no cabeçalho): setas e esmaecimento menores. */
  compact?: boolean;
}) {
  const strip = useRef<HTMLDivElement>(null);
  const [left, setLeft] = useState(false);
  const [right, setRight] = useState(false);

  const measure = useCallback(() => {
    const el = strip.current;
    if (!el) return;
    setLeft(el.scrollLeft > 2);
    setRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
  }, []);

  useEffect(() => {
    const el = strip.current;
    if (!el) return;

    // A aba aberta fica visível, mesmo que seja a última da fila.
    const active = el.querySelector<HTMLElement>("[aria-current='page'], [data-active='true']");
    if (active) {
      const box = el.getBoundingClientRect();
      const item = active.getBoundingClientRect();
      if (item.right > box.right || item.left < box.left) {
        el.scrollLeft += item.left - box.left - (box.width - item.width) / 2;
      }
    }
    measure();

    // A roda do mouse sobre a faixa rola na horizontal: num computador sem
    // touchpad, não haveria outro jeito de chegar às últimas abas.
    const onWheel = (event: WheelEvent) => {
      if (el.scrollWidth <= el.clientWidth) return;
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      const atStart = el.scrollLeft <= 0 && event.deltaY < 0;
      const atEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 1 && event.deltaY > 0;
      if (atStart || atEnd) return; // não há mais para onde ir: a rolagem passa para a página
      event.preventDefault();
      el.scrollLeft += event.deltaY;
    };

    const watcher = new ResizeObserver(measure);
    watcher.observe(el);
    el.addEventListener("scroll", measure, { passive: true });
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      watcher.disconnect();
      el.removeEventListener("scroll", measure);
      el.removeEventListener("wheel", onWheel);
    };
  }, [measure]);

  const page = (direction: 1 | -1) => {
    const el = strip.current;
    if (el) el.scrollBy({ left: direction * el.clientWidth * 0.8, behavior: "smooth" });
  };
  const edge = (direction: 1 | -1) => {
    const el = strip.current;
    if (el) el.scrollTo({ left: direction > 0 ? el.scrollWidth : 0, behavior: "smooth" });
  };

  const arrow = `glass-button absolute top-1/2 z-10 flex -translate-y-1/2 items-center justify-center rounded-full text-white/80 transition-all hover:text-white ${
    compact ? "h-6 w-6" : "h-8 w-8"
  }`;
  const icon = compact ? "h-3.5 w-3.5" : "h-4 w-4";
  const fade = compact ? "w-8" : "w-16";

  return (
    <div className="relative min-w-0" role={label ? "group" : undefined} aria-label={label}>
      <div ref={strip} className={`rail overflow-x-auto scroll-smooth ${className}`}>
        {children}
      </div>

      {/* Esmaecimento na borda: indica que há mais conteúdo além dela. */}
      <span
        aria-hidden
        className={`pointer-events-none absolute inset-y-0 left-0 ${fade} bg-gradient-to-r from-black/70 to-transparent transition-opacity ${left ? "opacity-100" : "opacity-0"}`}
      />
      <span
        aria-hidden
        className={`pointer-events-none absolute inset-y-0 right-0 ${fade} bg-gradient-to-l from-black/70 to-transparent transition-opacity ${right ? "opacity-100" : "opacity-0"}`}
      />

      {left ? (
        <button
          type="button"
          onClick={() => page(-1)}
          onDoubleClick={() => edge(-1)}
          className={`${arrow} ${compact ? "left-0" : "left-1"}`}
          aria-label="Rolar para a esquerda (duplo clique: ir ao início)"
          title="Esquerda · duplo clique: ir ao início"
        >
          <ChevronLeft className={icon} aria-hidden />
        </button>
      ) : null}
      {right ? (
        <button
          type="button"
          onClick={() => page(1)}
          onDoubleClick={() => edge(1)}
          className={`${arrow} ${compact ? "right-0" : "right-1"}`}
          aria-label="Rolar para a direita (duplo clique: ir ao fim)"
          title="Direita · duplo clique: ir ao fim"
        >
          <ChevronRight className={icon} aria-hidden />
        </button>
      ) : null}
    </div>
  );
}
