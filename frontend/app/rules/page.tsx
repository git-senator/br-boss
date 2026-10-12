import Link from "next/link";

import {
  createRuleAction,
  deleteRuleAction,
  parseRuleAction,
  toggleRuleAction,
} from "@/app/actions";
import { Nav } from "@/components/nav";
import { listRules, type RuleDraft, type RuleRow } from "@/lib/api";
import { categoryLabel, describeRule, ruleWantsNumber } from "@/lib/format";

export const dynamic = "force-dynamic";

const FIELD =
  "field mt-1";
const BUTTON =
  "btn-main";
const QUIET =
  "btn-quiet";

// Exemplos tirados direto da especificação: a pessoa vê na hora que tipo de frase é entendido.
const EXAMPLES = [
  "Tudo que vier de advogado é importante",
  "Sempre me mostrar e-mails do Banco Inter",
  "Boleto acima de R$ 50.000 — prioridade 90+",
  "E-mails da Receita Federal são urgentes",
  "Esconder publicidade de imóveis",
];

function readDraft(raw: string | undefined): RuleDraft | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as RuleDraft;
  } catch {
    return null;
  }
}

/**
 * Como a IA entendeu a frase. Nada foi salvo ainda: a pessoa confere
 * a regra escrita em português e, se precisar, ajusta o texto ou o número.
 *
 * O tipo de condição e de ação não é editável — se a IA entendeu errado,
 * é mais fácil dizer de outro jeito do que montar a regra com listas suspensas.
 */
function Draft({ draft, categories }: { draft: RuleDraft; categories: string[] }) {
  if (!draft.understood) {
    return (
      <div className="note-bad mt-4 p-4!">
        <p className="font-medium text-ink">Não entendi a regra</p>
        <p className="mt-1 text-sm text-ink-dim">{draft.explanation}</p>
      </div>
    );
  }

  const conditionIsCategory = draft.condition_kind === "category_is";
  const actionIsNumber = ruleWantsNumber(draft.action_kind);

  return (
    <form action={createRuleAction} className="ai-frame mt-4 p-5">
      <p className="text-xs tracking-wide text-ink-faint uppercase">Como eu entendi</p>
      <p className="mt-1 text-lg font-medium text-ink">{describeRule(draft)}</p>
      <p className="mt-1 text-sm text-ink-dim">{draft.explanation}</p>

      <input type="hidden" name="title" value={draft.title} />
      <input type="hidden" name="condition_kind" value={draft.condition_kind} />
      <input type="hidden" name="action_kind" value={draft.action_kind} />

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-sm text-ink-dim">
            {draft.condition_kind === "amount_over" ? "Valor acima de" : "O que procurar"}
          </span>
          {conditionIsCategory ? (
            <select name="condition_value" defaultValue={draft.condition_value} className={FIELD}>
              {categories.map((key) => (
                <option key={key} value={key}>
                  {categoryLabel(key)}
                </option>
              ))}
            </select>
          ) : (
            <input
              name="condition_value"
              defaultValue={draft.condition_value}
              required
              maxLength={500}
              className={FIELD}
            />
          )}
        </label>

        <label className="block">
          <span className="text-sm text-ink-dim">
            {actionIsNumber ? "Prioridade, 0–100" : "Categoria"}
          </span>
          {actionIsNumber ? (
            <input
              name="action_value"
              type="number"
              min={0}
              max={100}
              defaultValue={draft.action_value}
              required
              className={FIELD}
            />
          ) : (
            <select name="action_value" defaultValue={draft.action_value} className={FIELD}>
              {categories.map((key) => (
                <option key={key} value={key}>
                  {categoryLabel(key)}
                </option>
              ))}
            </select>
          )}
        </label>
      </div>

      <label className="mt-3 flex items-center gap-2 text-sm text-ink-dim">
        <input type="checkbox" name="apply_to_existing" defaultChecked />
        Aplicar também aos e-mails já analisados
      </label>

      <div className="mt-3 flex items-center gap-3">
        <button type="submit" className={BUTTON}>
          Salvar regra
        </button>
        <Link href="/rules" className="text-sm text-ink-dim transition-colors duration-150 hover:text-ink">
          Cancelar
        </Link>
      </div>
    </form>
  );
}

function RuleItem({ rule, removing }: { rule: RuleRow; removing: boolean }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className={rule.is_active ? "text-ink" : "text-ink-faint line-through"}>
          {describeRule(rule)}
        </p>
        {rule.title ? <p className="mt-0.5 truncate text-xs text-ink-faint">“{rule.title}”</p> : null}
      </div>

      {removing ? (
        <div className="flex items-center gap-2">
          <span className="text-sm text-alarm">Excluir regra?</span>
          <form action={deleteRuleAction}>
            <input type="hidden" name="id" value={rule.id} />
            <button className="btn-danger">
              Sim, excluir
            </button>
          </form>
          <Link href="/rules" className="text-sm text-ink-dim transition-colors duration-150 hover:text-ink">
            Cancelar
          </Link>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <form action={toggleRuleAction}>
            <input type="hidden" name="id" value={rule.id} />
            <input type="hidden" name="is_active" value={String(!rule.is_active)} />
            <button className={QUIET}>{rule.is_active ? "Desativar" : "Ativar"}</button>
          </form>
          <Link href={`/rules?remove=${rule.id}`} className={QUIET}>
            Excluir
          </Link>
        </div>
      )}
    </li>
  );
}

export default async function RulesPage({
  searchParams,
}: {
  searchParams: Promise<{
    draft?: string;
    error?: string;
    text?: string;
    saved?: string;
    remove?: string;
  }>;
}) {
  const { draft: rawDraft, error, text, saved, remove } = await searchParams;
  const draft = readDraft(rawDraft);
  const { items: rules, categories } = await listRules();

  return (
    <div>
      <Nav active="rules" />

      <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
        <h1 className="text-2xl font-bold tracking-tight text-white">Regras</h1>
        <p className="mt-1 text-sm text-ink-dim">
          As regras valem mais que a avaliação da IA. Se duas regras entrarem em conflito,
          “aumentar” vence “diminuir”: mostrar algo a mais é só um incômodo, esconder algo
          importante pode custar dinheiro.
        </p>

        <form action={parseRuleAction} className="glass-card mt-5 rounded-2xl p-5">
          <label className="block">
            <span className="font-medium text-ink">Escreva a regra com suas próprias palavras</span>
            <input
              name="text"
              required
              maxLength={500}
              defaultValue={draft?.title ?? text ?? ""}
              placeholder={EXAMPLES[0]}
              className={FIELD}
            />
          </label>
          <p className="mt-2 text-xs text-ink-faint">Por exemplo: {EXAMPLES.join(" · ")}</p>

          {error ? (
            <p className="note-bad mt-3">
              {error}
            </p>
          ) : null}

          <button type="submit" className={`${BUTTON} mt-3`}>
            Analisar
          </button>
        </form>

        {draft ? <Draft draft={draft} categories={categories} /> : null}

        {saved !== undefined ? (
          <p className="note-ok mt-3">
            Regra salva.{" "}
            {Number(saved) > 0
              ? `E-mails já analisados que foram alterados: ${saved}.`
              : "Os novos e-mails serão analisados com base nela."}
          </p>
        ) : null}

        <h2 className="mt-6 text-sm font-medium tracking-wide text-ink-dim uppercase">
          Ativas agora: {rules.filter((rule) => rule.is_active).length}
        </h2>
        {rules.length === 0 ? (
          <p className="mt-2 text-sm text-ink-faint">Nenhuma regra ainda — por enquanto, só a IA organiza seus e-mails.</p>
        ) : (
          <ul className="glass-card mt-2 divide-y divide-white/10 overflow-hidden rounded-2xl">
            {rules.map((rule) => (
              <RuleItem key={rule.id} rule={rule} removing={String(remove) === String(rule.id)} />
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
