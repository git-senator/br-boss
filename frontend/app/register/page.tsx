import Link from "next/link";

import { registerAction } from "@/app/actions";
import { LogoMark } from "@/components/logo-mark";

export const dynamic = "force-dynamic";

/**
 * Cadastro próprio por link. Quem se cadastra vê apenas os próprios e-mails:
 * as caixas de outras pessoas ficam inacessíveis (app.security no servidor).
 */
export default async function RegisterPage({
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
        <h1 className="mt-5 text-lg font-semibold text-white">Criar conta</h1>
        <p className="mt-1 text-sm text-ink-dim">
          Seus e-mails ficarão visíveis só para você — para mais ninguém neste site.
        </p>

        <form action={registerAction} className="mt-6 space-y-4">
          <label className="block">
            <span className="text-xs font-medium text-ink-dim">E-mail de acesso</span>
            <input name="email" type="email" autoComplete="username" required className="field mt-1" />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink-dim">Senha</span>
            <input
              name="password"
              type="password"
              autoComplete="new-password"
              minLength={10}
              required
              placeholder="no mínimo 10 caracteres"
              className="field mt-1"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink-dim">Confirme a senha</span>
            <input
              name="again"
              type="password"
              autoComplete="new-password"
              minLength={10}
              required
              className="field mt-1"
            />
          </label>

          {error ? <p className="note-bad">{error}</p> : null}

          <button type="submit" className="btn-main w-full py-2.5!">
            Criar conta
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-ink-dim">
          Já tem uma conta?{" "}
          <Link href="/login" className="text-link hover:underline">
            Entrar
          </Link>
        </p>
      </div>
    </main>
  );
}
