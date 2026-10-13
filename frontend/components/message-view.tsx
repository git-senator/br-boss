import { Archive, Clock, Languages, Paperclip, Sparkles } from "lucide-react";

import { draftAction, ignoreAction, snoozeAction, translateAction } from "@/app/actions";
import { LetterBody } from "@/components/letter-body";
import { PendingButton } from "@/components/pending-button";
import { ReplyPanel } from "@/components/reply-panel";
import type { MessageFull } from "@/lib/api";
import {
  categoryLabel,
  deadlineLabel,
  deadlineTone,
  fileSize,
  isMostlyPortuguese,
  moneyLabel,
  senderLabel,
  TRANSLATE_ERROR,
  whenLabel,
} from "@/lib/format";

const PILL =
  "spring inline-flex items-center gap-1.5 rounded-xl bg-white/10 px-3.5 py-1.5 text-xs font-medium text-white/90 hover:bg-white/15";

// "Lembrar": três prazos simples em vez de um calendário.
const LATER = [
  { hours: 24, label: "Amanhã" },
  { hours: 72, label: "Em 3 dias" },
  { hours: 168, label: "Em 1 semana" },
];

function Hidden({ id, back, done }: { id: number; back: string; done: string }) {
  return (
    <>
      <input type="hidden" name="message_id" value={id} />
      <input type="hidden" name="back" value={back} />
      <input type="hidden" name="done" value={done} />
    </>
  );
}

/**
 * Análise da IA em moldura arco-íris: o essencial, valores, prazo e três ações rápidas.
 * A moldura separa a opinião do modelo do próprio e-mail.
 */
function AiBox({ message, back, done }: { message: MessageFull; back: string; done: string }) {
  const open = message.replies.some((r) => r.status === "draft" || r.status === "failed");
  const decided = Boolean(message.handled_at);

  return (
    <div className="ai-frame p-5 shadow-2xl">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-xs font-semibold tracking-wide text-white">
          <Sparkles className="h-4 w-4 text-ai-purple" aria-hidden />
          Análise da IA
        </span>
        <span className="truncate text-[10px] text-ink-faint">{message.account.email}</span>
      </div>

      <p className="text-xs leading-relaxed text-white/80">
        {message.summary ||
          (message.category
            ? "Sem resumo: o e-mail foi classificado por uma regra, sem o modelo."
            : "Este e-mail ainda não foi analisado. A avaliação aparece na próxima verificação.")}
      </p>

      {message.amount || message.deadline || message.action_required || message.folder === "spam" ? (
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
          {message.amount ? (
            <span className="tabular rounded-md bg-white/10 px-2 py-0.5 font-mono font-semibold text-white">
              {moneyLabel(message.amount, message.currency)}
            </span>
          ) : null}
          {message.deadline ? (
            <span className={`rounded-md border px-2 py-0.5 ${deadlineTone(message.deadline)}`}>
              {deadlineLabel(message.deadline)}
            </span>
          ) : null}
          {message.action_required ? (
            <span className="rounded-md bg-link/15 px-2 py-0.5 text-link">requer resposta ou ação</span>
          ) : null}
          {message.folder === "spam" ? (
            <span className="rounded-md bg-alarm/15 px-2 py-0.5 text-alarm">da pasta Spam</span>
          ) : null}
        </div>
      ) : null}

      {decided ? null : (
        <div className="mt-4 flex flex-wrap gap-2 border-t border-white/10 pt-3">
          {open ? (
            <a href="#reply" className="spring inline-flex items-center gap-1.5 rounded-xl bg-link px-3.5 py-1.5 text-xs font-medium text-white shadow-md hover:bg-link/80">
              <Sparkles className="h-3.5 w-3.5" aria-hidden />Ver rascunho
            </a>
          ) : (
            <form action={draftAction}>
              <Hidden id={message.id} back={back} done={done} />
              <PendingButton
                className="spring inline-flex items-center gap-1.5 rounded-xl bg-link px-3.5 py-1.5 text-xs font-medium text-white shadow-md hover:bg-link/80"
                pending={
                  <>
                    <Sparkles className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    A IA está escrevendo…
                  </>
                }
              >
                <Sparkles className="h-3.5 w-3.5" aria-hidden />
                Preparar resposta
              </PendingButton>
            </form>
          )}

          <details className="relative">
            <summary className={`${PILL} cursor-pointer list-none [&::-webkit-details-marker]:hidden`}>
              <Clock className="h-3.5 w-3.5" aria-hidden />
              Lembrar
            </summary>
            <div className="menu absolute left-0 z-20 mt-2 w-44 rounded-2xl p-1.5">
              {LATER.map((option) => (
                <form key={option.hours} action={snoozeAction}>
                  <Hidden id={message.id} back={back} done={done} />
                  <input type="hidden" name="hours" value={option.hours} />
                  <button className="w-full rounded-xl px-3 py-2 text-left text-xs text-ink hover:bg-white/10">
                    {option.label}
                  </button>
                </form>
              ))}
            </div>
          </details>

          <form action={ignoreAction}>
            <Hidden id={message.id} back={back} done={done} />
            <button className={PILL} title="Sem resposta. O e-mail vai para o fim da lista.">
              <Archive className="h-3.5 w-3.5" aria-hidden />
              Ignorar
            </button>
          </form>
        </div>
      )}
    </div>
  );
}

/** Índice de prioridade em cápsula, como na lista, só que maior. */
export function ScoreCapsule({ priority }: { priority: number | null }) {
  const tone =
    priority === null
      ? "border-white/10 bg-white/10 text-ink-dim"
      : priority >= 80
        ? "border-alarm/30 bg-alarm/20 text-alarm"
        : priority >= 60
          ? "border-warn/30 bg-warn/20 text-warn"
          : priority >= 40
            ? "border-watch/30 bg-watch/20 text-watch"
            : "border-white/10 bg-white/10 text-ink-dim";
  return (
    <span className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold ${tone}`}>
      <span>Índice</span>
      <span className="tabular">{priority ?? "—"}</span>
    </span>
  );
}

export function CategoryTag({ category }: { category: string | null }) {
  return (
    <span className="rounded-full bg-white/10 px-2.5 py-0.5 text-xs font-medium text-white/80">
      {categoryLabel(category)}
    </span>
  );
}

/**
 * O e-mail completo: análise da IA, cabeçalho, texto e resposta. O mesmo
 * componente serve no painel sobre a lista e na página própria do e-mail.
 *
 * back: para onde voltar após uma ação (aqui mesmo); done: para onde ir
 * quando o e-mail for resolvido ("Ignorar", "Lembrar").
 */
export function MessageView({
  message,
  back,
  done,
  error,
}: {
  message: MessageFull;
  back: string;
  done: string;
  error?: string;
}) {
  // Erro de tradução aparece junto ao botão de traduzir; os demais, junto à resposta.
  const translateError = error?.startsWith(TRANSLATE_ERROR) ? error.slice(TRANSLATE_ERROR.length) : null;
  const foreign = !isMostlyPortuguese(`${message.subject} ${message.body_text}`);
  const subjectRu = message.subject_translated && message.subject_translated !== message.subject ? message.subject_translated : null;

  return (
    <div className="space-y-6">
      <AiBox message={message} back={back} done={done} />

      <div>
        <h2 className="mb-2 text-xl leading-snug font-bold break-words text-white">
          {subjectRu ?? (message.subject || "(sem assunto)")}
        </h2>
        {subjectRu ? (
          <p className="-mt-1 mb-2 text-xs break-words text-ink-faint" title="Assunto original">
            {message.subject}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-2 border-y border-white/10 py-2 text-xs text-ink-dim">
          <div className="min-w-0">
            <a
              href={`mailto:${message.sender}`}
              className="font-medium text-white/80 transition-colors hover:text-link"
              title={message.sender}
            >
              {senderLabel(message.sender_name, message.sender)}
            </a>
            <span className="ml-2 text-ink-faint">&lt;{message.sender}&gt;</span>
          </div>
          <span className="font-mono">{whenLabel(message.sent_at)}</span>
        </div>
      </div>

      {message.attachments.length > 0 ? (
        <ul className="flex flex-wrap gap-2">
          {message.attachments.map((file) => (
            <li
              key={file.id}
              className="glass-pill flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs text-ink-dim"
            >
              <Paperclip className="h-3.5 w-3.5" aria-hidden />
              {file.filename} · {fileSize(file.size_bytes)}
            </li>
          ))}
        </ul>
      ) : null}

      {foreign && !message.body_translated ? (
        <form action={translateAction} className="flex flex-wrap items-center justify-end gap-3">
          <Hidden id={message.id} back={back} done={done} />
          {translateError ? <span className="text-xs text-alarm">{translateError}</span> : null}
          <PendingButton
            className={PILL}
            pending={
              <>
                <Languages className="h-3.5 w-3.5 animate-pulse" aria-hidden />
                Traduzindo…
              </>
            }
            title="O assunto e o texto serão traduzidos. O original continua disponível: dá para alternar com um clique."
          >
            <Languages className="h-3.5 w-3.5" aria-hidden />
            Traduzir para português
          </PendingButton>
        </form>
      ) : null}

      <LetterBody original={message.body_text} translated={message.body_translated} />

      <ReplyPanel message={message} back={back} error={translateError ? undefined : error} />
    </div>
  );
}
