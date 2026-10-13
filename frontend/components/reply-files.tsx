"use client";

import { Paperclip, X } from "lucide-react";
import { useRef, useState } from "react";

import { fileSize, replyFilesProblem } from "@/lib/format";

/** O mesmo arquivo escolhido duas vezes é anexado uma vez só. */
function sameFile(file: File): string {
  return `${file.name}\u0000${file.size}\u0000${file.lastModified}`;
}

/**
 * Arquivos da resposta: o botão «Anexar arquivos», a lista do que foi
 * escolhido com o tamanho e um x, e arrastar direto para o campo de resposta.
 *
 * A lista vive no próprio campo de arquivos (input.files) — ou seja, os
 * arquivos vão junto com o formulário num POST comum, como todo o resto.
 * Excesso de quantidade ou de peso marca o campo como inválido, e o
 * navegador simplesmente não envia o formulário — saber disso antes de
 * subir 25 MB é melhor do que depois.
 *
 * lost — o que estava anexado à resposta que não foi. Os arquivos não
 * ficam com a gente, precisam ser anexados de novo — é o que diz o aviso.
 */
export function ReplyFiles({
  children,
  lost,
  buttonClassName,
}: {
  children: React.ReactNode;
  lost: string[];
  buttonClassName: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const problem = replyFilesProblem(files);

  function apply(next: File[]) {
    const element = input.current;
    if (!element) return;
    const transfer = new DataTransfer();
    for (const file of next) transfer.items.add(file);
    element.files = transfer.files;
    element.setCustomValidity(replyFilesProblem(next) ?? "");
    setFiles(next);
  }

  function add(picked: FileList | null) {
    if (!picked || picked.length === 0) {
      // A janela de escolha foi fechada sem escolher nada — a lista anterior fica.
      apply(files);
      return;
    }
    const known = new Set(files.map(sameFile));
    apply([...files, ...Array.from(picked).filter((file) => !known.has(sameFile(file)))]);
  }

  function hasFiles(event: React.DragEvent): boolean {
    // Se arrastam texto, é uma edição comum do campo — não atrapalhamos.
    return Array.from(event.dataTransfer.types).includes("Files");
  }

  return (
    <>
      <div
        className="relative"
        onDragOver={(event) => {
          if (!hasFiles(event)) return;
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          if (!hasFiles(event)) return;
          event.preventDefault();
          setDragging(false);
          add(event.dataTransfer.files);
        }}
      >
        {children}
        {dragging ? (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-xl border-2 border-dashed border-link/60 bg-link/15 text-xs font-medium text-white">
            Solte aqui — os arquivos serão anexados à resposta
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {/* Não hidden, e sim sr-only: num campo oculto o navegador não
            consegue mostrar por que o formulário não é enviado. */}
        <input
          ref={input}
          type="file"
          name="files"
          multiple
          tabIndex={-1}
          className="sr-only"
          onChange={(event) => add(event.target.files)}
        />
        <button type="button" className={buttonClassName} onClick={() => input.current?.click()}>
          <Paperclip className="h-3.5 w-3.5" aria-hidden />
          Anexar arquivos
        </button>
        {files.map((file, index) => (
          <span
            key={sameFile(file)}
            className="glass-pill flex max-w-full items-center gap-1.5 rounded-xl py-1 pr-1.5 pl-3 text-xs text-ink-dim"
          >
            <span className="truncate">
              {file.name} · {fileSize(file.size)}
            </span>
            <button
              type="button"
              className="rounded-md p-0.5 text-ink-faint hover:bg-white/10 hover:text-white"
              aria-label={`Remover ${file.name}`}
              title="Remover"
              onClick={() => apply(files.filter((_, at) => at !== index))}
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </span>
        ))}
      </div>

      {problem ? <p className="text-xs text-alarm">{problem}</p> : null}
      {files.length === 0 && lost.length > 0 ? (
        <p className="text-[11px] text-watch">
          Os arquivos não ficam guardados aqui — anexe-os de novo: {lost.join(", ")}.
        </p>
      ) : null}
    </>
  );
}
