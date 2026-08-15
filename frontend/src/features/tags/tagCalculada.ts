/**
 * Lógica pura de tag calculada (ADR-033): rótulo posicional IN1..INn, discriminador de tag
 * calculada, elegibilidade de entrada e reordenação imutável, mais as checagens locais e
 * baratas do formulário. `OUT` ausente, `IN<n>` fora do range, erro de sintaxe, nome dunder e
 * nome duplicado no projeto são 422 do backend (AST em `routers/calculated_tags.py`) — não
 * duplicados aqui, só devolvidos como `ApiError` na mesma lista de erros do formulário.
 */

import type { TagOut } from "../../lib/api";

/** `calculated_tag_inputs.position` vai de 1 a 8 (migration `0012_calculated_tags`). */
export const MAX_ENTRADAS = 8;

/** Rótulo posicional de uma entrada: índice 0 do array vira IN1. */
export function rotuloEntrada(indice: number): string {
  return `IN${String(indice + 1)}`;
}

/** Tag calculada = linha de `tags` sem conexão (`connection_id IS NULL`, ADR-033 D1). Único
 *  ponto de comparação do discriminador — nenhum outro lugar repete `=== null`. */
export function eCalculada(tag: TagOut): boolean {
  return tag.connection_id === null;
}

/**
 * Entradas elegíveis para IN1..INn: tags OPC de uma conexão do projeto ativo, ou tags
 * calculadas do próprio projeto — nunca a tag em edição (auto-referência é recusada pelo banco,
 * `calculated_tag_inputs.source_tag_id <> calc_tag_id`).
 */
export function tagsElegiveis(
  todas: TagOut[],
  projectId: number | null,
  conexoesDoProjeto: Set<number>,
  excluirTagId: number | null,
): TagOut[] {
  return todas.filter((tag) => {
    if (tag.id === excluirTagId) return false;
    if (eCalculada(tag)) return tag.project_id === projectId;
    return tag.connection_id !== null && conexoesDoProjeto.has(tag.connection_id);
  });
}

/** Reordena imutavelmente (Subir/Descer); índice de origem ou destino fora da faixa devolve
 *  uma cópia da lista original sem tocar em nada. */
export function mover<T>(itens: readonly T[], de: number, para: number): T[] {
  if (de < 0 || de >= itens.length || para < 0 || para >= itens.length) return [...itens];
  const copia = [...itens];
  const [item] = copia.splice(de, 1);
  copia.splice(para, 0, item as T);
  return copia;
}

export interface ValoresTagCalculada {
  name: string;
  code: string;
  /** Id da tag em cada posição, na ordem de IN1..INn. */
  inputTagIds: readonly number[];
}

/** Checagens locais e baratas (nome/script vazios, tag duplicada, excesso de entradas). O
 *  resto é validação de AST do backend, devolvida como `ApiError` e mostrada na mesma lista. */
export function validarTagCalculada(valores: ValoresTagCalculada): string[] {
  const erros: string[] = [];
  if (!valores.name.trim()) erros.push("Nome é obrigatório");
  if (!valores.code.trim()) erros.push("Script é obrigatório");
  if (valores.inputTagIds.length > MAX_ENTRADAS) {
    erros.push(`No máximo ${String(MAX_ENTRADAS)} entradas`);
  }
  if (new Set(valores.inputTagIds).size !== valores.inputTagIds.length) {
    erros.push("A mesma tag não pode ocupar duas entradas");
  }
  return erros;
}
