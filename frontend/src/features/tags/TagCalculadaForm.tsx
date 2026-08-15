import { useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import {
  ApiError,
  type CalculatedTagCreate,
  type CalculatedTagOut,
  type CalculatedTagUpdate,
  type TagOut,
} from "../../lib/api";
import { MAX_ENTRADAS, mover, rotuloEntrada, validarTagCalculada } from "./tagCalculada";
import {
  formatarPeriodo,
  PERIODO_OPCOES,
  useCreateCalculatedTag,
  useUpdateCalculatedTag,
  type PeriodoSegundos,
} from "./useCalculatedTags";

interface Valores {
  name: string;
  eu: string;
  description: string;
  period_seconds: PeriodoSegundos;
  code: string;
}

interface Props {
  /** `null` = criar; caso contrário, edita a tag calculada. */
  tag: CalculatedTagOut | null;
  /** Entradas elegíveis para IN1..INn: já filtradas por projeto e sem a própria tag
   *  (`tagCalculada.ts::tagsElegiveis`, chamado pela página). */
  tagsDisponiveis: TagOut[];
  projectId: number;
  onClose: () => void;
}

/** Tab indenta em vez de sair do campo (spec F3 §6.2: sem editor de código de terceiros).
 *  Copiado verbatim de `flows/config/ModalConfigBloco.tsx::indentarComTab` — não exportado de
 *  lá, mesma decisão de não introduzir um editor de terceiros vale para a tag calculada. */
function indentarComTab(evento: KeyboardEvent<HTMLTextAreaElement>): void {
  if (evento.key !== "Tab" || evento.shiftKey || evento.ctrlKey || evento.altKey || evento.metaKey) {
    return;
  }
  evento.preventDefault();
  const campo = evento.currentTarget;
  campo.setRangeText("    ", campo.selectionStart, campo.selectionEnd, "end");
}

export function TagCalculadaForm({ tag, tagsDisponiveis, projectId, onClose }: Props) {
  const [v, setV] = useState<Valores>(() => ({
    name: tag?.name ?? "",
    eu: tag?.eu ?? "",
    description: tag?.description ?? "",
    period_seconds: tag?.period_seconds ?? PERIODO_OPCOES[0],
    code: tag?.code ?? "",
  }));
  // Um id de tag por posição, na ordem IN1..INn — a posição É o índice (rotuloEntrada).
  const [entradas, setEntradas] = useState<number[]>(() => tag?.input_tag_ids ?? []);
  const [erros, setErros] = useState<string[]>([]);
  const criar = useCreateCalculatedTag();
  const atualizar = useUpdateCalculatedTag();
  const editando = tag !== null;
  const enviando = criar.isPending || atualizar.isPending;

  function mudar<K extends keyof Valores>(campo: K, valor: Valores[K]): void {
    setV((atual) => ({ ...atual, [campo]: valor }));
  }

  async function onSubmit(e: FormEvent): Promise<void> {
    e.preventDefault();
    // Checagens locais e baratas só (`tagCalculada.ts::validarTagCalculada`); `OUT` ausente,
    // `IN<n>` fora do range, sintaxe e dunder voltam como 422 do backend (AST) e caem no
    // mesmo catch abaixo.
    const locais = validarTagCalculada({ name: v.name, code: v.code, inputTagIds: entradas });
    setErros(locais);
    if (locais.length > 0) return;

    const comum = {
      name: v.name.trim(),
      eu: v.eu.trim(),
      description: v.description.trim(),
      period_seconds: v.period_seconds,
      code: v.code,
      input_tag_ids: entradas,
    };
    try {
      if (editando) {
        const corpo: CalculatedTagUpdate = comum;
        await atualizar.mutateAsync({ id: tag.id, body: corpo });
      } else {
        const corpo: CalculatedTagCreate = { ...comum, project_id: projectId };
        await criar.mutateAsync(corpo);
      }
      onClose();
    } catch (err) {
      setErros([err instanceof ApiError ? err.message : "Erro de comunicação com o servidor"]);
    }
  }

  return (
    <Card className="p-6">
      <h2 className="plaqueta text-xs text-fg-muted">
        {editando ? "Editar tag calculada" : "Nova tag calculada"}
      </h2>
      <form
        data-testid="calc-form"
        onSubmit={(e) => void onSubmit(e)}
        className="mt-4 space-y-6"
        noValidate
      >
        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="calc-name">Nome</Label>
            <Input
              id="calc-name"
              data-testid="calc-name"
              value={v.name}
              onChange={(e) => mudar("name", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="calc-eu">EU</Label>
            <Input
              id="calc-eu"
              data-testid="calc-eu"
              placeholder="degC, %, m3/h"
              value={v.eu}
              onChange={(e) => mudar("eu", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="calc-period">Periodicidade (s)</Label>
            <Select
              id="calc-period"
              data-testid="calc-period"
              className="process-value"
              value={String(v.period_seconds)}
              onChange={(e) => mudar("period_seconds", Number(e.target.value) as PeriodoSegundos)}
            >
              {PERIODO_OPCOES.map((opcao) => (
                <option key={opcao} value={String(opcao)}>
                  {formatarPeriodo(opcao)}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="calc-description">Descrição</Label>
          <Input
            id="calc-description"
            data-testid="calc-description"
            value={v.description}
            onChange={(e) => mudar("description", e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label>Entradas ordenadas (IN1..INn)</Label>
          {entradas.map((tagId, indice) => (
            // eslint-disable-next-line react/no-array-index-key -- a posição É a identidade da
            // linha (o rótulo IN<n> vem do índice); trocar de tag numa posição só troca o
            // `value` do mesmo `<select>`, o que é o comportamento correto aqui.
            <div key={indice} className="flex items-center gap-2">
              <span className="process-value w-10 shrink-0 text-xs text-fg-muted">
                {rotuloEntrada(indice)}
              </span>
              <Select
                aria-label={rotuloEntrada(indice)}
                data-testid={`calc-input-${String(indice + 1)}`}
                className="flex-1"
                value={String(tagId)}
                onChange={(e) => {
                  const escolhido = Number(e.target.value);
                  setEntradas((atual) => atual.map((item, i) => (i === indice ? escolhido : item)));
                }}
              >
                {tagsDisponiveis.map((disponivel) => (
                  <option key={disponivel.id} value={String(disponivel.id)}>
                    {disponivel.name}
                  </option>
                ))}
              </Select>
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label={`Subir ${rotuloEntrada(indice)}`}
                data-testid={`calc-input-up-${String(indice + 1)}`}
                disabled={indice === 0}
                onClick={() => setEntradas((atual) => mover(atual, indice, indice - 1))}
              >
                Subir
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label={`Descer ${rotuloEntrada(indice)}`}
                data-testid={`calc-input-down-${String(indice + 1)}`}
                disabled={indice === entradas.length - 1}
                onClick={() => setEntradas((atual) => mover(atual, indice, indice + 1))}
              >
                Descer
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label={`Remover ${rotuloEntrada(indice)}`}
                data-testid={`calc-input-remove-${String(indice + 1)}`}
                onClick={() => setEntradas((atual) => atual.filter((_, i) => i !== indice))}
              >
                Remover
              </Button>
            </div>
          ))}
          <Button
            type="button"
            size="sm"
            data-testid="calc-input-add"
            disabled={entradas.length >= MAX_ENTRADAS || tagsDisponiveis.length === 0}
            onClick={() => setEntradas((atual) => [...atual, tagsDisponiveis[0]?.id ?? 0])}
          >
            Adicionar entrada
          </Button>
          <p className="text-xs text-fg-muted">
            Remover ou reordenar uma entrada renumera IN1..INn — ajuste o script para a nova
            ordem.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="calc-code">Script</Label>
          <textarea
            id="calc-code"
            data-testid="calc-code"
            rows={12}
            spellCheck={false}
            value={v.code}
            onChange={(e) => mudar("code", e.target.value)}
            onKeyDown={indentarComTab}
            className="w-full rounded-sm border border-border bg-well p-2 font-mono text-xs leading-relaxed text-fg focus-visible:outline-2 focus-visible:outline-accent"
          />
          <p className="text-[10px] text-fg-muted">
            Escopo disponível: IN1..INn, state, math, numpy (np). O resultado deve ser atribuído
            a OUT. Tab insere quatro espaços.
          </p>
        </div>

        {erros.length > 0 && (
          // Regra do Canal Redundante: cor + ícone + texto (DESIGN.md §Colors)
          <ul role="alert" data-testid="calc-form-error" className="space-y-1 text-sm text-alarm">
            {erros.map((erro) => (
              <li key={erro} className="flex items-center gap-2">
                <svg
                  aria-hidden="true"
                  width="14"
                  height="14"
                  viewBox="0 0 16 16"
                  fill="currentColor"
                  className="shrink-0"
                >
                  <path d="M8 1 15 14H1L8 1Zm-.75 5v4h1.5V6h-1.5Zm0 5.5V13h1.5v-1.5h-1.5Z" />
                </svg>
                {erro}
              </li>
            ))}
          </ul>
        )}

        <div className="flex gap-3">
          <Button type="submit" data-testid="calc-submit" disabled={enviando}>
            {enviando ? "Salvando…" : "Salvar"}
          </Button>
          <Button type="button" variant="outline" data-testid="calc-cancel" onClick={onClose}>
            Cancelar
          </Button>
        </div>
      </form>
    </Card>
  );
}
