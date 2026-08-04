import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type uPlot from "uplot";

import { api, type HistoryResponse, type TagOut } from "../../lib/api";

/** OPC-UA: 0 good, 1 uncertain, 2 bad (spec F2 §4.2). */
const QUALIDADE_BAD = 2;

const INTERVALO_POLLING_MS = 5000;

/** Tags ordenadas por conexão e nome (brief 6.4: não filtrar direção). `GET /api/tags` não aceita
 *  `project_id`: o escopo por projeto ativo é aplicado na página. */
export function useTags(): UseQueryResult<TagOut[]> {
  return useQuery({
    queryKey: ["tags"],
    queryFn: () => api<TagOut[]>("/api/tags"),
    select: (tags) =>
      [...tags].sort(
        (a, b) => a.connection_id - b.connection_id || a.name.localeCompare(b.name, "pt-BR"),
      ),
  });
}

/**
 * Histórico das tags selecionadas na janela pedida. A janela é recalculada a cada busca
 * (`end = agora`), por isso start/end ficam fora da queryKey: senão cada poll criaria uma
 * entrada nova de cache e o gráfico piscaria.
 */
export function useHistory(
  tagIds: readonly number[],
  janelaSegundos: number,
): UseQueryResult<HistoryResponse> {
  const ids = tagIds.join(",");
  return useQuery({
    queryKey: ["history", ids, janelaSegundos],
    queryFn: () => {
      const fim = new Date();
      const inicio = new Date(fim.getTime() - janelaSegundos * 1000);
      const busca = new URLSearchParams({
        tag_ids: ids,
        start: inicio.toISOString(),
        end: fim.toISOString(),
      });
      return api<HistoryResponse>(`/api/history?${busca.toString()}`);
    },
    enabled: tagIds.length > 0,
    refetchInterval: INTERVALO_POLLING_MS,
  });
}

/**
 * Matriz colunar do uPlot: um eixo x compartilhado por todas as penas.
 *
 * Cada tag tem carimbos próprios (amostragem por exceção), então o eixo x é a união dos
 * carimbos e cada pena repete seu último valor conhecido nos instantes em que não amostrou
 * — que é o que o valor fez de fato no processo. Ponto `q === 2` zera esse último valor
 * conhecido para `null`, produzindo o gap exigido pela Regra do Canal Redundante.
 */
export function montarMatriz(
  resposta: HistoryResponse,
  ordem: readonly number[],
): uPlot.AlignedData {
  const porTag = new Map(resposta.series.map((serie) => [serie.tag_id, serie]));
  const tempos = ordem.map((tagId) =>
    (porTag.get(tagId)?.t ?? []).map((iso) => Date.parse(iso) / 1000),
  );
  const valores = ordem.map((tagId) => {
    const serie = porTag.get(tagId);
    if (!serie) return [];
    return serie.v.map((valor, i) => (serie.q[i] === QUALIDADE_BAD ? null : valor));
  });

  const cursores = ordem.map(() => 0);
  const atual: (number | null)[] = ordem.map(() => null);
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
        cursores[i]++;
      }
      penas[i].push(atual[i]);
    }
    x.push(instante);
  }

  return [x, ...penas];
}

export interface ResumoSerie {
  readonly tagId: number;
  /** Último valor com qualidade aceitável; `null` quando a série não tem nenhum. */
  readonly valor: number | null;
  /** Último ponto da série é bad — a legenda precisa dizer isso em texto. */
  readonly bad: boolean;
}

export function resumirSeries(
  resposta: HistoryResponse,
  ordem: readonly number[],
): ResumoSerie[] {
  const porTag = new Map(resposta.series.map((serie) => [serie.tag_id, serie]));
  return ordem.map((tagId) => {
    const serie = porTag.get(tagId);
    const ultimo = (serie?.q.length ?? 0) - 1;
    if (!serie || ultimo < 0) return { tagId, valor: null, bad: false };
    let i = ultimo;
    while (i >= 0 && serie.q[i] === QUALIDADE_BAD) i--;
    return { tagId, valor: i >= 0 ? serie.v[i] : null, bad: serie.q[ultimo] === QUALIDADE_BAD };
  });
}
