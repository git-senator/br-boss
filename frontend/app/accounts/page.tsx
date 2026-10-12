import Link from "next/link";

import { deleteAccountAction, toggleAccountAction } from "@/app/actions";
import { AddMailbox } from "@/components/add-mailbox";
import { Nav } from "@/components/nav";
import { listAccounts, listServices, me, type Mailbox } from "@/lib/api";
import { whenLabel } from "@/lib/format";

export const dynamic = "force-dynamic";

function Status({ box }: { box: Mailbox }) {
  if (box.last_error) {
    return <span className="text-sm text-alarm">Falha na conexão: {box.last_error}</span>;
  }
  if (!box.is_active) return <span className="text-sm text-ink-faint">Verificação pausada</span>;
  return (
    <span className="text-sm text-ink-dim">
      {box.last_synced_at ? `Verificada ${whenLabel(box.last_synced_at)}` : "Aguardando a primeira verificação"}
    </span>
  );
}

export default async function AccountsPage({
  searchParams,
}: {
  searchParams: Promise<{
    error?: string;
    remove?: string;
    added?: string;
    bad?: string | string[];
    welcome?: string;
  }>;
}) {
  const { error, remove, added, bad, welcome } = await searchParams;
  const problems = bad === undefined ? [] : Array.isArray(bad) ? bad : [bad];
  const [{ items: boxes }, { items: services }, who] = await Promise.all([
    listAccounts(),
    listServices(),
    me(),
  ]);
  const needsKey = !who.ai_key_hint && !who.ai_shared_key;

  return (
    <div>
      <Nav active="accounts" />

      <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
        {welcome ? (
          <section className="glass-card mb-6 rounded-2xl p-5">
            <h2 className="font-semibold text-white">Conta criada — faltam só dois passos para tudo funcionar</h2>
            <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm text-ink-dim">
              <li>Conecte suas caixas de e-mail abaixo — endereço e senha de app.</li>
              {needsKey ? (
                <li>
                  Cole sua chave do Gemini na página{" "}
                  <Link href="/key" className="text-link hover:underline">
                    “Chave de IA”
                  </Link>{" "}
                  — sem ela, os e-mails chegam, mas a IA não os analisa.
                </li>
              ) : null}
            </ol>
            <p className="mt-3 text-xs text-ink-faint">
              Seus e-mails ficam visíveis só para você — para mais ninguém neste site.
            </p>
          </section>
        ) : null}

        <h1 className="text-2xl font-bold tracking-tight text-white">Caixas de e-mail</h1>
        <p className="mt-1 text-sm text-ink-dim">
          Caixas conectadas: {boxes.length}. Os e-mails são verificados a cada minuto.
        </p>

        <ul className="glass-card mt-5 divide-y divide-white/10 overflow-hidden rounded-2xl">
          {boxes.map((box) => (
            <li key={box.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-ink">{box.email}</p>
                <p className="text-xs text-ink-faint">{box.service}</p>
                <Status box={box} />
              </div>

              {String(remove) === String(box.id) ? (
                <div className="flex items-center gap-2">
                  <span className="text-sm text-alarm">Excluir junto com os e-mails?</span>
                  <form action={deleteAccountAction}>
                    <input type="hidden" name="id" value={box.id} />
                    <button className="btn-danger">
                      Sim, excluir
                    </button>
                  </form>
                  <Link
                    href="/accounts"
                    className="text-sm text-ink-dim transition-colors duration-150 hover:text-ink"
                  >
                    Cancelar
                  </Link>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <form action={toggleAccountAction}>
                    <input type="hidden" name="id" value={box.id} />
                    <input type="hidden" name="is_active" value={String(!box.is_active)} />
                    <button className="btn-quiet">
                      {box.is_active ? "Pausar" : "Retomar"}
                    </button>
                  </form>
                  <Link
                    href={`/accounts?remove=${box.id}`}
                    className="rounded-xl px-3 py-1.5 text-sm text-ink-faint transition-colors duration-150 hover:text-alarm"
                  >
                    Excluir
                  </Link>
                </div>
              )}
            </li>
          ))}

          {boxes.length === 0 ? (
            <li className="px-4 py-6 text-center text-sm text-ink-dim">Nenhuma caixa de e-mail ainda.</li>
          ) : null}
        </ul>

        {added !== undefined ? (
          <div className="mt-4 space-y-2">
            {Number(added) > 0 ? (
              <p className="note-ok">
                Caixas conectadas: {added}. Os e-mails começam a chegar em até um minuto.
              </p>
            ) : null}
            {problems.length > 0 ? (
              <div className="note-bad">
                <p className="font-medium">Não foi possível conectar:</p>
                <ul className="mt-1 space-y-1 text-ink-dim">
                  {problems.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}

        <h2 className="mt-6 text-lg font-semibold text-ink">Adicionar e-mail</h2>
        <div className="mt-2">
          <AddMailbox services={services} error={error} />
        </div>
      </main>
    </div>
  );
}
