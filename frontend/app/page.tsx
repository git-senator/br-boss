import { ChevronRight, ExternalLink, Inbox, Sparkles, X } from "lucide-react";
import Link from "next/link";

import { EscapeClose } from "@/components/escape-close";
import { ScrollRail } from "@/components/scroll-rail";
import { CategoryTag, MessageView, ScoreCapsule } from "@/components/message-view";
import { Nav } from "@/components/nav";
import { SearchBox } from "@/components/search-box";
import { Toast } from "@/components/toast";
import {
  ApiError,
  getMessage,
  getMessageCounts,
  listAccounts,
  listMessages,
  markRead,
  type Mailbox,
  type MessageFull,
  type MessageRow,
} from "@/lib/api";
import {
  type InboxCounts,
  SPAM,
  TAB_ORDER,
  categoryLabel,
  deadlineLabel,
  deadlineTone,
  moneyLabel,
  priorityTone,
  senderLabel,
  tabCount,
  whenLabel,
} from "@/lib/format";

export const dynamic = "force-dynamic";

type Search = {
  category?: string;
  account?: string;
  unread?: string;
  q?: string;
  open?: string;
  error?: string;
  toast?: string;
};

/** Endereço da lista com os filtros desejados. Erro e mensagem não entram nele. */
function href(current: Search, extra: Search): string {
  const merged = { ...current, ...extra };
  const query = new URLSearchParams();
  if (merged.category) query.set("category", merged.category);
  if (merged.account) query.set("account", merged.account);
  if (merged.unread) query.set("unread", merged.unread);
  if (merged.q) query.set("q", merged.q);
  if (merged.open) query.set("open", merged.open);
  return query.toString() ? `/?${query}` : "/";
}

// Ponto na aba — só onde a cor significa algo: urgente e não lidos.
const DOT: Record<string, string> = { urgent: "bg-alarm", [SPAM]: "bg-white/30" };

function Pill({
  to,
  label,
  count,
  on,
  dot,
}: {
  to: string;
  label: string;
  count: string;
  on: boolean;
  dot?: string;
}) {
  return (
    <Link
      href={to}
      scroll={false}
      aria-current={on ? "page" : undefined}
      className={`glass-pill flex shrink-0 items-center gap-2 rounded-xl px-3.5 py-2 text-xs font-medium whitespace-nowrap ${
        on ? "glass-pill-on text-white" : "text-white/75 hover:text-white"
      }`}
    >
      {dot ? <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden /> : null}
      <span>{label}</span>
      <span
        className={`tabular rounded-md px-1.5 text-[10px] ${
          on
            ? "bg-white/20 font-bold text-white"
            : count === "0"
              ? "bg-white/5 text-white/40"
              : "bg-white/10 text-white/80"
        }`}
      >
        {count}
      </span>
    </Link>
  );
}

function Pills({ current, counts }: { current: Search; counts: InboxCounts }) {
  const unreadOnly = Boolean(current.unread);
  return (
    <div className="mb-4">
    <ScrollRail label="Abas" className="flex items-center gap-2 py-1">
      <Pill
        to={href(current, { category: undefined, open: undefined })}
        label="Todos"
        count={tabCount(counts.all, unreadOnly)}
        on={!current.category}
      />
      {TAB_ORDER.map((key) => (
        <Pill
          key={key}
          to={href(current, { category: key, open: undefined })}
          label={categoryLabel(key)}
          count={tabCount(counts.categories[key], unreadOnly)}
          on={current.category === key}
          dot={DOT[key]}
        />
      ))}
      <Pill
        to={href(current, { unread: unreadOnly ? undefined : "1", open: undefined })}
        label="Não lidos"
        count={String(counts.all.unread)}
        on={unreadOnly}
        dot="bg-link"
      />
    </ScrollRail>
    </div>
  );
}

function Boxes({ current, boxes }: { current: Search; boxes: Mailbox[] }) {
  if (boxes.length < 2) return null;
  const chip = (on: boolean) =>
    `glass-pill shrink-0 rounded-full px-3 py-1 text-[11px] whitespace-nowrap ${
      on ? "glass-pill-on text-white" : "text-white/60 hover:text-white"
    }`;
  return (
    <div className="mb-6">
    <ScrollRail label="Caixas de e-mail" className="flex gap-2 py-1">
      <Link
        href={href(current, { account: undefined, open: undefined })}
        scroll={false}
        aria-current={!current.account ? "page" : undefined}
        className={chip(!current.account)}
      >
        Todas as caixas
      </Link>
      {boxes.map((box) => (
        <Link
          key={box.id}
          href={href(current, { account: String(box.id), open: undefined })}
          scroll={false}
          aria-current={current.account === String(box.id) ? "page" : undefined}
          className={chip(current.account === String(box.id))}
        >
          {box.email}
        </Link>
      ))}
    </ScrollRail>
    </div>
  );
}

/** Cartão do e-mail. Abre um painel sobre a lista, e não uma nova página. */
function Card({ message, to, opened }: { message: MessageRow; to: string; opened: boolean }) {
  return (
    <Link
      href={to}
      scroll={false}
      // prefetch={false} de propósito: abrir o e-mail o marca como lido,
      // e o pré-carregamento dos links faria isso sem a pessoa agir.
      prefetch={false}
      className={`glass-card group relative flex flex-col items-stretch justify-between gap-4 rounded-2xl p-4 sm:flex-row sm:items-center sm:p-5 ${
        opened ? "border-white/20! bg-white/[0.07]!" : ""
      } ${
        // E-mail resolvido fica mais apagado, mas o vidro do cartão é o mesmo de todos:
        // esmaecemos só o conteúdo, senão o padrão de fundo aparece através dele.
        message.handled_at ? "[&>*]:opacity-55" : ""
      }`}
    >
      {/* items-stretch no cartão no celular: senão a coluna se ajusta
          ao comprimento do assunto, e um assunto longo alarga a página toda
          além da tela — junto com o painel do e-mail. */}
      <span className="flex w-full min-w-0 flex-1 items-start gap-4">
        <span
          className={`tabular flex shrink-0 items-center justify-center rounded-xl px-2.5 py-1 font-mono text-xs font-bold ${priorityTone(message.priority)}`}
        >
          {message.priority ?? "—"}
        </span>

        <span className="min-w-0 flex-1">
          <span className="mb-0.5 flex items-center gap-2">
            {message.is_read ? null : (
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-link" aria-label="não lido" />
            )}
            <span
              className={`truncate text-xs tracking-tight text-white ${message.is_read ? "font-medium" : "font-semibold"}`}
            >
              {senderLabel(message.sender_name, message.sender)}
            </span>
          </span>
          <span className="mb-1 block truncate text-xs font-medium text-white/90 transition-colors group-hover:text-link">
            {message.subject || "(sem assunto)"}
          </span>
          {message.summary ? (
            <span className="line-clamp-1 text-[11px] text-white/50">{message.summary}</span>
          ) : null}

          <span className="mt-2.5 flex flex-wrap items-center gap-2">
            <span className="rounded-md bg-white/10 px-2 py-0.5 text-[10px] font-medium text-white/70">
              {categoryLabel(message.category)}
            </span>
            {/* Valor e prazo aparecem direto no cartão: para saber se são duzentos
                reais ou duzentos mil, não é preciso abrir o e-mail. */}
            {message.amount ? (
              <span className="tabular rounded-md bg-white/10 px-2 py-0.5 font-mono text-[10px] font-semibold text-white">
                {moneyLabel(message.amount, message.currency)}
              </span>
            ) : null}
            {message.deadline ? (
              <span className={`rounded-md border px-2 py-0.5 text-[10px] ${deadlineTone(message.deadline)}`}>
                {deadlineLabel(message.deadline)}
              </span>
            ) : null}
            {message.handled_at ? (
              <span className="rounded-md bg-ok/15 px-2 py-0.5 text-[10px] text-ok">✓ resolvido</span>
            ) : null}
            <span className="truncate font-mono text-[10px] text-white/40">{message.account.email}</span>
          </span>
        </span>
      </span>

      <span className="flex w-full shrink-0 items-center justify-between font-mono text-xs text-white/40 sm:w-auto sm:flex-col sm:items-end">
        <span>{whenLabel(message.sent_at)}</span>
        <ChevronRight
          className="h-4 w-4 text-white/30 transition-all group-hover:translate-x-0.5 group-hover:text-white"
          aria-hidden
        />
      </span>
    </Link>
  );
}

/**
 * Janela do e-mail sobre a lista — desce do topo, centralizada. Sem JavaScript: qual
 * e-mail está aberto fica registrado no endereço (?open=…), por isso o painel sobrevive
 * à atualização da página, e o "voltar" do navegador o fecha.
 */
function Sheet({ message, current, error }: { message: MessageFull; current: Search; error?: string }) {
  const close = href(current, { open: undefined });
  const here = href(current, {});

  return (
    <div className="fixed inset-0 z-50 overflow-hidden" role="dialog" aria-modal="true" aria-label={message.subject}>
      <EscapeClose href={close} />
      <Link
        href={close}
        scroll={false}
        aria-label="Fechar e-mail"
        className="veil absolute inset-0 bg-black/60 backdrop-blur-md"
      />

      {/* Janela centralizada: no celular ocupa a tela toda, em telas grandes vai até 3xl,
          sem passar da altura da tela; o texto do e-mail rola por dentro. */}
      <div className="pointer-events-none absolute inset-0 flex items-start justify-center sm:p-6">
        <div className="sheet glass-sheet pointer-events-auto flex h-full w-full max-w-3xl flex-col overflow-hidden sm:h-auto sm:max-h-full sm:rounded-3xl">
          <div className="glass flex items-center justify-between gap-3 border-b border-white/10 px-5 py-4 sm:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <ScoreCapsule priority={message.priority} />
              <CategoryTag category={message.category} />
            </div>
            <div className="flex items-center gap-2">
              <Link
                href={`/messages/${message.id}`}
                className="glass-button flex h-8 w-8 items-center justify-center rounded-full text-white/80 transition-colors hover:text-white"
                aria-label="Abrir em página separada"
                title="Abrir em página separada"
              >
                <ExternalLink className="h-4 w-4" aria-hidden />
              </Link>
              <Link
                href={close}
                scroll={false}
                className="glass-button flex h-8 w-8 items-center justify-center rounded-full text-white/80 transition-colors hover:text-white"
                aria-label="Fechar"
                title="Fechar (Esc)"
              >
                <X className="h-4 w-4" aria-hidden />
              </Link>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6">
            <MessageView message={message} back={here} done={close} error={error} />
          </div>
        </div>
      </div>
    </div>
  );
}

async function openedMessage(raw: string | undefined): Promise<MessageFull | null> {
  const id = Number(raw);
  if (!raw || !Number.isInteger(id) || id <= 0) return null;
  try {
    const message = await getMessage(id);
    // Abriu — então leu.
    if (!message.is_read) {
      await markRead(message.id);
      message.is_read = true;
    }
    return message;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export default async function InboxPage({ searchParams }: { searchParams: Promise<Search> }) {
  const current = await searchParams;
  const { error, toast } = current;
  const accountId = current.account ? Number(current.account) : undefined;
  const query = current.q?.trim() || undefined;

  // Abrimos o e-mail antes da lista: ele é marcado como lido,
  // e a lista sob o painel já o mostra como lido.
  const opened = await openedMessage(current.open);

  const [{ items: boxes }, { items, total }, counts] = await Promise.all([
    listAccounts(),
    listMessages({
      category: current.category,
      accountId,
      unreadOnly: Boolean(current.unread),
      query,
    }),
    getMessageCounts(accountId),
  ]);

  const heading = query ? "Busca" : current.category ? categoryLabel(current.category) : "Caixa de entrada";
  const headCount = query
    ? total
    : current.category
      ? tabCount(counts.categories[current.category], false)
      : counts.all.total;

  return (
    <div className="flex min-h-screen flex-col">
      <Nav active="inbox" query={current.q} />

      <main className="z-10 mx-auto flex w-full max-w-[1600px] flex-1 flex-col px-4 py-6 sm:px-6 sm:py-8">
        <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-white">
              <span>{heading}</span>
              <span className="tabular rounded-full bg-white/10 px-2.5 py-0.5 text-xs font-normal text-white/40">
                {headCount}
              </span>
            </h1>
            <p className="mt-1 text-xs text-white/40">
              {query ? (
                <>
                  E-mails encontrados para “{query}”: <span className="text-white/80">{total}</span>.
                  Buscamos em tudo, inclusive publicidade e spam; os mais recentes primeiro.{" "}
                  <Link
                    href={href({ ...current, q: undefined, open: undefined }, {})}
                    className="text-link hover:underline"
                  >
                    Limpar
                  </Link>
                </>
              ) : (
                <>
                  No topo, o que custa mais caro adiar. E-mails exibidos:{" "}
                  <span className="text-white/80">{items.length}</span>
                  {total > items.length ? ` de ${total}` : ""}
                </>
              )}
            </p>
          </div>

          <Link
            href="/brief"
            className="ai-button spring flex items-center gap-2 self-start rounded-xl px-4 py-2 text-xs font-semibold text-white shadow-lg hover:scale-[1.02] hover:shadow-ai-purple/25 sm:self-auto"
          >
            <Sparkles className="h-3.5 w-3.5" aria-hidden />
            Resumo com IA
          </Link>
        </div>

        {/* Em telas estreitas, a busca não fica no cabeçalho — fica aqui. */}
        <div className="mb-4 lg:hidden">
          <SearchBox query={current.q} compact />
        </div>

        {boxes.length > 0 && !query ? <Pills current={current} counts={counts} /> : null}
        {boxes.length > 0 ? <Boxes current={current} boxes={boxes} /> : null}

        {boxes.length === 0 ? (
          <Empty
            title="Nenhuma caixa de e-mail conectada"
            hint="Comece pelo e-mail que você mais lê."
            action={{ href: "/accounts", label: "Conectar e-mail" }}
          />
        ) : items.length === 0 ? (
          <Empty
            title={query ? "Nada encontrado" : "Nada por aqui"}
            hint={
              query
                ? "Buscamos em todos os e-mails, inclusive publicidade e spam. Tente menos palavras ou parte de uma palavra."
                : "Não há e-mails com este filtro."
            }
          />
        ) : (
          <div className="space-y-3 pb-16">
            {items.map((message) => (
              <Card
                key={message.id}
                message={message}
                to={href(current, { open: String(message.id) })}
                opened={opened?.id === message.id}
              />
            ))}
          </div>
        )}
      </main>

      {opened ? <Sheet message={opened} current={current} error={error} /> : null}
      <Toast kind={toast} />
    </div>
  );
}

function Empty({
  title,
  hint,
  action,
}: {
  title: string;
  hint: string;
  action?: { href: string; label: string };
}) {
  return (
    <div className="glass-card rounded-2xl py-16 text-center">
      <Inbox className="mx-auto mb-2 h-8 w-8 text-white/30" aria-hidden />
      <p className="text-sm font-medium text-white">{title}</p>
      <p className="mt-1 text-xs text-white/50">{hint}</p>
      {action ? (
        <Link
          href={action.href}
          className="spring mt-5 inline-block rounded-xl bg-link px-4 py-2 text-xs font-medium text-white hover:bg-link/80"
        >
          {action.label}
        </Link>
      ) : null}
    </div>
  );
}
