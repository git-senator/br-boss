import Link from "next/link";

import { refreshBriefAction } from "@/app/actions";
import { Nav } from "@/components/nav";
import { getBrief, type MessageRow } from "@/lib/api";
import {
  deadlineLabel,
  deadlineTone,
  moneyLabel,
  priorityTone,
  senderLabel,
  whenLabel,
} from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * Resumo — a primeira tela após entrar (especificação, seções 16, 35, 36).
 *
 * Não "225 não lidos", e sim "5 exigem decisão, 8 aguardam resposta,
 * 3 pagamentos". Cada linha leva ao e-mail, onde há resposta, "Ignorar"
 * e "Lembrar" — ou seja, do resumo à decisão é um passo só.
 */

function Line({ message, money = false }: { message: MessageRow; money?: boolean }) {
  return (
    <Link
      href={`/messages/${message.id}`}
      prefetch={false}
      className="flex gap-3 border-b border-white/10 px-4 py-3 transition-colors duration-150 last:border-b-0 hover:bg-white/[0.06]"
    >
      <span
        className={`tabular mt-0.5 h-7 w-9 shrink-0 rounded text-center text-sm leading-7 font-semibold ${priorityTone(message.priority)}`}
      >
        {message.priority ?? "—"}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className="truncate font-medium text-ink">
            {senderLabel(message.sender_name, message.sender)}
          </span>
          <span className="ml-auto shrink-0 text-xs text-ink-faint">{whenLabel(message.sent_at)}</span>
        </span>
        <span className="mt-0.5 block text-sm text-ink-dim">{message.summary || message.subject}</span>
        {money && (message.amount || message.deadline) ? (
          <span className="mt-1.5 flex flex-wrap gap-2 text-xs">
            {message.amount ? (
              <span className="tabular rounded-md bg-white/10 px-1.5 py-0.5 font-mono font-semibold text-white">
                {moneyLabel(message.amount, message.currency)}
              </span>
            ) : null}
            {message.deadline ? (
              <span className={`rounded-md border px-1.5 py-0.5 ${deadlineTone(message.deadline)}`}>
                {deadlineLabel(message.deadline)}
              </span>
            ) : null}
          </span>
        ) : null}
      </span>
    </Link>
  );
}

function Section({
  mark,
  title,
  empty,
  letters,
  money = false,
}: {
  mark: string;
  title: string;
  empty: string;
  letters: MessageRow[];
  money?: boolean;
}) {
  return (
    <section className="mt-6">
      <h2 className="flex items-baseline gap-2 text-base font-semibold text-ink">
        <span aria-hidden>{mark}</span>
        {title}
        <span className="tabular text-titan">{letters.length}</span>
      </h2>
      {letters.length === 0 ? (
        <p className="mt-2 text-sm text-ink-faint">{empty}</p>
      ) : (
        <div className="glass-card mt-2 overflow-hidden rounded-2xl border border-white/[0.13]">
          {letters.map((message) => (
            <Line key={message.id} message={message} money={money} />
          ))}
        </div>
      )}
    </section>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="glass-card rounded-2xl border border-white/[0.13] px-3 py-3 text-center">
      <span className="tabular block text-2xl font-semibold text-ink">{value}</span>
      <span className="block text-xs leading-tight text-ink-dim">{label}</span>
    </div>
  );
}

export default async function BriefPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  const data = await getBrief();
  const day = new Date(`${data.day}T12:00:00`).toLocaleDateString("pt-BR", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  return (
    <div>
      <Nav active="brief" />

      <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
        <p className="text-sm text-ink-faint first-letter:uppercase">{day}</p>
        <h1 className="text-2xl font-bold tracking-tight text-white">Resumo</h1>

        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat value={data.attention.length} label="exigem atenção" />
          <Stat value={data.replies.length} label="aguardam resposta" />
          <Stat value={data.money.length} label="pagamentos e prazos" />
          <Stat value={data.filtered + data.information} label="tratados pela IA sem você em 24 h" />
        </div>

        <div className="ai-frame mt-4 px-5 py-4">
          {data.intro ? (
            <p className="leading-relaxed text-ink">{data.intro}</p>
          ) : (
            <p className="text-sm text-ink-dim">
              Todas as manhãs, a IA escreve um breve "o essencial das últimas 24 horas". O de hoje
              ainda não saiu — as listas abaixo já estão atualizadas.
            </p>
          )}
          <form action={refreshBriefAction} className="mt-2">
            <button className="text-sm text-ink-faint transition-colors duration-150 hover:text-ink">
              ↻ {data.intro ? "Gerar novamente" : "Gerar agora"}
            </button>
            {data.generated_at ? (
              <span className="ml-2 text-xs text-ink-faint">gerado {whenLabel(data.generated_at)}</span>
            ) : null}
          </form>
          {error ? <p className="mt-2 text-sm text-alarm">{error}</p> : null}
        </div>

        <Section
          mark="🔴"
          title="Exigem atenção"
          empty="Nada urgente."
          letters={data.attention}
        />
        <Section
          mark="🟠"
          title="Convém responder"
          empty="Ninguém aguarda resposta."
          letters={data.replies}
        />
        <Section
          mark="💰"
          title="Pagamentos e prazos da semana"
          empty="Nada a pagar nesta semana."
          letters={data.money}
          money
        />

        <p className="mt-6 text-sm text-ink-dim">
          E-mails recebidos nas últimas 24 horas: {data.arrived}. Informativos: {data.information};
          filtrados como sem importância: {data.filtered}.{" "}
          <Link href="/" className="text-link hover:underline">
            Todos os e-mails →
          </Link>
        </p>
      </main>
    </div>
  );
}
