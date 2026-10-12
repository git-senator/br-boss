import { Bell, KeyRound, LogOut } from "lucide-react";
import Link from "next/link";

import { logoutAction } from "@/app/actions";
import { LogoMark } from "@/components/logo-mark";
import { ScrollRail } from "@/components/scroll-rail";
import { SearchBox } from "@/components/search-box";
import { getStatus, me, type SystemStatus } from "@/lib/api";

type Section = "brief" | "inbox" | "money" | "rules" | "accounts";

const SECTIONS: { key: Section; href: string; label: string }[] = [
  { key: "brief", href: "/brief", label: "Resumo" },
  { key: "inbox", href: "/", label: "Caixa de entrada" },
  { key: "money", href: "/money", label: "Dinheiro e prazos" },
  { key: "rules", href: "/rules", label: "Regras" },
  { key: "accounts", href: "/accounts", label: "Caixas" },
];

/** Selo de análise: mostra com honestidade se a IA está funcionando agora. */
function AiState({ status }: { status: SystemStatus }) {
  const { ai, unsorted } = status;
  let dot = "bg-ok animate-pulse";
  const name = ai.own_key ? `${ai.name} · sua chave` : ai.name;
  let text = `${name} · analisando e-mails`;
  if (!ai.configured) {
    dot = "bg-alarm";
    text = `${name} · sem chave`;
  } else if (ai.paused_until) {
    dot = "bg-warn";
    const until = new Date(ai.paused_until * 1000).toLocaleTimeString("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
    });
    text = `${name} · pausada até ${until}`;
  } else if (unsorted > 0) {
    dot = "bg-link animate-pulse";
    text = `${name} · ${unsorted} na fila`;
  }
  return (
    <Link
      href="/key"
      className="glass-pill hidden items-center gap-2 rounded-xl px-3 py-1.5 text-xs text-ink-dim hover:text-white xl:flex"
      title="Qual modelo analisa seus e-mails e com qual chave. Clique para inserir sua própria chave."
    >
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
      <span className="whitespace-nowrap">{text}</span>
    </Link>
  );
}

function initials(email: string): string {
  const name = email.split("@")[0].replace(/[^\p{L}]/gu, "");
  return (name.slice(0, 2) || "?").toUpperCase();
}

export async function Nav({ active, query }: { active?: Section; query?: string }) {
  // O cabeçalho não pode derrubar a página: se o status não vier,
  // simplesmente não há selo nem número no sino.
  const [status, who] = await Promise.all([
    getStatus().catch(() => null),
    me().catch(() => null),
  ]);

  return (
    <header className="glass sticky top-0 z-40 border-b border-edge">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-3 px-4 sm:gap-4 sm:px-6">
        <Link href="/brief" className="group flex shrink-0 items-center gap-3" aria-label="BR BOSS — resumo">
          <LogoMark />
          <span className="hidden items-center gap-1.5 whitespace-nowrap sm:flex">
            <span className="text-base font-bold tracking-tight text-white">BR BOSS</span>
            <span className="rounded-full border border-white/10 bg-white/10 px-1.5 text-[10px] font-semibold text-white/80">
              AI
            </span>
          </span>
        </Link>

        {/* Seletor de seções. Em telas estreitas, rola com o dedo. */}
        <nav className="glass-pill min-w-0 rounded-xl p-1 text-xs font-medium">
          <ScrollRail compact className="flex items-center">
          {SECTIONS.map((section) => (
            <Link
              key={section.key}
              href={section.href}
              aria-current={active === section.key ? "page" : undefined}
              className={`shrink-0 rounded-lg px-3 py-1.5 whitespace-nowrap transition-colors sm:px-3.5 ${
                active === section.key
                  ? "bg-white/15 font-semibold text-white shadow-sm"
                  : "text-ink-dim hover:text-white"
              }`}
            >
              {section.label}
            </Link>
          ))}
          </ScrollRail>
        </nav>

        <div className="mx-2 hidden max-w-md flex-1 lg:block">
          <SearchBox query={query} />
        </div>

        <div className="ml-auto flex shrink-0 items-center gap-1 sm:gap-3">
          {status ? <AiState status={status} /> : null}

          <Link
            href="/brief"
            className="relative rounded-xl p-2 text-white/70 transition-colors hover:bg-white/10 hover:text-white"
            aria-label={status?.attention ? `Precisam de atenção: ${status.attention}` : "Nada urgente"}
            title={status?.attention ? `Precisam de atenção: ${status.attention}` : "Nada urgente"}
          >
            <Bell className="h-4 w-4" aria-hidden />
            {status?.attention ? (
              <span className="tabular absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-alarm px-1 text-center text-[10px] leading-4 font-semibold text-white">
                {status.attention > 99 ? "99+" : status.attention}
              </span>
            ) : null}
          </Link>

          {/* Menu sem JavaScript: o details abre e fecha sozinho. */}
          <details className="relative">
            <summary className="spring flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-full bg-gradient-to-tr from-ai-blue to-ai-purple p-px hover:scale-105 [&::-webkit-details-marker]:hidden">
              <span className="flex h-full w-full items-center justify-center rounded-full bg-black text-[11px] font-semibold text-white">
                {who ? initials(who.email) : "?"}
              </span>
            </summary>
            <div className="menu absolute right-0 z-50 mt-2 w-60 rounded-2xl p-2">
              {who ? (
                <p className="truncate px-3 py-2 text-xs text-ink-dim" title={who.email}>
                  {who.email}
                </p>
              ) : null}
              <Link
                href="/key"
                className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-ink transition-colors hover:bg-white/10"
              >
                <KeyRound className="h-4 w-4 text-ink-dim" aria-hidden />
                Chave de IA
                <span className="ml-auto text-xs text-ink-faint">
                  {who?.ai_key_hint ?? (who?.ai_shared_key ? "do servidor" : "nenhuma")}
                </span>
              </Link>
              <form action={logoutAction}>
                <button className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-ink transition-colors hover:bg-white/10">
                  <LogOut className="h-4 w-4 text-ink-dim" aria-hidden />
                  Sair
                </button>
              </form>
            </div>
          </details>
        </div>
      </div>
    </header>
  );
}
