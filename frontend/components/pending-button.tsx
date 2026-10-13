"use client";

import { useFormStatus } from "react-dom";

/**
 * Botão de formulário que avisa que o trabalho está em andamento. Tradução
 * ou rascunho podem levar até um minuto — sem isso parece que o clique não
 * funcionou, e a pessoa clica de novo. Sem JavaScript, é um botão comum.
 *
 * Se o formulário tem vários botões, name/value identificam o clicado: só
 * ele mostra «aguarde», mas todos ficam bloqueados enquanto isso.
 */
export function PendingButton({
  children,
  pending,
  className,
  title,
  name,
  value,
  formAction,
  formNoValidate,
}: {
  children: React.ReactNode;
  pending: React.ReactNode;
  className?: string;
  title?: string;
  name?: string;
  value?: string;
  formAction?: (form: FormData) => void | Promise<void>;
  formNoValidate?: boolean;
}) {
  const status = useFormStatus();
  const mine = status.pending && (!name || status.data?.get(name) === value);
  return (
    <button
      type="submit"
      disabled={status.pending}
      aria-busy={mine}
      className={`${className ?? ""} disabled:cursor-wait disabled:opacity-70`}
      title={title}
      name={name}
      value={value}
      formAction={formAction}
      formNoValidate={formNoValidate}
    >
      {mine ? pending : children}
    </button>
  );
}
