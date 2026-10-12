import Link from "next/link";

import { Nav } from "@/components/nav";
import { listMessages, type MessageRow } from "@/lib/api";
import {
  DUE_GROUPS,
  DUE_GROUP_LABEL,
  type DueGroup,
  deadlineLabel,
  deadlineTone,
  dueGroup,
  moneyLabel,
  senderLabel,
  sumByCurrency,
} from "@/lib/format";

export const dynamic = "force-dynamic";

// E-mails com cobrança são sempre minoria, mas pegamos com folga: o total do grupo
// é somado a partir do que é exibido, e um e-mail que ficasse de fora deixaria
// a soma menor do que a real.
const HOW_MANY = 200;

function Bill({ message }: { message: MessageRow }) {
  const money = moneyLabel(message.amount, message.currency);
  const due = deadlineLabel(message.deadline);

  return (
    <Link
      href={`/messages/${message.id}`}
      // Como na lista de e-mails: o pré-carregamento não deve marcar como lido.
      prefetch={false}
      className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-white/10 px-4 py-3 transition-colors duration-150 last:border-b-0 hover:bg-white/[0.06] sm:px-5"
    >
      {money ? (
        <span className="tabular shrink-0 font-mono text-sm font-semibold text-white sm:w-36">{money}</span>
      ) : (
        <span className="shrink-0 text-xs text-ink-faint sm:w-36">valor não informado</span>
      )}

      {/* No celular, o assunto fica em linha própria, na largura toda, abaixo do valor
          e do prazo: na mesma linha que eles, sobrava só "RE…". */}
      <span className="order-last min-w-0 basis-full sm:order-none sm:basis-0 sm:flex-1">
        <span className="block truncate text-sm text-ink">{message.subject}</span>
        <span className="mt-0.5 block truncate text-xs text-ink-faint">
          {senderLabel(message.sender_name, message.sender)} · {message.account.email}
        </span>
      </span>

      {due ? (
        <span
          className={`ml-auto shrink-0 rounded-md border px-2 py-0.5 text-[11px] whitespace-nowrap ${deadlineTone(message.deadline)}`}
        >
          {due}
        </span>
      ) : null}
    </Link>
  );
}

function Shelf({ group, items }: { group: DueGroup; items: MessageRow[] }) {
  if (items.length === 0) return null;
  const totals = sumByCurrency(items);

  return (
    <section className="mt-8 first:mt-0">
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3 px-1">
        <h2
          className={`text-sm font-semibold ${group === "overdue" ? "text-alarm" : "text-ink"}`}
        >
          {DUE_GROUP_LABEL[group]}
        </h2>
        <span className="text-xs text-ink-faint">
          {items.length === 1 ? "1 e-mail" : `${items.length} e-mails`}
        </span>
        <span className="tabular ml-auto text-sm font-semibold text-ink">
          {totals.map((total) => moneyLabel(total.amount, total.currency)).join(" · ")}
        </span>
      </div>
      <div className="glass-card overflow-hidden rounded-2xl border border-white/[0.13]">
        {items.map((message) => (
          <Bill key={message.id} message={message} />
        ))}
      </div>
    </section>
  );
}

export default async function MoneyPage() {
  const { items, total } = await listMessages({
    withMoney: true,
    byDeadline: true,
    limit: HOW_MANY,
  });

  const shelves = new Map<DueGroup, MessageRow[]>(DUE_GROUPS.map((group) => [group, []]));
  for (const message of items) {
    shelves.get(dueGroup(message.deadline))!.push(message);
  }

  return (
    <div>
      <Nav active="money" />

      <main className="mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 sm:py-8">
        <h1 className="text-2xl font-bold tracking-tight text-white">Dinheiro e prazos</h1>
        <p className="mt-1 mb-6 text-xs text-white/40">
          Apenas e-mails que mencionam um valor ou prazo. No topo, o que já está vencido.
          {total > items.length ? ` Exibindo ${items.length} de ${total}.` : null}
        </p>

        {items.length === 0 ? (
          <div className="glass-card rounded-2xl border border-white/[0.13] py-16 text-center">
            <p className="text-sm font-medium text-white">Nenhuma cobrança e nenhum prazo</p>
            <p className="mt-1 text-xs text-white/50">
              Valores e prazos aparecem aqui automaticamente assim que a análise chegar aos e-mails.
            </p>
          </div>
        ) : (
          DUE_GROUPS.map((group) => <Shelf key={group} group={group} items={shelves.get(group)!} />)
        )}
      </main>
    </div>
  );
}
