import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type uPlot from "uplot";

import { api, type HistoryResponse, type TagOut } from "../../lib/api";

/** OPC-UA: 0 good, 1 uncertain, 2 bad (spec F2 §4.2). */
const QUALIDADE_BAD = 2;

const INTERVALO_POLLING_MS = 5000;

/**
 * Cadência do modo bruto: toda tag viva republica pelo menos a cada 10 s mesmo sem mudança de
 * valor (spec F2 §2.2-6; `HEARTBEAT_INTERVAL_S` em
 * `services/opc-worker/src/ottima_opc_worker/heartbeat.py`). O recorder grava em lote de 1 s
 * (`FLUSH_INTERVAL_S` em `services/recorder/src/ottima_recorder/pipeline.py`), então o
 * histórico enxerga essa cadência praticamente sem atraso.
 */
const CADENCIA_RAW_S = 10;

/** Cadência do modo agregado: um ponto por bucket de 1 minuto, por construção do `samples_1m`
 *  (RF-801/802, `time_bucket('1 minute', ts)`). */
const CADENCIA_1M_S = 60;

/** Duas cadências perdidas = a tag parou de reportar. Uma só viraria falso positivo em
 *  qualquer jitter de rede, de gravação ou de fronteira de bucket. */
const CADENCIAS_ATE_SEM_DADO = 2;

/**
 * Teto do carry-forward. Repetir o último valor conhecido além dele desenharia reta contínua
 * numa tag que parou de reportar — a mentira que a Regra do Canal Redundante (DESIGN.md) e o
 * watchdog de 12 s (spec F2 §3) existem para impedir. Escala com o modo: no `1m` o bucket já
 * é de 60 s e um teto de bruto gaparia toda série agregada saudável.
 */
export function tetoCarryForwardSegundos(modo: HistoryResponse["mode"]): number {
  return CADENCIAS_ATE_SEM_DADO * (modo === "1m" ? CADENCIA_1M_S : CADENCIA_RAW_S);
}

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
 * — que é o que o valor fez de fato no processo. Duas coisas cortam essa repetição, e as duas
 * viram gap: ponto com `q === 2` (a origem disse que o valor não presta) e silêncio além de
 * `tetoCarryForwardSegundos` (não chegou amostra nenhuma — recorder fora do ar, worker morto,
 * canal Redis perdido). Sem o teto, a pena morta desenharia reta com o último valor bom
 * enquanto outra pena viva continua puxando o eixo x adiante, que é exatamente a mentira que
 * a Regra do Canal Redundante (DESIGN.md) proíbe.
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

  const teto = tetoCarryForwardSegundos(resposta.mode);
  const cursores = ordem.map(() => 0);
  const atual: (number | null)[] = ordem.map(() => null);
  // Instante da última amostra real de cada pena; antes da primeira, silêncio infinito.
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

export interface ResumoSerie {
  readonly tagId: number;
  /** Último valor utilizável; `null` quando não há nenhum ou quando a pena está sem dado. */
  readonly valor: number | null;
  /** Último ponto da série é bad — a legenda precisa dizer isso em texto. */
  readonly bad: boolean;
  /** Nenhuma amostra dentro do teto de carry-forward: a aquisição dessa tag parou. */
  readonly semDado: boolean;
}

export function resumirSeries(
  resposta: HistoryResponse,
  ordem: readonly number[],
): ResumoSerie[] {
  const porTag = new Map(resposta.series.map((serie) => [serie.tag_id, serie]));
  const teto = tetoCarryForwardSegundos(resposta.mode);
  // Referência de "agora": o carimbo mais recente que a resposta trouxe, de qualquer pena — a
  // mesma que o eixo x do gráfico usa, então legenda e gráfico nunca se contradizem.
  // Não é `resposta.end` de propósito: `end` vem do relógio do navegador, e o modo `1m` só
  // enxerga buckets já materializados pela policy do TimescaleDB (`end_offset` 1 min,
  // `schedule_interval` 1 min, medido ~196 s de atraso), o que marcaria toda série agregada
  // saudável como sem dado.
  let referencia = Number.NEGATIVE_INFINITY;
  for (const serie of resposta.series) {
    const ultimo = serie.t[serie.t.length - 1];
    if (ultimo !== undefined) referencia = Math.max(referencia, Date.parse(ultimo) / 1000);
  }
  return ordem.map((tagId) => {
    const serie = porTag.get(tagId);
    const ultimo = (serie?.q.length ?? 0) - 1;
    // Sem amostra dentro do teto não existe valor atual: mostrar o último bom seria mentira.
    if (!serie || ultimo < 0 || referencia - Date.parse(serie.t[ultimo]) / 1000 > teto) {
      return { tagId, valor: null, bad: false, semDado: true };
    }
    let i = ultimo;
    while (i >= 0 && serie.q[i] === QUALIDADE_BAD) i--;
    return {
      tagId,
      valor: i >= 0 ? serie.v[i] : null,
      bad: serie.q[ultimo] === QUALIDADE_BAD,
      semDado: false,
    };
  });
}
