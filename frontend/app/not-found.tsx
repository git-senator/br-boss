import Link from "next/link";

import { LogoMark } from "@/components/logo-mark";

/** «Não encontrado» no estilo do app — em vez da página crua do Next. */
export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="glass-card w-full max-w-sm rounded-3xl p-8 text-center">
        <div className="flex justify-center">
          <LogoMark size="lg" />
        </div>
        <h1 className="mt-5 text-lg font-semibold text-white">Não encontrado</h1>
        <p className="mt-1 text-sm text-ink-dim">
          Esta página ou este e-mail não existe — ou não é seu.
        </p>
        <Link href="/" className="btn-main mt-6 inline-block">
          Voltar para todos os e-mails
        </Link>
      </div>
    </main>
  );
}
