import { RefreshCw, Send, Sparkles } from "lucide-react";

import { draftAction, reopenAction, sendReplyAction } from "@/app/actions";
import { PendingButton } from "@/components/pending-button";
import type { MessageFull, ReplyRow } from "@/lib/api";
import { untilLabel, whenLabel } from "@/lib/format";

const FIELD =
  "glass-pill w-full rounded-xl px-3.5 py-2.5 text-xs text-white placeholder:text-white/35 focus:border-link/60! focus:ring-2 focus:ring-link/25 focus:outline-none";
const QUIET =
  "spring inline-flex items-center gap-1.5 rounded-xl bg-white/10 px-3.5 py-1.5 text-xs font-medium text-white/90 hover:bg-white/15";
const MAIN =
  "spring inline-flex items-center gap-1.5 rounded-xl bg-link px-4 py-1.5 text-xs font-medium text-white shadow-md hover:bg-link/80";

function Hidden({ message, back }: { message: MessageFull; back: string }) {
  return (
    <>
      <input type="hidden" name="message_id" value={message.id} />
      <input type="hidden" name="back" value={back} />
    </>
  );
}

function SentReply({ reply }: { reply: ReplyRow }) {
  return (
    <details className="glass-card rounded-2xl px-4 py-3">
      <summary className="cursor-pointer text-xs text-ink">
        <span className="text-ok">✓</span> Resposta enviada {whenLabel(reply.sent_at)} para {reply.to}
        {reply.ai_text ? "" : " · escrita manualmente"}
      </summary>
      <pre className="mt-2 font-sans text-xs leading-relaxed break-words whitespace-pre-wrap text-ink-dim">
        {reply.final_text ?? reply.ai_text}
      </pre>
    </details>
  );
}

function Notice({
  message,
  back,
  text,
  button,
}: {
  message: MessageFull;
  back: string;
  text: string;
  button: string;
}) {
  return (
    <div className="glass-card flex flex-wrap items-center gap-3 rounded-2xl px-4 py-3">
      <span className="text-xs text-ink-dim">{text}</span>
      <form action={reopenAction}>
        <Hidden message={message} back={back} />
        <button className={QUIET}>{button}</button>
      </form>
    </div>
  );
}

/**
 * "Resposta inteligente": um campo, dois botões. Dá para escrever e enviar,
 * ou pedir um rascunho à IA e ajustá-lo. O que estiver no campo ao clicar
 * em "Enviar" é o que sai. Sem o clique, nada é enviado.
 */
export function ReplyPanel({
  message,
  back,
  error,
}: {
  message: MessageFull;
  back: string;
  error?: string;
}) {
  const sent = message.replies.filter((reply) => reply.status === "sent");
  const open = [...message.replies].reverse().find((r) => r.status === "draft" || r.status === "failed");
  const snoozed = message.snoozed_until && new Date(message.snoozed_until) > new Date();
  const text = open ? (open.final_text ?? open.ai_text) : "";

  return (
    <section id="reply" className="scroll-mt-4 space-y-3">
      {sent.map((reply) => (
        <SentReply key={reply.id} reply={reply} />
      ))}

      {message.handled_at && !open ? (
        <Notice
          message={message}
          back={back}
          text={sent.length > 0 ? "E-mail resolvido: a resposta foi enviada." : "E-mail marcado como sem necessidade de resposta."}
          button="Voltar para pendências"
        />
      ) : null}

      {snoozed ? (
        <Notice
          message={message}
          back={back}
          text={`Adiado: volta para a lista ${untilLabel(message.snoozed_until)}.`}
          button="Trazer de volta agora"
        />
      ) : null}

      {message.handled_at && !open ? null : (
        <form action={sendReplyAction} className="space-y-2">
          <Hidden message={message} back={back} />
          <input type="hidden" name="reply_id" value={open?.id ?? ""} />

          <label htmlFor="reply-text" className="flex items-center justify-between text-xs font-medium text-ink-dim">
            <span>
              {open
                ? `Rascunho da IA${open.language ? ` · ${open.language}` : ""}: ajuste se necessário`
                : "Resposta inteligente"}
            </span>
          </label>

          {open ? (
            <div className="grid gap-2 sm:grid-cols-2">
              <input name="to" defaultValue={open.to} required aria-label="Para" className={FIELD} />
              <input name="subject" defaultValue={open.subject} aria-label="Assunto" className={FIELD} />
            </div>
          ) : (
            <>
              <input type="hidden" name="to" value={message.answer_to} />
              <input type="hidden" name="subject" value="" />
            </>
          )}

          <textarea
            id="reply-text"
            name="text"
            required
            rows={open ? Math.min(16, Math.max(5, text.split("\n").length + 2)) : 3}
            defaultValue={text}
            placeholder="Escreva sua resposta ou clique em “Gerar” para a IA preparar um rascunho"
            className={`${FIELD} leading-relaxed`}
          />

          {open?.note ? <p className="text-xs text-watch">{open.note}</p> : null}
          {open && /\[[^\]]+\]/.test(text) ? (
            <p className="text-[11px] text-ink-faint">
              Entre colchetes [ … ] está o que a IA não sabe. Substitua antes de enviar.
            </p>
          ) : null}

          {open?.status === "failed" && open.error ? (
            <p className="rounded-xl border border-alarm/40 bg-alarm/10 px-3 py-2 text-xs text-ink">
              Não foi enviado: {open.error}
            </p>
          ) : null}
          {error ? (
            <p className="rounded-xl border border-alarm/40 bg-alarm/10 px-3 py-2 text-xs text-ink">{error}</p>
          ) : null}

          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="mr-auto text-[11px] text-ink-faint">
              Para: {open?.to ?? message.answer_to} · da conta {message.account.email}
            </span>
            <PendingButton
              formAction={draftAction}
              formNoValidate
              name="regenerate"
              value={open ? "1" : "0"}
              className={QUIET}
              pending={
                <>
                  <Sparkles className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  A IA está escrevendo…
                </>
              }
            >
              {open ? <RefreshCw className="h-3.5 w-3.5" aria-hidden /> : <Sparkles className="h-3.5 w-3.5" aria-hidden />}
              {open ? "Outro rascunho" : "Gerar"}
            </PendingButton>
            <PendingButton
              name="send"
              value="1"
              className={MAIN}
              pending={
                <>
                  <Send className="h-3.5 w-3.5 animate-pulse" aria-hidden />
                  Enviando…
                </>
              }
            >
              <Send className="h-3.5 w-3.5" aria-hidden />
              {open?.status === "failed" ? "Enviar novamente" : "Enviar"}
            </PendingButton>
          </div>
        </form>
      )}
    </section>
  );
}
