import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CategoryTag, MessageView, ScoreCapsule } from "@/components/message-view";
import { Nav } from "@/components/nav";
import { Toast } from "@/components/toast";
import { ApiError, getMessage, markRead, type MessageFull } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * E-mail em página própria — para links do Resumo e de "Dinheiro e prazos".
 * Na Caixa de entrada, o e-mail abre em um painel sobre a lista; o conteúdo
 * é o mesmo — MessageView.
 */
export default async function MessagePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string; toast?: string }>;
}) {
  const { id } = await params;
  const { error, toast } = await searchParams;
  let message: MessageFull;
  try {
    message = await getMessage(Number(id));
  } catch (error) {
    // E-mail inexistente ou de outra pessoa — para o usuário dá no mesmo:
    // "não encontrado", e não "o site quebrou".
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  // Abriu, então leu. Um botão separado de "lido" aqui seria desnecessário.
  if (!message.is_read) await markRead(message.id);

  return (
    <div>
      <Nav active="inbox" />

      <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6">
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-xs text-ink-faint transition-colors hover:text-white"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            Voltar para todos os e-mails
          </Link>
          <span className="ml-auto flex items-center gap-2">
            <ScoreCapsule priority={message.priority} />
            <CategoryTag category={message.category} />
          </span>
        </div>

        <MessageView message={message} back={`/messages/${message.id}`} done="/" error={error} />
      </main>

      <Toast kind={toast} />
    </div>
  );
}
