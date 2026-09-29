import type { TagOut } from "../../../lib/api";

/**
 * Tags do seletor dos blocos de tag (spec F3 §4.1): o OPC-Read aceita também tags de
 * ESCRITA — readback do último valor escrito (ex.: lógica de incremento sobre a MV, cuja
 * série o opc-worker publica quando o servidor declara CurrentRead). O OPC-Write segue
 * restrito a tags `w`.
 */
export function tagsDoSeletor(tags: readonly TagOut[], direcao: "r" | "w"): readonly TagOut[] {
  return direcao === "r" ? tags : tags.filter((tag) => tag.direction === "w");
}

/** Sufixo do <option> para distinguir tags de escrita no seletor de leitura. */
export function sufixoDirecao(tag: TagOut, direcao: "r" | "w"): string {
  return direcao === "r" && tag.direction === "w" ? " · Escrita" : "";
}
