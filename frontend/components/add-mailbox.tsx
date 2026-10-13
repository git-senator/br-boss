"use client";

import { useState } from "react";

import { addManyAction } from "@/app/actions";
import type { Service } from "@/lib/api";

/**
 * Conexão de caixas de e-mail.
 *
 * Um único campo para tudo: uma caixa ou trinta. Não há um formulário
 * "adicionar mais uma": com três dezenas de caixas seria uma noite de
 * trabalho; assim, a lista é colada de uma vez só.
 *
 * As dicas não aparecem todas de uma vez, só as dos serviços que a pessoa
 * realmente digitou: procurar o seu entre quatro é trabalho desnecessário.
 */

const DOMAINS: Record<string, string> = {
  "gmail.com": "google",
  "googlemail.com": "google",
  "outlook.com": "microsoft",
  "hotmail.com": "microsoft",
  "live.com": "microsoft",
  "msn.com": "microsoft",
  "outlook.com.br": "microsoft",
  "hotmail.com.br": "microsoft",
  "uol.com.br": "uol",
  "bol.com.br": "bol",
  "terra.com.br": "terra",
  "yahoo.com": "yahoo",
  "yahoo.com.br": "yahoo",
  "icloud.com": "apple",
  "me.com": "apple",
  "mac.com": "apple",
  "mail.ru": "mailru",
  "bk.ru": "mailru",
  "inbox.ru": "mailru",
  "list.ru": "mailru",
  "internet.ru": "mailru",
  "yandex.ru": "yandex",
  "yandex.com": "yandex",
  "ya.ru": "yandex",
};

const PLACEHOLDER = `boss@gmail.com abcd efgh ijkl mnop
trabalho@outlook.com senha-de-app
escritorio@hotmail.com senha-de-app`;

function servicesInText(text: string, services: Service[]): Service[] {
  const keys = new Set<string>();
  for (const match of text.matchAll(/@([\w.-]+)/g)) {
    const key = DOMAINS[match[1].toLowerCase()];
    if (key) keys.add(key);
  }
  return services.filter((service) => keys.has(service.key));
}

export function AddMailbox({ services, error }: { services: Service[]; error?: string }) {
  const [text, setText] = useState("");
  const found = servicesInText(text, services);
  const count = text.split("\n").filter((line) => line.includes("@")).length;

  return (
    <form action={addManyAction} className="glass-card rounded-2xl p-5">
      <label className="block">
        <span className="font-medium text-ink">Cole as caixas de e-mail, uma por linha</span>
        <span className="mt-0.5 block text-sm text-ink-dim">
          Endereço, espaço, senha. Uma ou trinta de uma vez.
        </span>
        <textarea
          name="list"
          required
          rows={5}
          spellCheck={false}
          placeholder={PLACEHOLDER}
          value={text}
          onChange={(event) => setText(event.target.value)}
          className="field mt-2 font-mono"
        />
      </label>

      {found.length > 0 ? (
        <div className="mt-3 rounded-xl border border-white/10 bg-white/[0.04] p-3">
          <p className="text-sm text-ink-dim">
            É preciso uma senha de app: os serviços de e-mail não aceitam a senha comum da conta.
            Crie a sua aqui:
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {found.map((service) => (
              <a
                key={service.key}
                href={service.help_url}
                target="_blank"
                rel="noreferrer"
                className="btn-quiet"
              >
                {service.label} →
              </a>
            ))}
          </div>
        </div>
      ) : null}

      {error ? (
        <p className="note-bad mt-3">{error}</p>
      ) : null}

      <button
        type="submit"
        className="btn-main mt-3"
      >
        {count > 1 ? `Conectar todas (${count})` : "Conectar"}
      </button>
      <p className="mt-2 text-xs text-ink-faint">
        Cada caixa é verificada separadamente. A que não conseguir se conectar
        não é salva; as demais serão conectadas normalmente.
      </p>
    </form>
  );
}
