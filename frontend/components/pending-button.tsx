"use client";

import { useFormStatus } from "react-dom";

/**
 * Botão de formulário que avisa que o trabalho está em andamento. Tradução
 * ou rascunho podem levar até um minuto — sem isso parece que o clique não
 * funcionou, e a pessoa clica de novo. Sem JavaScript, é um botão comum.
 */
export function PendingButton({
  children,
  pending,
  className,
  title,
}: {
  children: React.ReactNode;
  pending: React.ReactNode;
  className?: string;
  title?: string;
}) {
  const status = useFormStatus();
  return (
    <button
      type="submit"
      disabled={status.pending}
      aria-busy={status.pending}
      className={`${className ?? ""} disabled:cursor-wait disabled:opacity-70`}
      title={title}
    >
      {status.pending ? pending : children}
    </button>
  );
}
