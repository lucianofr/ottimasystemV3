import type uPlot from "uplot";

import { tetoCarryForwardSegundos } from "../trend/useHistory";
import type { FuzzyHistoryResponse } from "./types";

/**
 * Montagem de dados do trend fuzzy (`TrendFuzzy.tsx`, ADR-030) — mesmo algoritmo de
 * `montarMatriz`/`resumirSeries` (`../trend/useHistory.ts`), sem o filtro de qualidade `q`
 * (que `fuzzy_samples` não tem, mesmo motivo de `MpcHistorySeries`/`trendOperacao.ts`): o
 * "silêncio" de uma pena usa o mesmo teto de carry-forward por `mode` (política RAW/1m
 * compartilhada — `tetoCarryForwardSegundos`). Funções puras, sem I/O.
 */

/** Matriz colunar do uPlot: um eixo x compartilhado por todas as penas selecionadas, na
 *  ordem de `ordem` (portas `IN1..INn`/`OUT1..OUTn`). */
export function montarMatrizFuzzy(
  resposta: FuzzyHistoryResponse,
  ordem: readonly string[],
): uPlot.AlignedData {
  const porVar = new Map(resposta.series.map((serie) => [serie.var_id, serie]));
  const tempos = ordem.map((varId) =>
    (porVar.get(varId)?.t ?? []).map((iso) => Date.parse(iso) / 1000),
  );
  const valores = ordem.map((varId) => porVar.get(varId)?.v ?? []);

  const teto = tetoCarryForwardSegundos(resposta.mode);
  const cursores = ordem.map(() => 0);
  const atual: (number | null)[] = ordem.map(() => null);
  const ultimaAmostra = ordem.map(() => Number.NEGATIVE_INFINITY);
  const x: number[] = [];
  const penas: (number | null)[][] = ordem.map(() => []);

  for (;;) {
    let instante = Number.POSITIVE_INFINITY;
    for (let i = 0; i < ordem.length; i++) {
      const proximo = tempos[i][cursores[i]];
      if (proximo !== undefined && proximo < instante) instante = proximo;
    }
    if (instante === Number.POSITIVE_INFINITY) break;

    for (let i = 0; i < ordem.length; i++) {
      while (cursores[i] < tempos[i].length && tempos[i][cursores[i]] === instante) {
        atual[i] = valores[i][cursores[i]];
        ultimaAmostra[i] = instante;
        cursores[i]++;
      }
      penas[i].push(instante - ultimaAmostra[i] > teto ? null : atual[i]);
    }
    x.push(instante);
  }

  return [x, ...penas];
}

export interface ResumoSerieFuzzy {
  readonly varId: string;
  /** Último valor utilizável; `null` quando não há nenhum ou quando a pena está sem dado. */
  readonly valor: number | null;
  /** Nenhuma amostra dentro do teto de carry-forward: a variável parou de reportar. */
  readonly semDado: boolean;
}

export function resumirSeriesFuzzy(
  resposta: FuzzyHistoryResponse,
  ordem: readonly string[],
): ResumoSerieFuzzy[] {
  const porVar = new Map(resposta.series.map((serie) => [serie.var_id, serie]));
  const teto = tetoCarryForwardSegundos(resposta.mode);
  // Referência de "agora": o carimbo mais recente da resposta, de qualquer pena — mesmo
  // motivo de `resumirSeries` (`../trend/useHistory.ts`): `resposta.end` vem do relógio do
  // navegador, e o modo `1m` só enxerga buckets já materializados pela policy do TimescaleDB.
  let referencia = Number.NEGATIVE_INFINITY;
  for (const serie of resposta.series) {
    const ultimo = serie.t[serie.t.length - 1];
    if (ultimo !== undefined) referencia = Math.max(referencia, Date.parse(ultimo) / 1000);
  }
  return ordem.map((varId) => {
    const serie = porVar.get(varId);
    const ultimo = (serie?.v.length ?? 0) - 1;
    if (!serie || ultimo < 0 || referencia - Date.parse(serie.t[ultimo]) / 1000 > teto) {
      return { varId, valor: null, semDado: true };
    }
    return { varId, valor: serie.v[ultimo], semDado: false };
  });
}
