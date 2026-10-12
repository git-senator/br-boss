import type { NextConfig } from "next";

// Por padrão o Next não define nenhum cabeçalho de segurança. Sem eles,
// dá para abrir a página numa janela invisível sobre um site alheio e fazer
// o próprio dono clicar em «Excluir caixa de e-mail» com as próprias mãos.
const SECURITY_HEADERS = [
  // Endereços externos não são carregados de jeito nenhum: e-mails chegam de qualquer um,
  // e uma imagem do e-mail não deve fazer requisições a um servidor alheio.
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "connect-src 'self'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; "),
  },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  // Só tem efeito sobre HTTPS, por isso é inofensivo em testes locais.
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
];

const config: NextConfig = {
  output: "standalone",
  // Não há por que contar ao mundo com o que isto foi feito.
  poweredByHeader: false,
  // O endereço da API vem do ambiente — ao migrar para o servidor do cliente,
  // muda-se uma linha no .env, e não o código.
  env: { API_URL: process.env.API_URL ?? "http://api:8000" },
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default config;
