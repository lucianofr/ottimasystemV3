/**
 * Decisões puras da tela MALHA (RF-645, RF-646): qual malha está selecionada, se o dado é "ao
 * vivo", a escala da barra, os ids das penas do trend, a ponta viva e a limpeza do histórico.
 * Sem React — a página só liga estas funções aos hooks; o que decide fica testável aqui
 * (`malhaLogica.check.ts`).
 */

import type { EstadoConexaoCanal } from "../../app/CanalAoVivo";
import { ROTULO_CONEXAO } from "../flows/useFlowStatus";
import type { FuzzyHistoryResponse } from "../fuzzy/types";
import type { LeituraViva } from "../trend/bordaViva";
import { LIMITE_PENAS } from "../trend/trendTheme";
import type { LoopHistoryResponse, LoopNodeOut, LoopState } from "./types";

export const MODOS_LOOP = ["oos", "iman", "lo", "man", "auto", "cas", "rcas", "rout"] as const;
export type ModoLoop = (typeof MODOS_LOOP)[number];

/** Modos que o operador pode COMANDAR (os demais existem no FF mas são atingidos por
 *  rebaixamento/cascata — a API também só aceita estes). */
export const MODOS_COMANDAVEIS: readonly ModoLoop[] = ["oos", "man", "auto", "cas", "rcas", "rout"];

/** Modo comandável está em `permitted`? Pura para check. */
export function podeComandar(estado: LoopState, modo: ModoLoop): boolean {
  return MODOS_COMANDAVEIS.includes(modo) && estado.permitted.includes(modo);
}

/** A malha que casa com `?flow=&bloco=`; sem casar (link velho, bloco apagado), a primeira. */
export function resolverSelecao(
  loops: readonly LoopNodeOut[],
  flow: string | null,
  bloco: string | null,
): LoopNodeOut | null {
  const casada = loops.find((l) => String(l.flow_id) === flow && l.block_id === bloco);
  return casada ?? loops[0] ?? null;
}

export interface CondicaoMalha {
  readonly canal: EstadoConexaoCanal;
  /** `status.state` publicado no canal do flow — não o `desired_state` REST, que pode estar velho. */
  readonly estadoFlow: string | undefined;
  readonly estado: LoopState | undefined;
  /** `ts` do `LoopState` retido quando a página montou ou o canal reabriu (`undefined` se não havia). */
  readonly tsBase: string | undefined;
}

/** "Ao vivo" exige os quatro termos (spec §6): canal aberto, flow rodando, estado presente e
 *  quadro diferente do retido na montagem/reconexão — o retido é de antes e não prova nada. */
export function malhaAoVivo(c: CondicaoMalha): boolean {
  return (
    c.canal === "aberto" &&
    c.estadoFlow === "running" &&
    c.estado !== undefined &&
    c.estado.ts !== c.tsBase
  );
}

/** Texto do aviso quando não está ao vivo. `desejado` (`desired_state` REST) só escolhe o
 *  texto: pode estar velho, por isso não entra no predicado. */
export function motivoSemEstado(
  canal: EstadoConexaoCanal,
  estadoFlow: string | undefined,
  desejado: "running" | "stopped" | undefined,
): string {
  if (canal === "sessao_invalida") {
    return "Sessão inválida ou expirada: entre novamente para ver a malha ao vivo.";
  }
  if (canal === "conectando") return ROTULO_CONEXAO.conectando;
  if (canal === "reconectando") return ROTULO_CONEXAO.reconectando;
  if (estadoFlow === "failed") return "Flow em falha — sem estado ao vivo";
  if (desejado === "stopped" || estadoFlow === "stopped") return "Flow parado — sem estado ao vivo";
  return "Aguardando estado ao vivo da malha…";
}

/** Posição na faixa do bloco, 0…100. Faixa degenerada ou valor ausente/NaN ⇒ 0, nunca NaN. */
export function percentualBarra(valor: number | null, minimo: number, maximo: number): number {
  if (valor === null || !(maximo > minimo)) return 0;
  const pct = ((valor - minimo) / (maximo - minimo)) * 100;
  return Number.isNaN(pct) ? 0 : Math.min(100, Math.max(0, pct));
}

export interface VarMalha {
  readonly id: string;
  readonly rotulo: string;
}

const VARIAVEIS = ["pv", "sp", "out"] as const;

/** Ids da API: canal 0 sem sufixo, canal `i` com `:i`. Rótulo sem canal só quando há um. */
export function varsMalha(nLoops: number): VarMalha[] {
  return Array.from({ length: nLoops }, (_, i) =>
    VARIAVEIS.map((v) => ({
      id: i === 0 ? v : `${v}:${i}`,
      rotulo: nLoops === 1 ? v.toUpperCase() : `${v.toUpperCase()} · canal ${i + 1}`,
    })),
  ).flat();
}

/** Só PV/SP/OUT do canal 0 nascem marcadas: o teto de penas (`LIMITE_PENAS`) é menor que
 *  as variáveis de uma malha multicanal. */
export function penasIniciais(vars: readonly VarMalha[]): string[] {
  return vars
    .filter((v) => !v.id.includes(":"))
    .map((v) => v.id)
    .slice(0, LIMITE_PENAS);
}

/** Uma leitura por pena, indexada pelo `channel` do próprio quadro (não pela posição no array).
 *  PV nula fica de fora; PV sem qualidade (`pv_ok` falso) entra — só o valor ausente não se plota. */
export function leiturasVivasMalha(
  estados: readonly (LoopState | undefined)[],
): ReadonlyMap<string, LeituraViva> {
  const vivas = new Map<string, LeituraViva>();
  for (const e of estados) {
    if (e === undefined) continue;
    const sufixo = e.channel === 0 ? "" : `:${e.channel}`;
    for (const v of VARIAVEIS) {
      const valor = e[v];
      if (valor !== null) vivas.set(`${v}${sufixo}`, { ts: e.ts, v: valor });
    }
  }
  return vivas;
}

/** Forma `FuzzyHistoryResponse` (sem `v_min`/`v_max`, que o gráfico não usa) para reaproveitar a
 *  matriz e a mescla viva de `../fuzzy/historicoFuzzy`. Mantém TODA amostra, nulas incluídas. */
export function historicoComLacunas(resposta: LoopHistoryResponse): FuzzyHistoryResponse {
  return {
    mode: resposta.mode,
    start: resposta.start,
    end: resposta.end,
    series: resposta.series.map((s) => ({
      var_id: s.var_id,
      t: s.t,
      // null preservado de propósito: `alinharNoEixo` o trata como lacuna conhecida.
      v: s.v as number[],
    })),
  };
}
