import { ApiError, errorText, fetchAttachment } from "@/lib/api";
import { ATTACHMENT_ERROR, isOwnPath } from "@/lib/format";
import { getToken } from "@/lib/session";

/**
 * Baixar um anexo do e-mail. O navegador não fala direto com a API (a API
 * só escuta em 127.0.0.1, e o token fica num cookie httpOnly), então os
 * bytes passam pelo servidor Next: ele coloca o token e repassa a resposta
 * da API em fluxo, sem montar o arquivo na memória.
 *
 * Cabeçalhos — só os que a API escolheu, mais a proibição de adivinhar o
 * tipo e de guardar em cache: o anexo pode ter sido mandado por qualquer
 * um, e o cache de um computador alheio não é lugar para ele.
 */

const PASSED_HEADERS = ["content-type", "content-disposition", "content-length"];

// É assim que a API responde ao que é de outra pessoa ou não existe — é só um 404.
// Qualquer outro texto no 404 («o e-mail não está mais na caixa») nós explicamos.
const NOT_FOUND_DETAILS = new Set(["Anexo não encontrado", "E-mail não encontrado"]);

function notFound(): Response {
  return new Response("Não encontrado", {
    status: 404,
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "private, no-store" },
  });
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; attachmentId: string }> },
): Promise<Response> {
  const { id, attachmentId } = await params;
  const messageId = Number(id);
  const fileId = Number(attachmentId);
  // Sem login o anexo simplesmente não existe — assim como o e-mail de outra pessoa.
  const token = await getToken();
  if (!token || !Number.isInteger(messageId) || !Number.isInteger(fileId)) return notFound();

  const url = new URL(request.url);
  const backParam = url.searchParams.get("back") ?? "";
  const back = isOwnPath(backParam) ? backParam : `/messages/${messageId}`;

  let upstream: Response;
  try {
    upstream = await fetchAttachment(messageId, fileId, token);
  } catch {
    return explain(back, "O servidor de e-mail está fora do ar agora. Tente de novo daqui a um minuto.");
  }

  if (upstream.status === 401 || upstream.status === 404) {
    const body = await upstream.json().catch(() => null);
    const detail: unknown = body?.detail;
    // «O e-mail não está mais na caixa» não é «sem acesso»: a pessoa precisa
    // saber o que aconteceu.
    if (upstream.status === 404 && typeof detail === "string" && !NOT_FOUND_DETAILS.has(detail)) {
      return explain(back, detail);
    }
    return notFound();
  }
  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.json().catch(() => null);
    return explain(back, errorText(new ApiError(upstream.status, detail?.detail ?? null)));
  }

  const headers = new Headers({
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, no-store",
  });
  for (const name of PASSED_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Por garantia: responda a API o que for, o navegador não pode abrir o
  // arquivo como uma página do nosso site.
  if (!headers.get("content-disposition")?.startsWith("attachment")) {
    headers.set("Content-Disposition", "attachment");
  }
  if (!headers.get("content-type")) headers.set("Content-Type", "application/octet-stream");

  return new Response(upstream.body, { status: 200, headers });
}

/**
 * Não deu certo — voltamos ao e-mail com uma explicação junto à lista de
 * anexos, em vez de mostrar uma página de erro crua no lugar do e-mail.
 */
function explain(back: string, text: string): Response {
  const [base, hash] = back.split("#");
  const joined = `${base}${base.includes("?") ? "&" : "?"}error=${encodeURIComponent(ATTACHMENT_ERROR + text)}`;
  // Endereço relativo: atrás do nginx, o servidor Next não sabe o próprio
  // nome externo, e um endereço absoluto levaria para o localhost.
  return new Response(null, {
    status: 303,
    headers: { Location: hash ? `${joined}#${hash}` : joined, "Cache-Control": "private, no-store" },
  });
}
