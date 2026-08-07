import type { MpcHistoryResponse } from "../../lib/api";
import type { MpcVarState } from "../../lib/contracts.gen";

/**
 * Trend central com predição (spec F5 §7.4-6; plano F5b Etapa 5). Lógica pura: montagem de
 * séries, âncora da predição e seleção default de penas — sem DOM, sem uPlot. `TrendOperacao.tsx`
 * consome este módulo para desenhar; `trendOperacao.check.ts` cobre só dados (regra global 3:
 * nunca pixel).
 */

// ----------------------------------------------------------------------------------------
// 5.1 — Dados: janelas, polling e borda viva (spec F5 §7.4-6 item 1-2)
// ----------------------------------------------------------------------------------------

export interface JanelaOperacao {
  readonly id: "15m" | "30m" | "2h" | "8h";
  readonly rotulo: string;
  readonly segundos: number;
}

/** Janelas do trend de operação (brief 5.1) — teto próprio, distinto das janelas do trend de
 *  engenharia (`features/trend/TrendPage.tsx`), que serve outro caso de uso (tags OPC). */
export const JANELAS_OPERACAO: readonly JanelaOperacao[] = [
  { id: "15m", rotulo: "15 min", segundos: 900 },
  { id: "30m", rotulo: "30 min", segundos: 1800 },
  { id: "2h", rotulo: "2 h", segundos: 7200 },
  { id: "8h", rotulo: "8 h", segundos: 28800 },
];

export const JANELA_PADRAO_ID: JanelaOperacao["id"] = "30m";

/** Polling do histórico (brief 5.1) — mesma cadência do trend de engenharia (`useHistory.ts`). */
export const INTERVALO_POLLING_OPERACAO_MS = 5000;

/** Um `mpc.state` (borda viva): `ts` + `vars` do quadro, mais `auto` derivado dos `modes` no
 *  mesmo instante (§2.2-1: `local_remote === "remote" && man_auto === "auto"`) — o quadro não
 *  guarda `auto` pronto, quem lê o WS deriva antes de empilhar aqui. */
export interface AmostraViva {
  readonly ts: string;
  readonly vars: Readonly<Record<string, MpcVarState>>;
  readonly auto: boolean;
}

/** Série montada de uma variável, pronta para virar coluna do uPlot: `t` em segundos epoch,
 *  crescente, sem buraco de qualidade (`mpc_samples` não tem conceito de qualidade — só OPC
 *  tem, spec F5 §2.4-2). */
export interface SerieOperacao {
  readonly id: string;
  readonly t: readonly number[];
  readonly v: readonly number[];
  readonly sp: readonly (number | null)[];
  readonly auto: readonly boolean[];
}

/**
 * Une o histórico do poll (`GET /api/history/mpc`) com a borda viva (`mpc.state` via WS):
 * cada amostra vira um ponto por `ts`, deduplicado — quando o poll re-sincroniza e já traz um
 * instante que a borda viva também tinha capturado ao vivo, o ponto não duplica (o histórico
 * e a borda viva descrevem o mesmo `ts`, então o `Map` por `ts` funde os dois sem distinção;
 * não importa qual "vence", os dois têm que concordar por construção — mesmo `mpc.state` que
 * o recorder persistiu). Pura: não muta `historico` nem `vivas`.
 */
export function mesclarSeriesVivas(
  historico: MpcHistoryResponse,
  vivas: readonly AmostraViva[],
  ordem: readonly string[],
): SerieOperacao[] {
  const porVar = new Map(historico.series.map((serie) => [serie.var_id, serie]));

  return ordem.map((id) => {
    const pontos = new Map<number, { v: number; sp: number | null; auto: boolean }>();
    const serie = porVar.get(id);
    if (serie) {
      serie.t.forEach((iso, i) => {
        pontos.set(Date.parse(iso) / 1000, { v: serie.v[i], sp: serie.sp[i], auto: serie.auto[i] });
      });
    }
    for (const amostra of vivas) {
      const valor = amostra.vars[id];
      if (!valor) continue;
      const tsSegundos = Date.parse(amostra.ts) / 1000;
      if (!pontos.has(tsSegundos)) {
        pontos.set(tsSegundos, { v: valor.v, sp: valor.sp, auto: amostra.auto });
      }
    }

    const t = [...pontos.keys()].sort((a, b) => a - b);
    return {
      id,
      t,
      v: t.map((ts) => pontos.get(ts)!.v),
      sp: t.map((ts) => pontos.get(ts)!.sp),
      auto: t.map((ts) => pontos.get(ts)!.auto),
    };
  });
}
