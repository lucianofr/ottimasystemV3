/**
 * Lógica pura da página "Coleta e treino" (RF-589): sem React, sem rede — testada em
 * `coleta.check.ts`. O backend manda `stats` e `progress` como dicionário aberto, então cada
 * leitura aqui valida o tipo em vez de confiar na forma.
 */

import { ApiError } from "../../lib/api";
import type { DatasetOut, MlJobOut } from "./types";

/** Períodos aceitos pelo modelo (`ottima_core.softsensor.PERIODS_S`); o 422 do POST confere. */
export const PERIODOS_S = [1, 2, 5, 10, 30, 60, 300, 600] as const;

/** Teto de entradas por conjunto (`MAX_DATASET_TAGS` em `routers/softsensor_lab.py`). */
export const TETO_ENTRADAS = 32;

/** Janela máxima do `/api/history` (`MAX_WINDOW_DAYS`): acima disso é 422. */
const JANELA_MAX_S = 31 * 86400;
const JANELA_MIN_S = 60;

/** Tique da janela ao vivo: a largura só é refeita a cada 5 min (ou antes, ver
 *  `janelaAoVivoDefasada`), porque cada refação recria o gráfico e perde o zoom. */
const TIQUE_JANELA_MS = 300_000;
const FOLGA_JANELA = 1.5;

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

/** Texto do erro de uma chamada: o `detail` do servidor (pt-BR) como veio. */
export function mensagem(erro: unknown): string {
  return erro instanceof ApiError ? erro.message : "Erro de comunicação com o servidor";
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

/** Tentar de novo: só a partir de `failed` (o backend refaz a montagem mantendo `end_ts`);
 *  em `collecting` quem age é `podeFinalizar`. */
export function podeRefazer(conjunto: Pick<DatasetOut, "status">): boolean {
  return conjunto.status === "failed";
}

/** Em montagem o DELETE devolve 409 (o job ainda lê o conjunto): cancele o job antes. */
export function podeExcluir(conjunto: Pick<DatasetOut, "status">): boolean {
  return conjunto.status !== "building";
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

/**
 * Ao vivo (sem `end_ts`) a largura de `janelaDoConjunto` envelhece: o gráfico desliza
 * `[agora - largura, agora]` e perde o começo da coleta. Refaz a largura no tique de 5 min, ou
 * antes quando o decorrido passa de 1,5x a largura (começo da coleta, janela de 1 min). No teto
 * de 31 dias a regra de 1,5x cala — refazer não alargaria nada. Encerrado: nunca (janela fixa).
 */
export function janelaAoVivoDefasada(
  conjunto: Pick<DatasetOut, "start_ts" | "end_ts">,
  janelaSegundos: number,
  calculadaEmMs: number,
  agoraMs: number,
): boolean {
  if (conjunto.end_ts !== null) return false;
  const decorridoS = (agoraMs - Date.parse(conjunto.start_ts)) / 1000;
  return (
    agoraMs - calculadaEmMs >= TIQUE_JANELA_MS ||
    (janelaSegundos < JANELA_MAX_S && decorridoS > FOLGA_JANELA * janelaSegundos)
  );
}
