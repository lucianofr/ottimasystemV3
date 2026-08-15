/**
 * Escopo por projeto ativo (ADR-033, ADR-017): uma tag pertence ao projeto de duas formas
 * distintas — uma tag OPC pertence via a conexão (o worker só reconecilia o projeto ativo),
 * uma tag calculada pertence direto (`connection_id === null`, `project_id` setado). Uma pena
 * fora desse recorte desenharia vazia para sempre; daí o teste dedicado.
 */

import type { TagOut } from "../../lib/api";

/** `true` quando `tag` pertence ao projeto ativo, seja por conexão (tag OPC) seja por
 *  `project_id` direto (tag calculada). */
export function tagDoProjeto(
  tag: TagOut,
  idsConexaoDoProjeto: ReadonlySet<number>,
  projetoId: number,
): boolean {
  if (tag.connection_id === null) return tag.project_id === projetoId;
  return idsConexaoDoProjeto.has(tag.connection_id);
}
