import { cookies } from "next/headers";

export const TOKEN_COOKIE = "boss_token";
const WEEK = 60 * 60 * 24 * 7;

/**
 * O token vive em um cookie httpOnly: o código do navegador não o alcança,
 * por isso não dá para roubá-lo pela página. Todas as chamadas à API saem
 * do servidor Next, e não do navegador.
 */
export async function getToken(): Promise<string | null> {
  return (await cookies()).get(TOKEN_COOKIE)?.value ?? null;
}

export async function setToken(token: string): Promise<void> {
  (await cookies()).set(TOKEN_COOKIE, token, {
    httpOnly: true,
    // No servidor, obrigatoriamente true: senão o navegador aceitaria enviar
    // o token por http aberto, e isso é todo o acesso ao e-mail em uma requisição.
    // Localmente, via http, esse cookie não seria salvo — por isso vem do ambiente.
    secure: process.env.COOKIE_SECURE !== "false",
    sameSite: "lax",
    path: "/",
    maxAge: WEEK,
  });
}

export async function clearToken(): Promise<void> {
  (await cookies()).delete(TOKEN_COOKIE);
}
