import assert from "node:assert/strict";
import { test } from "node:test";

import {
  isMostlyPortuguese,
  CATEGORY_LABEL,
  DUE_GROUPS,
  SPAM,
  TAB_ORDER,
  UNSORTED,
  categoryLabel,
  deadlineLabel,
  deadlineTone,
  describeRule,
  dueGroup,
  fileSize,
  linkParts,
  moneyLabel,
  priorityTone,
  ruleWantsNumber,
  senderLabel,
  shortLink,
  sumByCurrency,
  tabCount,
  untilLabel,
  whenLabel,
} from "../lib/format.ts";

test("categorias aparecem em português", () => {
  assert.equal(categoryLabel("payments"), "Pagamentos");
  assert.equal(categoryLabel(null), "Não classificado");
  assert.equal(categoryLabel("nunca-vista"), "nunca-vista");
});

test("publicidade é uma prateleira própria, e não «outros» com outro nome", () => {
  assert.equal(categoryLabel("ads"), "Publicidade");
  assert.notEqual(categoryLabel("ads"), categoryLabel("low"));
});

test("segurança é a última prateleira antes do não classificado", () => {
  assert.equal(categoryLabel("security"), "Segurança");
  const keys = Object.keys(CATEGORY_LABEL);
  assert.equal(keys.at(-1), "security", "no fim da fileira, não entre as pendências");
});

test("não classificado é uma aba como as outras", () => {
  assert.equal(categoryLabel(UNSORTED), "Não classificado");
  assert.equal(TAB_ORDER.at(-2), UNSORTED, "antes do spam, no fim da faixa");
  assert.equal(TAB_ORDER.length, Object.keys(CATEGORY_LABEL).length + 2);
});

test("a prioridade tem quatro degraus, não um gradiente", () => {
  const tones = [95, 80, 79, 60, 59, 40, 39, 0].map(priorityTone);
  assert.equal(new Set(tones).size, 4);
  assert.notEqual(priorityTone(95), priorityTone(0), "alarmante e tranquilo se distinguem");
});

test("e-mail não classificado não parece urgente", () => {
  assert.equal(priorityTone(null), priorityTone(10));
});

test("o número sob a aba acompanha o seletor de não lidos", () => {
  const bucket = { total: 40, unread: 12 };
  assert.equal(tabCount(bucket, false), "40");
  assert.equal(tabCount(bucket, true), "12");
});

test("aba vazia mostra zero, e não vazio", () => {
  assert.equal(tabCount({ total: 0, unread: 0 }, false), "0");
  assert.equal(tabCount(undefined, false), "0", "a categoria pode faltar na resposta");
});

test("o tempo é dito como as pessoas falam", () => {
  const now = new Date("2026-08-17T18:00:00");
  assert.equal(whenLabel("2026-08-17T14:30:00", now), "hoje 14:30");
  assert.equal(whenLabel("2026-08-16T09:12:00", now), "ontem 09:12");
  assert.equal(whenLabel("2026-08-14T09:12:00", now), "há 3 dias");
  assert.equal(whenLabel("2026-08-01T09:12:00", now), "01/08");
});

test("data vazia ou lixo não derrubam a lista", () => {
  assert.equal(whenLabel(null), "");
  assert.equal(whenLabel("não é data"), "");
});

test("sem nome do remetente, aparece o endereço", () => {
  assert.equal(senderLabel("  ", "ana@fornecedor.com.br"), "ana@fornecedor.com.br");
  assert.equal(senderLabel("Ana", "ana@fornecedor.com.br"), "Ana");
});

test("tamanho do anexo em unidades compreensíveis", () => {
  assert.equal(fileSize(512), "512 B");
  assert.equal(fileSize(2048), "2 KB");
  assert.equal(fileSize(3_500_000), "3,3 MB");
});

test("o valor se lê como dinheiro, e não como número do banco de dados", () => {
  assert.equal(moneyLabel("47000.00", "BRL"), "R$ 47.000");
  assert.equal(moneyLabel("1200.50", "BRL"), "R$ 1.200,50");
  assert.equal(moneyLabel("1234567.89", "BRL"), "R$ 1.234.567,89");
  assert.equal(moneyLabel("99.99", "EUR"), "€ 99,99");
  assert.equal(moneyLabel("500.00", "XYZ"), "XYZ 500", "moeda desconhecida vai como está");
  assert.equal(moneyLabel(null, "BRL"), "", "sem valor, sem rótulo");
});

test("valores redondos aparecem sem o «,00» no final", () => {
  assert.equal(moneyLabel("300.00", "USD"), "US$ 300");
});

test("o prazo é dito como as pessoas falam", () => {
  const now = new Date("2026-09-10T12:00:00");
  assert.equal(deadlineLabel("2026-09-07", now), "vencido há 3 dias");
  assert.equal(deadlineLabel("2026-09-09", now), "vencido há 1 dia");
  assert.equal(deadlineLabel("2026-09-10", now), "vence hoje");
  assert.equal(deadlineLabel("2026-09-11", now), "vence amanhã");
  assert.equal(deadlineLabel("2026-09-14", now), "vence em 4 dias");
  assert.equal(deadlineLabel("2026-09-30", now), "vence em 30/09");
  assert.equal(deadlineLabel(null, now), "");
});

test("vencido e tranquilo se distinguem pela cor", () => {
  const now = new Date("2026-09-10T12:00:00");
  assert.match(deadlineTone("2026-09-01", now), /alarm/);
  assert.notEqual(deadlineTone("2026-09-01", now), deadlineTone("2026-12-01", now));
  assert.equal(deadlineTone(null, now), deadlineTone("2026-12-01", now));
});

test("os e-mails se distribuem pelas prateleiras de prazo", () => {
  const now = new Date("2026-09-10T12:00:00");
  assert.equal(dueGroup("2026-09-01", now), "overdue");
  assert.equal(dueGroup("2026-09-11", now), "now");
  assert.equal(dueGroup("2026-09-14", now), "week");
  assert.equal(dueGroup("2026-12-01", now), "later");
  assert.equal(dueGroup(null, now), "nodate");
  assert.equal(DUE_GROUPS[0], "overdue", "o vencido é a primeira prateleira");
});

test("o total é somado por moeda e não mistura reais com dólares", () => {
  const totals = sumByCurrency([
    { amount: "1200.50", currency: "BRL" },
    { amount: "47000.00", currency: "BRL" },
    { amount: "300.00", currency: "USD" },
    { amount: null, currency: "EUR" },
  ]);

  assert.deepEqual(totals, [
    { currency: "BRL", amount: "48200.50" },
    { currency: "USD", amount: "300.00" },
  ]);
});

test("os centavos do total não se perdem em uma dezena de faturas", () => {
  const cents = Array.from({ length: 10 }, () => ({ amount: "0.10", currency: "BRL" }));
  assert.deepEqual(sumByCurrency(cents), [{ currency: "BRL", amount: "1.00" }]);
});

test("spam é a última aba de todas", () => {
  assert.equal(categoryLabel(SPAM), "Spam");
  assert.equal(TAB_ORDER.at(-1), SPAM, "bem no fim da fileira");
  assert.equal(TAB_ORDER.at(-2), UNSORTED);
  assert.notEqual(categoryLabel(SPAM), categoryLabel("ads"), "spam e publicidade são coisas diferentes");
});

test("links no e-mail viram links", () => {
  const parts = linkParts("Veja https://boss.example.com/fatura e pronto");
  assert.deepEqual(parts, [
    { text: "Veja " },
    { text: "https://boss.example.com/fatura", href: "https://boss.example.com/fatura" },
    { text: " e pronto" },
  ]);
});

test("o ponto final da frase não entra no link", () => {
  const parts = linkParts("Saiba mais: https://site.com/x.");
  assert.equal(parts[1].text, "https://site.com/x");
  assert.equal(parts[2].text, ".");
});

test("parêntese dentro do link continua no link", () => {
  const parts = linkParts("veja https://pt.wikipedia.org/wiki/Correio_(desambiguação)");
  assert.equal(parts[1].href, "https://pt.wikipedia.org/wiki/Correio_(desambiguação)");
});

test("endereço de e-mail vira link de e-mail", () => {
  const parts = linkParts("escreva para ana@fornecedor.com.br");
  assert.equal(parts[1].href, "mailto:ana@fornecedor.com.br");
});

test("link fraudulento não vira link", () => {
  const parts = linkParts("clique javascript:alert(1) ou data:text/html,<b>");
  assert.ok(parts.every((part) => !part.href), "nada aqui pode ser clicável");
});

test("o endereço é montado por nós, e não copiado do e-mail", () => {
  const parts = linkParts("www.site.com");
  assert.equal(parts[0].href, "https://www.site.com", "sem esquema — só https");
});

test("e-mail sem links continua um trecho só", () => {
  assert.deepEqual(linkParts("Só texto"), [{ text: "Só texto" }]);
});

test("link longo aparece curto, mas o domínio fica inteiro", () => {
  const long =
    "https://clickemailmkt.hameseventos.com.br/ls/click?upn=u001.sO74cqE-2B6teaUtW3LdvB9qb4oPmNGOjjtwtVV5ba";
  const shown = shortLink(long);

  assert.ok(shown.startsWith("clickemailmkt.hameseventos.com.br/"), "o nome do site não é cortado");
  assert.ok(shown.endsWith("…"));
  assert.ok(shown.length <= 73);
});

test("link curto fica como está, só sem o esquema", () => {
  assert.equal(shortLink("https://boss.example.com/fatura"), "boss.example.com/fatura");
  assert.equal(shortLink("mailto:ana@fornecedor.com.br"), "ana@fornecedor.com.br");
});

test("nome de site longo não é cortado a ponto de ficar irreconhecível", () => {
  const shown = shortLink(`https://${"o".repeat(90)}.com/caminho`);
  assert.ok(shown.endsWith("/…"), "o caminho some inteiro, o domínio fica");
});

test("a regra se lê em português", () => {
  assert.equal(
    describeRule({
      condition_kind: "sender_contains",
      condition_value: "advogad",
      action_kind: "set_min_priority",
      action_value: "85",
    }),
    "Se o remetente contém «advogad» — prioridade no mínimo 85",
  );
  assert.equal(
    describeRule({
      condition_kind: "amount_over",
      condition_value: "50000",
      action_kind: "set_category",
      action_value: "payments",
    }),
    "Se o valor for maior que 50000 — mover para a categoria «Pagamentos»",
  );
});

test("regra incompreensível não finge ser compreensível", () => {
  assert.match(
    describeRule({
      condition_kind: "moon_phase",
      condition_value: "x",
      action_kind: "set_min_priority",
      action_value: "1",
    }),
    /excluí-la/,
  );
});

test("campo numérico só para prioridade", () => {
  assert.equal(ruleWantsNumber("set_min_priority"), true);
  assert.equal(ruleWantsNumber("set_max_priority"), true);
  assert.equal(ruleWantsNumber("set_category"), false);
});

test("o lembrete diz quando o e-mail volta, e não «há N dias»", () => {
  const now = new Date(2026, 9, 11, 10, 0);
  assert.match(untilLabel(new Date(2026, 9, 12, 14, 30).toISOString(), now), /^amanhã 14:30$/);
  assert.equal(untilLabel(new Date(2026, 9, 14, 9, 0).toISOString(), now), "em 3 dias");
  assert.match(untilLabel(new Date(2026, 9, 11, 18, 0).toISOString(), now), /^hoje/);
  assert.equal(untilLabel(new Date(2026, 9, 25, 9, 0).toISOString(), now), "25/10");
  assert.equal(untilLabel(null, now), "");
});

test("a tradução é para e-mail estrangeiro, não para o português", () => {
  assert.equal(isMostlyPortuguese("Olá! Pague até sexta: R$ 56.315,00"), true);
  assert.equal(
    isMostlyPortuguese("Prezado cliente, sua fatura de outubro já está disponível no app."),
    true,
  );
  assert.equal(isMostlyPortuguese("Your payment to Anthropic, PBC was unsuccessful"), false);
  assert.equal(isMostlyPortuguese("I need a car or a bike, so do it as soon as you can"), false);
  // Russo («Fatura a pagar até sexta»), escrito com escapes para o
  // código-fonte ficar só em alfabeto latino.
  const russian =
    "\u0421\u0447\u0451\u0442 \u043d\u0430 \u043e\u043f\u043b\u0430\u0442\u0443 " +
    "\u0434\u043e \u043f\u044f\u0442\u043d\u0438\u0446\u044b";
  assert.equal(isMostlyPortuguese(russian), false);
  assert.equal(
    isMostlyPortuguese("Hola, gracias por su pago. Usted tiene una factura pendiente."),
    false,
  );
  // Links em inglês não tornam estrangeiro um e-mail em português.
  assert.equal(
    isMostlyPortuguese("Pague a sua fatura aqui: https://pay.example.com/invoice/payment/now/12345"),
    true,
  );
  assert.equal(isMostlyPortuguese("12345 — 678"), true, "sem letras não há o que traduzir");
  assert.equal(isMostlyPortuguese("https://example.com/only/link"), true);
});
