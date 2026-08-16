import type uPlot from "uplot";

import { alinharNoEixo, montarEixoUniao } from "../trend/alinhamento";
import { colunasVivas, type PontoVivo } from "../trend/bordaViva";
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
 *  ordem de `ordem` (portas `IN1..INn`/`OUT1..OUTn`) — eixo união (`montarEixoUniao`) mais
 *  carry-forward-com-teto delegado ao primitivo único (`alinharNoEixo`,
 *  `../trend/alinhamento.ts`, ARCH-02). */
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
  const x = montarEixoUniao(tempos);
  const penas = tempos.map((t, i) => alinharNoEixo(x, t, valores[i], teto));

  return [x, ...penas];
}

export interface ResumoSerieFuzzy {
  readonly varId: string;
  /** Último valor utilizável; `null` quando não há nenhum ou quando a pena está sem dado. */
  readonly valor: number | null;
  /** Nenhuma amostra dentro do teto de carry-forward: a variável parou de reportar. */
  readonly semDado: boolean;
}

/** `referenciaAgoraS`: mesmo contrato de `resumirSeries` (`../trend/useHistory.ts`) — quem
 *  mescla a borda viva passa a referência do histórico PERSISTIDO, para uma porta que já
 *  recebeu quadro vivo não marcar a vizinha ainda sem quadro como SEM DADO. */
export function resumirSeriesFuzzy(
  resposta: FuzzyHistoryResponse,
  ordem: readonly string[],
  referenciaAgoraS?: number,
): ResumoSerieFuzzy[] {
  const porVar = new Map(resposta.series.map((serie) => [serie.var_id, serie]));
  const teto = tetoCarryForwardSegundos(resposta.mode);
  // Referência de "agora": o carimbo mais recente da resposta, de qualquer pena — mesmo
  // motivo de `resumirSeries` (`../trend/useHistory.ts`): `resposta.end` vem do relógio do
  // navegador, e o modo `1m` só enxerga buckets já materializados pela policy do TimescaleDB.
  let referencia = referenciaAgoraS ?? Number.NEGATIVE_INFINITY;
  if (referenciaAgoraS === undefined) {
    for (const serie of resposta.series) {
      const ultimo = serie.t[serie.t.length - 1];
      if (ultimo !== undefined) referencia = Math.max(referencia, Date.parse(ultimo) / 1000);
    }
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

/**
 * Histórico do trend fuzzy com a ponta viva de `fuzzy.state` acrescentada — espelho de
 * `mesclarHistoricoVivo` (`../trend/bordaViva.ts`) sem a coluna `q`, que `fuzzy_samples` não
 * tem. A porta cujo quadro vivo não trouxe valor fica de fora e cai no teto de carry-forward,
 * como qualquer pena que parou de reportar.
 */
export function mesclarHistoricoFuzzyVivo(
  resposta: FuzzyHistoryResponse,
  vivos: ReadonlyMap<string, readonly PontoVivo[]>,
): FuzzyHistoryResponse {
  if (vivos.size === 0) return resposta;

  let mudou = false;
  const series = resposta.series.map((serie) => {
    const extra = colunasVivas(serie.t, vivos.get(serie.var_id) ?? []);
    if (extra === null) return serie;
    mudou = true;
    return { ...serie, t: [...serie.t, ...extra.t], v: [...serie.v, ...extra.v] };
  });

  // Porta sem amostra persistida na janela não vem como série na resposta: existe só na borda
  // viva (bloco fuzzy que acabou de entrar em execução).
  const persistidas = new Set(resposta.series.map((serie) => serie.var_id));
  for (const [varId, pontos] of vivos) {
    if (persistidas.has(varId) || pontos.length === 0) continue;
    series.push({
      var_id: varId,
      t: pontos.map((ponto) => new Date(ponto.t * 1000).toISOString()),
      v: pontos.map((ponto) => ponto.v),
    });
    mudou = true;
  }

  return mudou ? { ...resposta, series } : resposta;
}
