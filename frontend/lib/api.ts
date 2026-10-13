import { redirect } from "next/navigation";

import type { InboxCounts, RuleShape } from "./format";
import { getToken } from "./session";

const API_URL = process.env.API_URL ?? "http://api:8000";

export type MailboxLabel = {
  id: number;
  email: string;
  service: string;
};

export type MessageRow = {
  id: number;
  sender: string;
  sender_name: string;
  subject: string;
  summary: string | null;
  category: string | null;
  priority: number | null;
  sent_at: string | null;
  is_read: boolean;
  /** De onde vem o e-mail: "inbox" ou "spam". */
  folder: string;
  deadline: string | null;
  // O valor chega como texto, não como número: dinheiro não pode passar
  // por ponto flutuante, que arredonda em silêncio.
  amount: string | null;
  currency: string | null;
  action_required: boolean;
  /** Resolvido: a resposta foi enviada ou o e-mail foi ignorado. */
  handled_at: string | null;
  /** «Lembrar»: até esse horário o e-mail fica oculto das listas. */
  snoozed_until: string | null;
  account: MailboxLabel;
};

export type ReplyRow = {
  id: number;
  /** draft — aguarda decisão; sent — enviado; failed — o serviço recusou; dropped — descartado. */
  status: "draft" | "sent" | "failed" | "dropped";
  to: string;
  subject: string;
  ai_text: string;
  final_text: string | null;
  language: string;
  note: string;
  error: string | null;
  /** O que foi anexado — só nomes e tamanhos; os arquivos em si não ficam com a gente. */
  attachments: { filename: string; size: number }[];
  created_at: string;
  sent_at: string | null;
};

export type MessageFull = MessageRow & {
  body_text: string;
  /** Tradução, se já foi pedida; senão null. (O nome do campo vem da API.) */
  subject_translated: string | null;
  body_translated: string | null;
  /** Para onde vai a resposta: o Reply-To do e-mail ou o remetente. */
  answer_to: string;
  replies: ReplyRow[];
  recipients: string[];
  attachments: { id: number; filename: string; size_bytes: number }[];
};

export type Mailbox = {
  id: number;
  email: string;
  display_name: string;
  service: string;
  imap_host: string;
  is_active: boolean;
  last_error: string | null;
  last_synced_at: string | null;
};

export type Service = {
  key: string;
  label: string;
  help_url: string;
  password_hint: string;
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : "Erro na requisição");
  }
}

/** Texto legível a partir da resposta da API: nos erros de e-mail ele vem como objeto. */
export function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.detail as { message?: string; hint?: string } | string;
    if (typeof detail === "string") return detail;
    if (detail?.message) return detail.message;
  }
  return "Algo deu errado. Tente novamente.";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  // Num formulário com arquivos, o tipo e o separador das partes são
  // definidos pelo próprio fetch — um Content-Type nosso os apagaria.
  const json = !(init.body instanceof FormData);
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(json ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
    cache: "no-store",
  });

  if (response.status === 401) redirect("/login");
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(response.status, body?.detail ?? null);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type InboxFilter = {
  category?: string;
  minPriority?: number;
  accountId?: number;
  unreadOnly?: boolean;
  /** Só e-mails que mencionam um valor ou um prazo. */
  withMoney?: boolean;
  /** No topo, não o mais importante, e sim o vencido. Para a tela de dinheiro e prazos. */
  byDeadline?: boolean;
  /** Busca em todos os e-mails: cada palavra no assunto, no remetente ou no texto. */
  query?: string;
  limit?: number;
};

export async function listMessages(
  filter: InboxFilter = {},
): Promise<{ total: number; items: MessageRow[] }> {
  const query = new URLSearchParams({ limit: String(filter.limit ?? 100) });
  if (filter.category) query.set("category", filter.category);
  if (filter.minPriority) query.set("min_priority", String(filter.minPriority));
  if (filter.accountId) query.set("account_id", String(filter.accountId));
  if (filter.unreadOnly) query.set("unread_only", "true");
  if (filter.withMoney) query.set("with_money", "true");
  if (filter.byDeadline) query.set("by_deadline", "true");
  if (filter.query) query.set("q", filter.query);
  return request(`/api/messages?${query}`);
}

/**
 * Números de todas as abas em uma única requisição.
 *
 * A categoria não é passada aqui de propósito: os contadores não podem
 * depender da aba aberta, senão todas as outras mostrariam zero.
 */
export async function getMessageCounts(accountId?: number): Promise<InboxCounts> {
  const query = new URLSearchParams();
  if (accountId) query.set("account_id", String(accountId));
  const tail = query.toString();
  return request(`/api/messages/counts${tail ? `?${tail}` : ""}`);
}

export async function getMessage(id: number): Promise<MessageFull> {
  return request(`/api/messages/${id}`);
}

export async function translateMessage(
  id: number,
): Promise<{ subject_translated: string; body_translated: string }> {
  return request(`/api/messages/${id}/translate`, { method: "POST" });
}

export async function markRead(id: number): Promise<void> {
  await request(`/api/messages/${id}/read`, { method: "POST" });
}

export async function listAccounts(): Promise<{ items: Mailbox[] }> {
  return request("/api/accounts");
}

export async function listServices(): Promise<{ items: Service[] }> {
  return request("/api/accounts/services");
}

export async function addAccount(email: string, password: string): Promise<Mailbox> {
  return request("/api/accounts", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export type BulkResult = {
  added: number;
  failed: { email: string; message: string }[];
};

export async function addManyAccounts(text: string): Promise<BulkResult> {
  return request("/api/accounts/bulk", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function setAccountActive(id: number, isActive: boolean): Promise<void> {
  await request(`/api/accounts/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  });
}

export async function deleteAccount(id: number): Promise<void> {
  await request(`/api/accounts/${id}`, { method: "DELETE" });
}

/**
 * O login é a única requisição sem token, por isso não passa por request().
 * clientIp — como no cadastro: a API conta os erros por endereço, e não só
 * pelo e-mail, para que um desconhecido não tranque o dono fora da conta.
 */
export async function login(
  email: string,
  password: string,
  code: string,
  clientIp: string,
): Promise<{ access_token: string }> {
  const response = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Client-IP": clientIp },
    body: JSON.stringify({ email, password, code: code || null }),
    cache: "no-store",
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body?.detail ?? null);
  return body;
}

export type Me = {
  email: string;
  totp_enabled: boolean;
  /** owner — equipe; member — criou a conta por conta própria. */
  role: "owner" | "member";
  /** Final da chave própria do Gemini («…wxyz»); null — sem chave própria. */
  ai_key_hint: string | null;
  /** Se o servidor compartilha a chave dele com quem não tem a própria. */
  ai_shared_key: boolean;
};

/**
 * Cadastro pelo link. clientIp é o endereço da pessoa: a API conta os
 * cadastros por ele, para que um script não crie mil contas.
 */
export async function register(
  email: string,
  password: string,
  clientIp: string,
): Promise<{ access_token: string }> {
  const response = await fetch(`${API_URL}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Client-IP": clientIp },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body?.detail ?? null);
  return body;
}

export async function me(): Promise<Me> {
  return request("/api/auth/me");
}

/**
 * Encerrar a sessão no servidor: o token deixa de valer, e não só some do
 * cookie. Fora de request() de propósito — com o token já vencido, request()
 * levaria à página de login antes de o cookie ser apagado. Falhou — tanto
 * faz: o cookie é apagado de qualquer jeito.
 */
export async function logout(): Promise<void> {
  const token = await getToken();
  if (!token) return;
  await fetch(`${API_URL}/api/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  }).catch(() => null);
}

/** Trocar a senha. Devolve um token novo: as outras sessões caem, esta continua. */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ access_token: string }> {
  return request("/api/auth/password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

/**
 * Salvar a chave própria do Gemini. token — logo após o login: o novo login
 * já está no cookie da resposta, mas na mesma requisição não dá para lê-lo de lá.
 */
export async function setAiKey(key: string, token?: string): Promise<{ ai_key_hint: string }> {
  return request("/api/auth/ai-key", {
    method: "PUT",
    body: JSON.stringify({ key }),
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
}

export async function deleteAiKey(): Promise<void> {
  await request("/api/auth/ai-key", { method: "DELETE" });
}

export type RuleRow = RuleShape & {
  id: number;
  title: string;
  is_active: boolean;
  created_at: string;
};

/** Como a IA entendeu a frase. Ainda não é regra — a pessoa confere antes. */
export type RuleDraft = RuleShape & {
  understood: boolean;
  explanation: string;
  title: string;
};

export async function listRules(): Promise<{ items: RuleRow[]; categories: string[] }> {
  return request("/api/rules");
}

export async function parseRule(text: string): Promise<RuleDraft> {
  return request("/api/rules/parse", { method: "POST", body: JSON.stringify({ text }) });
}

export async function createRule(
  rule: RuleShape & { title: string; apply_to_existing: boolean },
): Promise<RuleRow & { applied: number }> {
  return request("/api/rules", { method: "POST", body: JSON.stringify(rule) });
}

export async function setRuleActive(id: number, isActive: boolean): Promise<void> {
  await request(`/api/rules/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  });
}

export async function deleteRule(id: number): Promise<void> {
  await request(`/api/rules/${id}`, { method: "DELETE" });
}

export async function makeDraft(id: number, regenerate = false): Promise<ReplyRow> {
  return request(`/api/messages/${id}/draft`, {
    method: "POST",
    body: JSON.stringify({ regenerate }),
  });
}

/**
 * Enviar a resposta. Sempre como formulário (multipart): os mesmos campos
 * de antes, mais os arquivos anexados no campo files. Um caminho só, com
 * arquivos ou sem — menos lugares onde algo pode divergir.
 */
export async function sendReply(
  id: number,
  reply: { reply_id: number | null; text: string; to: string; subject: string },
  files: File[] = [],
): Promise<ReplyRow> {
  const body = new FormData();
  body.set("reply_id", reply.reply_id ? String(reply.reply_id) : "");
  body.set("text", reply.text);
  body.set("to", reply.to);
  body.set("subject", reply.subject);
  for (const file of files) body.append("files", file, file.name);
  return request(`/api/messages/${id}/send`, { method: "POST", body });
}

/**
 * Anexo do e-mail — a resposta crua da API, para repassar os bytes ao
 * navegador em fluxo. Por fora de request(): ela lê a resposta inteira como
 * JSON e, no 401, manda para a página de login; aqui quem decide é a rota
 * de download.
 */
export async function fetchAttachment(
  messageId: number,
  attachmentId: number,
  token: string,
): Promise<Response> {
  return fetch(`${API_URL}/api/messages/${messageId}/attachments/${attachmentId}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
}

export async function ignoreMessage(id: number): Promise<void> {
  await request(`/api/messages/${id}/ignore`, { method: "POST" });
}

export async function snoozeMessage(id: number, hours: number): Promise<void> {
  await request(`/api/messages/${id}/snooze`, {
    method: "POST",
    body: JSON.stringify({ hours }),
  });
}

export async function reopenMessage(id: number): Promise<void> {
  await request(`/api/messages/${id}/reopen`, { method: "POST" });
}

export type BriefData = {
  day: string;
  intro: string;
  generated_at: string | null;
  attention: MessageRow[];
  replies: MessageRow[];
  money: MessageRow[];
  arrived: number;
  information: number;
  filtered: number;
};

export async function getBrief(): Promise<BriefData> {
  return request("/api/brief");
}

export async function refreshBrief(): Promise<BriefData> {
  return request("/api/brief/refresh", { method: "POST" });
}

export type SystemStatus = {
  ai: {
    name: string;
    configured: boolean;
    /** Os e-mails desta pessoa são analisados com a chave dela. */
    own_key: boolean;
    paused_until: number | null;
  };
  /** Quantos e-mails aguardam análise. */
  unsorted: number;
  /** Quantos e-mails exigem atenção — o número no sininho. */
  attention: number;
};

export async function getStatus(): Promise<SystemStatus> {
  return request("/api/status");
}
