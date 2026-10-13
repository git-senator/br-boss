import { useId } from "react";

/**
 * Símbolo do BR BOSS: escudo prateado com um chip "AI" e racks de servidor nas laterais.
 *
 * Vetorial, e não imagem: no cabeçalho ele tem 36 pixels, mas em celulares com
 * tela de alta densidade são três vezes mais pontos, e um ícone rasterizado
 * ficaria borrado. A moldura arco-íris e o brilho ficam ao redor, em LogoMark.
 */
function Emblem() {
  // Os ids dos gradientes são únicos na página: o símbolo aparece no cabeçalho
  // e na página de login, e ids repetidos quebram o preenchimento do segundo.
  const id = useId().replace(/:/g, "");
  const metal = `metal-${id}`;
  const rim = `rim-${id}`;
  const rack = `rack-${id}`;

  // Blocos dos racks: à esquerda e à direita, abrindo para baixo, como no esboço.
  const blocks = [
    { y: 14, w: 9 },
    { y: 21, w: 10 },
    { y: 28, w: 11 },
    { y: 35, w: 12 },
    { y: 42, w: 13 },
  ];

  return (
    <svg viewBox="0 0 64 64" className="h-full w-full" aria-hidden>
      <defs>
        <linearGradient id={metal} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#f4f5f7" />
          <stop offset="0.55" stopColor="#c3c7cf" />
          <stop offset="1" stopColor="#8a909b" />
        </linearGradient>
        <linearGradient id={rim} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#9aa0aa" />
        </linearGradient>
        <linearGradient id={rack} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#e6e8ec" />
          <stop offset="1" stopColor="#8f95a0" />
        </linearGradient>
      </defs>

      {/* Racks de servidor nas laterais */}
      {blocks.map((block) => (
        <g key={block.y}>
          <rect x={14 - block.w} y={block.y} width={block.w} height={5} rx={1.2} fill={`url(#${rack})`} />
          <rect x={50} y={block.y} width={block.w} height={5} rx={1.2} fill={`url(#${rack})`} />
          <rect x={15.5 - block.w} y={block.y + 1.6} width={2.2} height={1.8} rx={0.5} fill="#2a2d34" />
          <rect x={46.3 + block.w} y={block.y + 1.6} width={2.2} height={1.8} rx={0.5} fill="#2a2d34" />
        </g>
      ))}

      {/* Escudo */}
      <path
        d="M32 7 L50 13 V30 C50 43 42.5 51.5 32 57 C21.5 51.5 14 43 14 30 V13 Z"
        fill={`url(#${metal})`}
        stroke={`url(#${rim})`}
        strokeWidth={1.2}
      />
      <path
        d="M32 11.5 L46 16.2 V30 C46 40.6 40 47.6 32 52.2 C24 47.6 18 40.6 18 30 V16.2 Z"
        fill="none"
        stroke="#6b717c"
        strokeWidth={1}
      />

      {/* Chip com terminais */}
      {[26, 30, 34, 38].map((at) => (
        <g key={at} stroke="#2a2d34" strokeWidth={1.4} strokeLinecap="round">
          <line x1={at} y1={20.5} x2={at} y2={23} />
          <line x1={at} y1={39} x2={at} y2={41.5} />
          <line x1={20.5} y1={at - 1} x2={23} y2={at - 1} />
          <line x1={41} y1={at - 1} x2={43.5} y2={at - 1} />
        </g>
      ))}
      <rect x={23} y={23} width={18} height={16} rx={2.5} fill="#1d2027" stroke="#e8eaee" strokeWidth={1.2} />
      <text
        x={32}
        y={34.6}
        textAnchor="middle"
        fontSize={9.5}
        fontWeight={800}
        fontFamily="-apple-system, 'Segoe UI', Arial, sans-serif"
        fill="#f4f5f7"
        letterSpacing={0.3}
      >
        AI
      </text>
    </svg>
  );
}

/** Símbolo em um quadrado com moldura arco-íris e brilho suave. */
export function LogoMark({ size = "md" }: { size?: "md" | "lg" }) {
  const box = size === "lg" ? "h-11 w-11 rounded-[14px]" : "h-9 w-9 rounded-xl";
  const inner = size === "lg" ? "rounded-[13px] p-1" : "rounded-[11px] p-[3px]";
  return (
    <span
      className={`spring block shrink-0 bg-gradient-to-tr from-ai-blue via-ai-purple to-ai-pink p-px shadow-[0_0_18px_rgb(175_82_222/0.35)] group-hover:scale-105 ${box}`}
    >
      <span className={`flex h-full w-full items-center justify-center bg-[#0e0e12] ${inner}`}>
        <Emblem />
      </span>
    </span>
  );
}
