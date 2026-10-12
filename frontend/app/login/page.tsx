import Link from "next/link";

import { loginAction } from "@/app/actions";
import { LogoMark } from "@/components/logo-mark";

export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-8">
      <div className="glass-card w-full max-w-sm rounded-3xl border border-white/[0.13] p-8">
        <div className="flex items-center gap-3">
          <LogoMark size="lg" />
          <span className="flex items-center gap-1.5">
            <span className="text-xl font-bold tracking-tight text-white">BR BOSS</span>
            <span className="rounded-full border border-white/10 bg-white/10 px-1.5 text-[10px] font-semibold text-white/80">
              AI
            </span>
          </span>
        </div>
        <p className="mt-3 text-sm text-ink-dim">Todos os seus e-mails em uma única lista</p>

        <form action={loginAction} className="mt-8 space-y-4">
          <label className="block">
            <span className="text-xs font-medium text-ink-dim">E-mail</span>
            <input name="email" type="email" autoComplete="username" required className="field mt-1" />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink-dim">Senha</span>
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              className="field mt-1"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink-dim">Código do app autenticador</span>
            <input
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="se estiver ativado"
              className="field mt-1"
            />
          </label>

          {/* Chave própria é opcional: sem ela, usa-se a chave do servidor.
              Fica recolhida para não assustar quem não precisa dela. */}
          <details className="group">
            <summary className="cursor-pointer list-none text-xs font-medium text-ink-dim transition-colors hover:text-white [&::-webkit-details-marker]:hidden">
              <span className="mr-1 inline-block transition-transform group-open:rotate-90">›</span>
              Sua chave do Gemini — opcional
            </summary>
            <input
              name="ai_key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="AIza…"
              aria-label="Sua chave do Gemini"
              className="field mt-2 font-mono"
            />
            <p className="mt-1.5 text-[11px] leading-relaxed text-ink-faint">
              Assim, seus e-mails são analisados por sua conta. A chave é obtida no Google AI
              Studio; você pode trocá-la depois no menu do seu avatar.
            </p>
          </details>

          {error ? <p className="note-bad">{error}</p> : null}

          <button type="submit" className="btn-main w-full py-2.5!">
            Entrar
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-ink-dim">
          Não tem uma conta?{" "}
          <Link href="/register" className="text-link hover:underline">
            Criar conta
          </Link>
        </p>
      </div>
    </main>
  );
}
