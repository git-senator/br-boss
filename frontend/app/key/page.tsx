import { ExternalLink, KeyRound, Lock } from "lucide-react";

import { changePasswordAction, removeAiKeyAction, saveAiKeyAction } from "@/app/actions";
import { Nav } from "@/components/nav";
import { PendingButton } from "@/components/pending-button";
import { me } from "@/lib/api";

export const dynamic = "force-dynamic";

const STUDIO = "https://aistudio.google.com/apikey";

/**
 * Chave própria do Gemini. Se existir, os e-mails das caixas desta pessoa,
 * seus rascunhos e regras rodam por conta dela. Se não, usa a chave do
 * servidor, caso o servidor a compartilhe.
 */
export default async function KeyPage({
  searchParams,
}: {
  searchParams: Promise<{
    error?: string;
    saved?: string;
    removed?: string;
    password?: string;
    password_error?: string;
  }>;
}) {
  const { error, saved, removed, password, password_error: passwordError } = await searchParams;
  const who = await me();
  const hint = who.ai_key_hint;

  return (
    <div>
      <Nav />

      <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
        <h1 className="text-2xl font-bold tracking-tight text-white">Chave de IA</h1>
        <p className="mt-1 text-sm text-ink-dim">
          Sua própria chave do Gemini: a análise dos seus e-mails, os rascunhos de resposta e as
          regras rodam por sua conta e dentro dos seus limites.
        </p>

        <section className="glass-card mt-5 rounded-2xl p-5">
          <div className="flex items-start gap-3">
            <span
              className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${
                hint ? "bg-ok/15 text-ok" : who.ai_shared_key ? "bg-white/10 text-ink-dim" : "bg-warn/15 text-warn"
              }`}
            >
              <KeyRound className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              {hint ? (
                <>
                  <p className="font-medium text-ink">
                    Usando sua chave <span className="font-mono text-white">{hint}</span>
                  </p>
                  <p className="mt-0.5 text-sm text-ink-dim">
                    Os e-mails das suas caixas são analisados com esta chave.
                  </p>
                </>
              ) : who.ai_shared_key ? (
                <>
                  <p className="font-medium text-ink">No momento, está em uso a chave do servidor</p>
                  <p className="mt-0.5 text-sm text-ink-dim">
                    Tudo já está funcionando — não é obrigatório informar sua própria chave.
                  </p>
                </>
              ) : (
                <>
                  <p className="font-medium text-ink">Nenhuma chave própria cadastrada</p>
                  <p className="mt-0.5 text-sm text-ink-dim">
                    Os e-mails chegam, mas a IA só começa a analisá-los depois que você colar uma chave.
                  </p>
                </>
              )}
            </div>
          </div>

          <form action={saveAiKeyAction} className="mt-5 flex flex-col gap-2 sm:flex-row">
            <input
              name="key"
              type="password"
              required
              autoComplete="off"
              spellCheck={false}
              placeholder="AIza…"
              aria-label="Chave do Gemini"
              className="field font-mono"
            />
            <button type="submit" className="btn-main shrink-0">
              {hint ? "Substituir" : "Salvar"}
            </button>
          </form>

          {error ? <p className="note-bad mt-3">{error}</p> : null}
          {saved ? <p className="note-ok mt-3">Chave verificada e salva.</p> : null}
          {removed ? <p className="note-ok mt-3">Chave excluída.</p> : null}

          {hint ? (
            <form action={removeAiKeyAction} className="mt-3">
              <button className="text-sm text-ink-faint transition-colors duration-150 hover:text-alarm">
                Excluir minha chave
              </button>
            </form>
          ) : null}
        </section>

        <section className="glass-card mt-5 rounded-2xl p-5">
          <h2 className="font-semibold text-white">Como obter a chave — leva dois minutos</h2>
          <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm text-ink-dim">
            <li>
              Acesse o{" "}
              <a
                href={STUDIO}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-link underline decoration-link/40 underline-offset-2 hover:decoration-link"
              >
                Google AI Studio
                <ExternalLink className="h-3 w-3" aria-hidden />
              </a>{" "}
              (aistudio.google.com) e entre com sua Conta do Google.
            </li>
            <li>
              Clique em “Get API key” (ou “Criar chave de API”) e copie a chave — ela começa
              com “AIza”.
            </li>
            <li>Cole a chave no campo acima e clique em “Salvar”.</li>
          </ol>
          <p className="mt-4 text-xs leading-relaxed text-ink-faint">
            A chave fica armazenada com criptografia e nunca mais é exibida por completo. A chave
            gratuita tem um limite diário; no plano gratuito, o Google pode usar as solicitações
            para aprimorar os próprios modelos. Para e-mails de trabalho, é melhor ativar o
            faturamento no AI Studio — a análise custa uma fração de centavo por e-mail.
          </p>
        </section>

        {/* Trocar a senha derruba as outras sessões abertas — inclusive uma roubada. */}
        <section id="senha" className="glass-card mt-5 scroll-mt-24 rounded-2xl p-5">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/10 text-ink-dim">
              <Lock className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <h2 className="font-semibold text-white">Alterar senha</h2>
              <p className="mt-0.5 text-sm text-ink-dim">
                Os outros aparelhos saem da conta; este continua conectado.
              </p>
            </div>
          </div>

          <form action={changePasswordAction} className="mt-5 flex flex-col gap-2">
            <input
              name="current"
              type="password"
              required
              autoComplete="current-password"
              placeholder="Senha atual"
              aria-label="Senha atual"
              className="field"
            />
            <input
              name="password"
              type="password"
              required
              minLength={10}
              autoComplete="new-password"
              placeholder="Nova senha (pelo menos 10 caracteres)"
              aria-label="Nova senha"
              className="field"
            />
            <input
              name="again"
              type="password"
              required
              minLength={10}
              autoComplete="new-password"
              placeholder="Repita a nova senha"
              aria-label="Repita a nova senha"
              className="field"
            />
            <PendingButton className="btn-main self-start" pending="Salvando…">
              Alterar senha
            </PendingButton>
          </form>

          {passwordError ? <p className="note-bad mt-3">{passwordError}</p> : null}
          {password ? <p className="note-ok mt-3">Senha alterada.</p> : null}
        </section>
      </main>
    </div>
  );
}
