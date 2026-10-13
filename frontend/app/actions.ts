"use server";

import { revalidatePath } from "next/cache";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import {
  addAccount,
  addManyAccounts,
  ApiError,
  changePassword,
  createRule,
  deleteAccount,
  deleteAiKey,
  deleteRule,
  errorText,
  ignoreMessage,
  login,
  logout,
  makeDraft,
  refreshBrief,
  reopenMessage,
  sendReply,
  snoozeMessage,
  translateMessage,
  parseRule,
  register,
  setAccountActive,
  setAiKey,
  setRuleActive,
} from "@/lib/api";
import { TRANSLATE_ERROR } from "@/lib/format";
import { clearToken, setToken } from "@/lib/session";

/**
 * Os formulários funcionam com POST comum, sem JavaScript no navegador.
 * O erro volta pelo endereço da página — igualmente confiável no
 * navegador do celular e com conexão ruim.
 */
function back(path: string, error?: string): never {
  redirect(error ? withParam(path, "error", error) : path);
}

/** Acrescentar um parâmetro a um endereço que já pode ter «?» e «#». */
function withParam(path: string, key: string, value: string): string {
  const [base, hash] = path.split("#");
  const joined = `${base}${base.includes("?") ? "&" : "?"}${key}=${encodeURIComponent(value)}`;
  return hash ? `${joined}#${hash}` : joined;
}

/**
 * Para onde voltar após a ação — vem de um campo oculto do formulário.
 * Só endereços nossos: «/…», mas nunca «//site-alheio» nem «/\site-alheio»
 * — o navegador lê a barra invertida como barra, e um link com o campo
 * adulterado poderia levar a pessoa para qualquer lugar.
 */
function returnPath(form: FormData, field: string, fallback: string): string {
  const value = String(form.get(field) ?? "");
  return value.startsWith("/") && !/^\/[\\/]/.test(value) ? value : fallback;
}

/**
 * O endereço da pessoa é definido pelo nginx na frente do site, no X-Real-IP.
 * Só ele: o X-Forwarded-For o navegador pode mandar como quiser, e com ele
 * um script trocaria de «endereço» a cada tentativa e passaria pelo limite.
 */
async function clientIp(): Promise<string> {
  return (await headers()).get("x-real-ip") ?? "";
}

/**
 * redirect() no Next funciona por meio de uma exceção. Se ela for pega
 * pelo nosso catch, o redirecionamento silenciosamente não acontece: em vez
 * da página de login, a pessoa vê «algo deu errado» e fica onde está.
 */
function rethrowRedirects(error: unknown): void {
  const digest = (error as { digest?: string })?.digest;
  if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw error;
}

export async function loginAction(form: FormData): Promise<void> {
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "");
  const code = String(form.get("code") ?? "").trim();
  const aiKey = String(form.get("ai_key") ?? "").trim();

  if (!email || !password) back("/login", "Informe o e-mail e a senha");

  let token: string;
  try {
    token = (await login(email, password, code, await clientIp())).access_token;
  } catch (error) {
    rethrowRedirects(error);
    if (error instanceof ApiError && error.detail === "totp_required") {
      back("/login", "Digite o código do app autenticador");
    }
    if (error instanceof ApiError && error.detail === "invalid_code") {
      back("/login", "Código inválido. Tente o próximo.");
    }
    back("/login", "E-mail ou senha incorretos");
  }

  await setToken(token);

  // A chave é opcional. Se não funcionar, o login já aconteceu mesmo assim:
  // levamos à página da chave e dizemos o que há de errado, sem expulsar a pessoa.
  if (aiKey) {
    try {
      await setAiKey(aiKey, token);
    } catch (error) {
      rethrowRedirects(error);
      back("/key", errorText(error));
    }
  }

  // Primeiro o resumo: a pessoa deve ver decisões, não e-mails.
  redirect("/brief");
}

export async function saveAiKeyAction(form: FormData): Promise<void> {
  const key = String(form.get("key") ?? "").trim();
  if (!key) back("/key", "Cole a chave");
  try {
    await setAiKey(key);
  } catch (error) {
    rethrowRedirects(error);
    back("/key", errorText(error));
  }
  revalidatePath("/", "layout");
  redirect("/key?saved=1");
}

export async function removeAiKeyAction(): Promise<void> {
  await deleteAiKey();
  revalidatePath("/", "layout");
  redirect("/key?removed=1");
}

export async function registerAction(form: FormData): Promise<void> {
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "");
  const again = String(form.get("again") ?? "");

  if (!email || !password) back("/register", "Informe o e-mail e a senha");
  if (password !== again) back("/register", "As senhas não coincidem");

  let token: string;
  try {
    token = (await register(email, password, await clientIp())).access_token;
  } catch (error) {
    rethrowRedirects(error);
    back("/register", errorText(error));
  }

  await setToken(token);
  // Para quem acabou de chegar, o primeiro passo é conectar o e-mail.
  redirect("/accounts?welcome=1");
}

export async function logoutAction(): Promise<void> {
  // Primeiro o servidor esquece o token, depois o navegador apaga o cookie:
  // um token copiado antes do «Sair» também deixa de valer.
  await logout();
  await clearToken();
  redirect("/login");
}

/** O erro da troca de senha vai num parâmetro próprio: «error» é o da chave de IA, na mesma página. */
function passwordError(text: string): never {
  redirect(withParam("/key#senha", "password_error", text));
}

export async function changePasswordAction(form: FormData): Promise<void> {
  const current = String(form.get("current") ?? "");
  const next = String(form.get("password") ?? "");
  const again = String(form.get("again") ?? "");

  if (!current || !next) passwordError("Informe a senha atual e a nova");
  if (next !== again) passwordError("As senhas novas não coincidem");

  let token: string;
  try {
    token = (await changePassword(current, next)).access_token;
  } catch (error) {
    rethrowRedirects(error);
    passwordError(errorText(error));
  }

  // As outras sessões caíram; esta segue com o token novo.
  await setToken(token);
  redirect("/key?password=1#senha");
}

export async function addAccountAction(form: FormData): Promise<void> {
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "").trim();

  if (!email || !password) back("/accounts", "Informe o endereço e a senha de app");

  try {
    await addAccount(email, password);
  } catch (error) {
    rethrowRedirects(error);
    back("/accounts", errorText(error));
  }
  revalidatePath("/accounts");
  redirect("/accounts");
}

export async function addManyAction(form: FormData): Promise<void> {
  const text = String(form.get("list") ?? "").trim();
  if (!text) back("/accounts", "Cole pelo menos uma caixa de e-mail");

  let result;
  try {
    result = await addManyAccounts(text);
  } catch (error) {
    rethrowRedirects(error);
    back("/accounts", errorText(error));
  }

  revalidatePath("/accounts");
  // O resultado aparece na própria página: o que conectou, o que não conectou e por quê.
  const query = new URLSearchParams({ added: String(result.added) });
  for (const item of result.failed) query.append("bad", `${item.email} — ${item.message}`);
  redirect(`/accounts?${query}`);
}

export async function toggleAccountAction(form: FormData): Promise<void> {
  const id = Number(form.get("id"));
  const isActive = form.get("is_active") === "true";
  await setAccountActive(id, isActive);
  revalidatePath("/accounts");
  redirect("/accounts");
}

export async function deleteAccountAction(form: FormData): Promise<void> {
  await deleteAccount(Number(form.get("id")));
  revalidatePath("/accounts");
  redirect("/accounts");
}

/**
 * Frase → rascunho da regra. O rascunho volta para a página no endereço:
 * os formulários funcionam sem JavaScript, e não há outro jeito de levar a
 * resposta à página depois de um POST comum. Ele é pequeno — poucas linhas.
 */
export async function parseRuleAction(form: FormData): Promise<void> {
  const text = String(form.get("text") ?? "").trim();
  if (!text) back("/rules", "Escreva a regra");

  let draft;
  try {
    draft = await parseRule(text);
  } catch (error) {
    rethrowRedirects(error);
    redirect(`/rules?${new URLSearchParams({ error: errorText(error), text })}`);
  }
  redirect(`/rules?${new URLSearchParams({ draft: JSON.stringify(draft) })}`);
}

export async function createRuleAction(form: FormData): Promise<void> {
  const field = (name: string) => String(form.get(name) ?? "").trim();

  let created;
  try {
    created = await createRule({
      title: field("title"),
      condition_kind: field("condition_kind"),
      condition_value: field("condition_value"),
      action_kind: field("action_kind"),
      action_value: field("action_value"),
      apply_to_existing: form.get("apply_to_existing") === "on",
    });
  } catch (error) {
    rethrowRedirects(error);
    back("/rules", errorText(error));
  }
  revalidatePath("/rules");
  redirect(`/rules?saved=${created.applied}`);
}

export async function toggleRuleAction(form: FormData): Promise<void> {
  await setRuleActive(Number(form.get("id")), form.get("is_active") === "true");
  revalidatePath("/rules");
  redirect("/rules");
}

export async function deleteRuleAction(form: FormData): Promise<void> {
  await deleteRule(Number(form.get("id")));
  revalidatePath("/rules");
  redirect("/rules");
}

/**
 * Ações sobre o e-mail. O formulário pode vir da página do e-mail ou do
 * painel sobre a lista: o campo back diz para onde voltar (e onde mostrar o
 * erro), o campo done diz para onde ir quando o e-mail está resolvido e o
 * painel não é mais necessário.
 */
function letterPath(form: FormData): string {
  return returnPath(form, "back", `/messages/${Number(form.get("message_id"))}`);
}

export async function translateAction(form: FormData): Promise<void> {
  const path = letterPath(form);
  try {
    await translateMessage(Number(form.get("message_id")));
  } catch (error) {
    rethrowRedirects(error);
    back(path, TRANSLATE_ERROR + errorText(error));
  }
  redirect(path);
}

export async function draftAction(form: FormData): Promise<void> {
  const path = letterPath(form);
  try {
    await makeDraft(Number(form.get("message_id")), form.get("regenerate") === "1");
  } catch (error) {
    rethrowRedirects(error);
    back(path, errorText(error));
  }
  redirect(`${path}#reply`);
}

export async function sendReplyAction(form: FormData): Promise<void> {
  const path = letterPath(form);
  const replyId = Number(form.get("reply_id"));
  try {
    await sendReply(Number(form.get("message_id")), {
      reply_id: replyId || null,
      text: String(form.get("text") ?? ""),
      to: String(form.get("to") ?? "").trim(),
      subject: String(form.get("subject") ?? "").trim(),
    });
  } catch (error) {
    rethrowRedirects(error);
    back(`${path}#reply`, errorText(error));
  }
  revalidatePath("/");
  redirect(withParam(path, "toast", "sent"));
}

export async function ignoreAction(form: FormData): Promise<void> {
  await ignoreMessage(Number(form.get("message_id")));
  revalidatePath("/");
  // E-mail resolvido não exige mais atenção — de volta à lista de pendências.
  redirect(withParam(returnPath(form, "done", "/"), "toast", "ignored"));
}

export async function snoozeAction(form: FormData): Promise<void> {
  await snoozeMessage(Number(form.get("message_id")), Number(form.get("hours")));
  revalidatePath("/");
  redirect(withParam(returnPath(form, "done", "/"), "toast", "snoozed"));
}

export async function reopenAction(form: FormData): Promise<void> {
  await reopenMessage(Number(form.get("message_id")));
  revalidatePath("/");
  redirect(withParam(letterPath(form), "toast", "reopened"));
}

export async function refreshBriefAction(): Promise<void> {
  try {
    await refreshBrief();
  } catch (error) {
    rethrowRedirects(error);
    back("/brief", errorText(error));
  }
  revalidatePath("/brief");
  redirect("/brief");
}
