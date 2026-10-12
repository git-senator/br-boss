/** Rótulos e cores em um só lugar, para a caixa de entrada e o cartão do e-mail não divergirem. */

/** Localidade da interface: datas dd/mm, números 1.234,56. */
const LOCALE = "pt-BR";

export const CATEGORY_LABEL: Record<string, string> = {
  urgent: "Urgente",
  payments: "Pagamentos",
  banks: "Bancos",
  legal: "Jurídico",
  renewals: "Renovações",
  business: "Negócios",
  personal: "Pessoal",
  low: "Outros",
  ads: "Publicidade",
  // Por último na fileira: e-mails de segurança são muitos, mas quase
  // nunca exigem decisão — o lugar deles é no fim, não entre as pendências.
  security: "Segurança",
};

/**
 * E-mails que a classificação ainda não alcançou. No servidor é uma
 * categoria vazia; aqui ela tem aba própria — senão, com a caixa ainda
 * não classificada, a interface mostraria zeros com a caixa cheia.
 */
export const UNSORTED = "none";
const UNSORTED_LABEL = "Não classificado";

/**
 * A pasta de spam não é uma categoria, é um lugar. O conteúdo de um e-mail
 * de lá pode ser qualquer coisa, por isso a aba é separada e não entra em
 * «Todos». Mas também não se perde: um e-mail importante que caiu no spam
 * aparece aqui.
 */
export const SPAM = "spam";
const SPAM_LABEL = "Spam";

export function categoryLabel(category: string | null): string {
  if (category === SPAM) return SPAM_LABEL;
  if (!category || category === UNSORTED) return UNSORTED_LABEL;
  return CATEGORY_LABEL[category] ?? category;
}

/** Ordem das abas: primeiro as pendências, bem no fim o spam. */
export const TAB_ORDER = [...Object.keys(CATEGORY_LABEL), UNSORTED, SPAM];

export type Bucket = { total: number; unread: number };
export type InboxCounts = { all: Bucket; categories: Record<string, Bucket> };

/**
 * Número sob a aba. No modo «não lidos» mostramos os não lidos — senão os
 * números continuariam os mesmos e o seletor pareceria quebrado.
 *
 * Zero é mostrado como zero, não como vazio: aba sem número parece erro.
 */
export function tabCount(bucket: Bucket | undefined, unreadOnly: boolean): string {
  if (!bucket) return "0";
  return String(unreadOnly ? bucket.unread : bucket.total);
}

/**
 * Cor da prioridade. Quatro degraus, não um gradiente: o olhar precisa
 * captar o que é alarmante sem comparar tons.
 */
export function priorityTone(priority: number | null): string {
  // Cápsula: fundo translúcido, borda e texto da mesma cor.
  if (priority === null) return "border border-edge bg-calm text-ink-dim";
  if (priority >= 80) return "border border-alarm/30 bg-alarm/15 text-alarm";
  if (priority >= 60) return "border border-warn/30 bg-warn/15 text-warn";
  if (priority >= 40) return "border border-watch/30 bg-watch/15 text-watch";
  return "border border-edge bg-calm text-ink-dim";
}

/** «hoje 14:30», «ontem 09:12», «12/08» — como as pessoas falam do tempo. */
export function whenLabel(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";

  const time = date.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" });
  const days = daysApart(date, now);
  if (days === 0) return `hoje ${time}`;
  if (days === 1) return `ontem ${time}`;
  if (days < 7) return `há ${days} dias`;
  return shortDate(date);
}

/** Quando, no futuro: «amanhã 14:00», «em 3 dias», «18/10». Para «Lembrar». */
export function untilLabel(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";

  const time = date.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" });
  const days = daysApart(now, date);
  if (days <= 0) return `hoje ${time}`;
  if (days === 1) return `amanhã ${time}`;
  if (days < 7) return `em ${days} dias`;
  return shortDate(date);
}

/** Data curta no padrão brasileiro: «01/08». */
function shortDate(date: Date): string {
  return date.toLocaleDateString(LOCALE, { day: "2-digit", month: "2-digit" });
}

function daysApart(from: Date, to: Date): number {
  const midnight = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const ms = midnight(to).getTime() - midnight(from).getTime();
  return Math.round(ms / 86_400_000);
}

export function senderLabel(name: string, email: string): string {
  return name.trim() || email;
}

const ONE_DECIMAL = new Intl.NumberFormat(LOCALE, {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${ONE_DECIMAL.format(bytes / 1024 / 1024)} MB`;
}

/** Símbolos das moedas que aparecem nos e-mails do cliente. */
const CURRENCY_SIGN: Record<string, string> = {
  BRL: "R$",
  USD: "US$",
  EUR: "€",
  RUB: "₽",
  AED: "dh",
};

/**
 * O valor como uma pessoa lê: «R$ 47.315», e não «47315.00».
 *
 * Trabalhamos com texto, não com número: o ponto flutuante arredonda em
 * silêncio, e os centavos da fatura deixam de bater. A formatação segue o
 * padrão brasileiro (o mesmo do Intl pt-BR): ponto nos milhares, vírgula
 * nos centavos. Centavos só aparecem quando existem — valores redondos se
 * leem mais rápido sem o «,00» no final.
 */
export function moneyLabel(amount: string | null, currency: string | null): string {
  if (!amount) return "";
  const [whole, cents = ""] = amount.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const tail = cents && Number(cents) > 0 ? `,${cents}` : "";
  const sign = currency ? (CURRENCY_SIGN[currency] ?? currency) : "";
  return sign ? `${sign} ${grouped}${tail}` : `${grouped}${tail}`;
}

/** Quantos dias faltam até o prazo. Negativo — vencido. */
function daysLeft(iso: string, now: Date): number | null {
  const due = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(due.getTime())) return null;
  const midnight = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return Math.round((midnight(due).getTime() - midnight(now).getTime()) / 86_400_000);
}

/** «vencido há 3 dias», «vence hoje», «vence em 30/09» */
export function deadlineLabel(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "";
  const days = daysLeft(iso, now);
  if (days === null) return "";
  if (days === -1) return "vencido há 1 dia";
  if (days < 0) return `vencido há ${-days} dias`;
  if (days === 0) return "vence hoje";
  if (days === 1) return "vence amanhã";
  if (days < 7) return `vence em ${days} dias`;
  return `vence em ${shortDate(new Date(`${iso}T00:00:00`))}`;
}

/** Cor do prazo. Os mesmos quatro degraus da prioridade — o olho já se acostumou. */
export function deadlineTone(iso: string | null, now: Date = new Date()): string {
  const days = iso ? daysLeft(iso, now) : null;
  if (days === null) return "border-edge text-ink-dim";
  if (days < 0) return "border-alarm text-alarm";
  if (days <= 1) return "border-warn text-warn";
  if (days < 7) return "border-watch text-watch";
  return "border-edge text-ink-dim";
}

export const DUE_GROUPS = ["overdue", "now", "week", "later", "nodate"] as const;
export type DueGroup = (typeof DUE_GROUPS)[number];

export const DUE_GROUP_LABEL: Record<DueGroup, string> = {
  overdue: "Vencidos",
  now: "Hoje e amanhã",
  week: "Esta semana",
  later: "Mais adiante",
  nodate: "Sem prazo",
};

/** Em qual prateleira da tela «Dinheiro e prazos» o e-mail vai. */
export function dueGroup(iso: string | null, now: Date = new Date()): DueGroup {
  const days = iso ? daysLeft(iso, now) : null;
  if (days === null) return "nodate";
  if (days < 0) return "overdue";
  if (days <= 1) return "now";
  if (days < 7) return "week";
  return "later";
}

/**
 * Somar valores por moeda. Reais com dólares não se somam: um «47.000»
 * sem dizer de quê é pior do que nenhum número.
 *
 * Somamos em centavos, com inteiros — ponto flutuante em uma dezena de
 * faturas erra por um centavo, e a pessoa deixa de confiar no total.
 */
export function sumByCurrency(
  items: { amount: string | null; currency: string | null }[],
): { currency: string; amount: string }[] {
  const totals = new Map<string, bigint>();
  for (const item of items) {
    if (!item.amount) continue;
    const [whole, cents = "0"] = item.amount.split(".");
    const inCents = BigInt(whole) * 100n + BigInt(cents.padEnd(2, "0").slice(0, 2));
    const key = item.currency ?? "";
    totals.set(key, (totals.get(key) ?? 0n) + inCents);
  }
  return [...totals].map(([currency, cents]) => ({
    currency,
    amount: `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`,
  }));
}

/** Trecho do texto do e-mail: comum ou link. */
export type TextPart = { text: string; href?: string };

// Capturamos só três coisas: http, https e endereço de e-mail. Nada mais
// vira link.
const LINKY =
  /(https?:\/\/[^\s<>"'«»]+|www\.[^\s<>"'«»]+|[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+)/g;

// Sinais que encerram a frase, não o link.
const TAIL = /[.,;:!?»"')\]]+$/;

/**
 * Dividir o texto do e-mail em trechos comuns e links.
 *
 * Os links vêm de um estranho, por isso o endereço é montado por nós, e
 * não copiado do e-mail: só http, https e e-mail são permitidos. Nada de
 * «javascript:», «data:» e outros truques de fraude entra aqui, por
 * construção.
 *
 * Devolvemos trechos, não marcação pronta: quem monta a marcação é o React,
 * e ele mesmo escapa o texto. Montar HTML como string a partir de um e-mail
 * alheio não é permitido em hipótese alguma.
 */
export function linkParts(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let last = 0;

  for (const found of text.matchAll(LINKY)) {
    const at = found.index ?? 0;
    let piece = found[0];

    // «Saiba mais: https://site.com/x.» — o ponto final pertence à frase.
    const tail = piece.match(TAIL);
    let trimmed = "";
    if (tail) {
      // O parêntese só é cortado se não houver um de abertura no próprio link.
      const cut = piece.slice(0, piece.length - tail[0].length);
      if (!(tail[0].includes(")") && cut.includes("("))) {
        trimmed = tail[0];
        piece = cut;
      }
    }
    if (!piece) continue;

    if (at > last) parts.push({ text: text.slice(last, at) });
    parts.push({ text: piece, href: _href(piece) });
    if (trimmed) parts.push({ text: trimmed });
    last = at + found[0].length;
  }

  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

function _href(piece: string): string {
  if (piece.startsWith("http://") || piece.startsWith("https://")) return piece;
  if (piece.startsWith("www.")) return `https://${piece}`;
  return `mailto:${piece}`;
}

/**
 * Como mostrar um link sem que ele ocupe meia tela.
 *
 * Links de publicidade arrastam uma cauda de parâmetros de rastreamento —
 * às vezes de quatro linhas. Escondemos a cauda, mas o nome do site fica
 * inteiro: é por ele que a pessoa decide se clica ou não, e não se pode
 * trocá-lo por uma abreviação. O endereço completo continua no próprio
 * link e na dica.
 */
export function shortLink(href: string, limit = 72): string {
  const bare = href.replace(/^https?:\/\//, "").replace(/^mailto:/, "");
  if (bare.length <= limit) return bare;

  const slash = bare.indexOf("/");
  const host = slash === -1 ? bare : bare.slice(0, slash);
  const rest = slash === -1 ? "" : bare.slice(slash);
  const room = Math.max(0, limit - host.length - 1);
  return room < 4 ? `${host}/…` : `${host}${rest.slice(0, room)}…`;
}

export type RuleShape = {
  condition_kind: string;
  condition_value: string;
  action_kind: string;
  action_value: string;
};

const CONDITION_TEXT: Record<string, (value: string) => string> = {
  sender_contains: (value) => `o remetente contém «${value}»`,
  subject_contains: (value) => `o assunto contém «${value}»`,
  body_contains: (value) => `o assunto ou o texto contém «${value}»`,
  amount_over: (value) => `o valor for maior que ${value}`,
  category_is: (value) => `a categoria for ${categoryLabel(value)}`,
};

const ACTION_TEXT: Record<string, (value: string) => string> = {
  set_min_priority: (value) => `prioridade no mínimo ${value}`,
  set_max_priority: (value) => `prioridade no máximo ${value}`,
  set_category: (value) => `mover para a categoria «${categoryLabel(value)}»`,
};

/**
 * A regra em linguagem humana: «Se o remetente contém «advogad» —
 * prioridade no mínimo 85».
 *
 * É o que a pessoa confere com os olhos antes de salvar. A frase com que
 * ela escreveu a regra pode ter sido entendida de outro jeito — mostramos
 * como entendemos.
 */
export function describeRule(rule: RuleShape): string {
  const condition = CONDITION_TEXT[rule.condition_kind]?.(rule.condition_value);
  const action = ACTION_TEXT[rule.action_kind]?.(rule.action_value);
  if (!condition || !action) return "Regra em formato desconhecido — é melhor excluí-la";
  return `Se ${condition} — ${action}`;
}

/** Se o campo é numérico (prioridade), e não uma escolha de categoria. */
export function ruleWantsNumber(actionKind: string): boolean {
  return actionKind === "set_min_priority" || actionKind === "set_max_priority";
}

/** Marca no texto do erro: mostrá-lo junto ao botão de tradução, não junto à resposta. */
export const TRANSLATE_ERROR = "Tradução: ";

/**
 * Palavras funcionais frequentes do português. Ficam de fora as que também
 * são palavras inglesas comuns («a», «o», «as», «do», «no», «se») — senão
 * qualquer texto em inglês pareceria português.
 */
const PT_WORDS = new Set([
  "de", "que", "não", "para", "com", "uma", "um", "os", "você", "é", "da", "dos", "das",
  "em", "na", "nos", "nas", "por", "pelo", "pela", "mais", "seu", "sua", "seus", "suas",
  "obrigado", "obrigada", "olá", "está", "são", "também", "ao", "aos", "à", "até",
  "muito", "sobre", "ou", "já", "como", "mas", "foi", "isso", "este", "esta", "esse",
  "essa", "pagamento", "fatura", "prezado", "prezada",
]);

/** Palavras que denunciam o espanhol (e não existem como tais em português). */
const ES_WORDS = new Set([
  "el", "los", "las", "del", "y", "usted", "gracias", "hola", "pero", "muy", "es",
  "su", "sus", "con", "una", "factura", "pago", "estimado", "señor", "tiene",
]);

/**
 * O e-mail já está em português — o botão de tradução não é necessário.
 *
 * Heurística simples, sem dicionário: tiramos links e endereços; sem letras,
 * não há o que traduzir. Alfabeto não latino (cirílico etc.) — não é
 * português. Depois contamos palavras funcionais portuguesas e palavras com
 * letras típicas (ã, õ, ç); se a fatia delas entre as palavras é alta o
 * bastante e o espanhol não aparece mais forte, é português.
 */
export function isMostlyPortuguese(text: string): boolean {
  const clean = text.replace(/https?:\/\/\S+|www\.\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, " ");
  const letters = clean.match(/\p{L}/gu) ?? [];
  if (letters.length === 0) return true;
  const latin = letters.filter((letter) => /\p{Script=Latin}/u.test(letter)).length;
  if (latin / letters.length < 0.5) return false;

  const words = clean.toLowerCase().match(/\p{L}+/gu) ?? [];
  const portuguese = words.filter((word) => PT_WORDS.has(word)).length;
  const spanish = words.filter((word) => ES_WORDS.has(word)).length;
  // ã, õ, ç, ê, â, ô são marcas fortes: quase não existem em inglês e espanhol.
  const marked = words.filter((word) => /[ãõçêâô]/u.test(word) && !PT_WORDS.has(word)).length;

  const score = portuguese + marked;
  if (spanish >= score) return false;
  return score / words.length >= 0.15;
}
