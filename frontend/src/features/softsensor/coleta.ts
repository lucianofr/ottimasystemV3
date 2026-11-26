/**
 * Lógica pura da página "Coleta e treino" (RF-589): sem React, sem rede — testada em
 * `coleta.check.ts`. O backend manda `stats` e `progress` como dicionário aberto, então cada
 * leitura aqui valida o tipo em vez de confiar na forma.
 */

import type { DatasetOut, MlJobOut } from "./types";

/** Períodos aceitos pelo modelo (`ottima_core.softsensor.PERIODS_S`); o 422 do POST confere. */
export const PERIODOS_S = [1, 2, 5, 10, 30, 60, 300, 600] as const;

/** Teto de entradas por conjunto (`MAX_DATASET_TAGS` em `routers/softsensor_lab.py`). */
export const TETO_ENTRADAS = 32;

/** Janela máxima do `/api/history` (`MAX_WINDOW_DAYS`): acima disso é 422. */
const JANELA_MAX_S = 31 * 86400;
const JANELA_MIN_S = 60;

/** Fuso IANA do navegador: a API interpreta as datas SEM fuso do CSV de laboratório nele. */
export function fusoDoNavegador(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** Hora local de `agora` no formato do `<input type="datetime-local">` (sem segundos, logo
 *  nunca no futuro — a API recusa data de coleta futura). */
export function agoraLocal(agora: Date = new Date()): string {
  const dois = (n: number) => String(n).padStart(2, "0");
  return `${String(agora.getFullYear())}-${dois(agora.getMonth() + 1)}-${dois(agora.getDate())}T${dois(agora.getHours())}:${dois(agora.getMinutes())}`;
}

function numero(dados: Record<string, unknown>, chave: string): number {
  const valor = dados[chave];
  return typeof valor === "number" && Number.isFinite(valor) ? valor : 0;
}

export function resumoPareamento(stats: DatasetOut["stats"]): string {
  const analises = numero(stats, "analyses");
  if (analises === 0) return "Nenhuma análise no período";
  return [
    `Emparelhadas ${String(numero(stats, "paired"))} de ${String(analises)}`,
    `${String(numero(stats, "dropped_no_process"))} sem dado de processo no instante da coleta`,
    `${String(numero(stats, "full_window"))} com janela completa`,
  ].join(" · ");
}

export function temJobAtivo(jobs: readonly Pick<MlJobOut, "status">[] | undefined): boolean {
  return jobs?.some((job) => job.status === "queued" || job.status === "running") ?? false;
}

export function podeFinalizar(conjunto: Pick<DatasetOut, "status">): boolean {
  return conjunto.status === "collecting";
}

/** `null` sem `done`/`total` numéricos (ou com total 0): a tela desenha o `<progress>`
 *  indeterminado em vez de dividir por zero. */
export function progressoDoJob(
  job: Pick<MlJobOut, "progress">,
): { feito: number; total: number } | null {
  const { done, total } = job.progress;
  if (typeof done !== "number" || typeof total !== "number" || !(total > 0)) return null;
  return { feito: done, total };
}

/** Marca/desmarca a tag preservando a ORDEM de marcação (é a ordem das colunas do modelo). No
 *  teto devolve o MESMO array, para o chamador distinguir "recusado" de "alterado". */
export function alternarEntrada(selecionadas: readonly number[], tagId: number): readonly number[] {
  if (selecionadas.includes(tagId)) return selecionadas.filter((id) => id !== tagId);
  if (selecionadas.length >= TETO_ENTRADAS) return selecionadas;
  return [...selecionadas, tagId];
}

/**
 * Janela do trend das entradas: `[start_ts, end_ts]`, ou `[start_ts, agora]` enquanto coleta
 * (`fimEpochS: null` = ao vivo no `useHistory`). Largura arredondada para cima ao minuto — vira
 * chave de cache e de estrutura do gráfico, então tem de ser estável — com piso de 1 min
 * (`start >= end` é 422 no `/api/history`) e teto de 31 dias.
 */
export function janelaDoConjunto(
  conjunto: Pick<DatasetOut, "start_ts" | "end_ts">,
  agoraMs: number,
): { janelaSegundos: number; fimEpochS: number | null } {
  const fimMs = conjunto.end_ts === null ? agoraMs : Date.parse(conjunto.end_ts);
  const segundos = Math.ceil((fimMs - Date.parse(conjunto.start_ts)) / 60000) * 60;
  return {
    janelaSegundos: Math.min(JANELA_MAX_S, Math.max(JANELA_MIN_S, segundos)),
    fimEpochS: conjunto.end_ts === null ? null : fimMs / 1000,
  };
}
