import type { MpcHistoryResponse } from "../../lib/api";
import type { MpcPrediction, MpcVarState } from "../../lib/contracts.gen";

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

// ----------------------------------------------------------------------------------------
// 5.2 — Overlay de predição (spec F5 §3, §7.4-6 item 3)
// ----------------------------------------------------------------------------------------

/** Degrau fantasma das penas de MV (§3.3): `stepped align: -1` — o valor de `mv[j]` pertence
 *  ao intervalo que TERMINA no seu ponto (ZOH à esquerda). Única fonte do `align` consumido
 *  por `TrendOperacao.tsx`: `align: +1` deslocaria o plano inteiro em 1×Ts_mpc e é proibido —
 *  como nenhum outro lugar do código escreve o número, ele nunca pode nascer errado. */
export const OPCOES_DEGRAU_MV = { align: -1 as const };

export interface OverlayPrevisao {
  /** `t_abs[k] = prediction.ts + t[k]` (§3.5) — nunca `MpcState.ts` (F5R-01). Vazio fora de
   *  AUTO (`prediction.t == []`, §3.4): o overlay some sem mexer no histórico. */
  readonly tAbs: readonly number[];
  /** Início do overlay ("agora") para a linha-cursor; `null` quando não há predição. */
  readonly agora: number | null;
  /** `cv[i][k]` previsto no instante `tAbs[k]`; linhas = CVs do config, depois Restrições. */
  readonly cv: readonly (readonly number[])[];
  /** `mv[i] = [u_prev, u_0, …, u_{Np-1}]` alinhado a `tAbs` — renderizar com `OPCOES_DEGRAU_MV`. */
  readonly mv: readonly (readonly number[])[];
}

/**
 * Monta o overlay a partir do último `MpcPrediction` publicado. Âncora `prediction.ts`
 * (nunca `MpcState.ts` do quadro — regra global 2): o resultado publicado num quadro foi
 * calculado na fronteira anterior (F5R-01), então usar o `ts` do quadro adiantaria o plano
 * inteiro em 1×Ts_mpc.
 */
export function montarOverlayPrevisao(prediction: MpcPrediction): OverlayPrevisao {
  if (prediction.t.length === 0) return { tAbs: [], agora: null, cv: [], mv: [] };
  const ancoraSegundos = Date.parse(prediction.ts) / 1000;
  const tAbs = prediction.t.map((deslocamentoS) => ancoraSegundos + deslocamentoS);
  return { tAbs, agora: tAbs[0], cv: prediction.cv, mv: prediction.mv };
}

export interface DivisaoSp {
  /** SP nos trechos com `auto=true` — SP comandado, cor cheia (Azul Industrial). */
  readonly comandado: readonly (number | null)[];
  /** SP nos trechos com `auto=false` — SP rastreado (PV-tracking), dessaturado. */
  readonly rastreado: readonly (number | null)[];
}

/**
 * Divide a pena de SP em duas séries paralelas por `auto` (§2.2-1, F5R-21): SP em
 * PV-tracking não é SP comandado, então o trecho `auto=false` não pode sair na mesma cor do
 * trecho comandado. As duas séries alinham ao mesmo eixo x do histórico (nulo onde a outra
 * série tem valor), então a pena aparente é contínua mas troca de estilo exatamente na borda.
 */
export function dividirSpPorAuto(
  sp: readonly (number | null)[],
  auto: readonly boolean[],
): DivisaoSp {
  return {
    comandado: sp.map((valor, i) => (auto[i] ? valor : null)),
    rastreado: sp.map((valor, i) => (auto[i] ? null : valor)),
  };
}

// ----------------------------------------------------------------------------------------
// 5.3 — Defaults e legenda (spec F5 §7.4-6 item 4; decisão A-11; F5R-16)
// ----------------------------------------------------------------------------------------

/** Teto de penas do trend de operação — distinto do teto de 6 tags do trend de engenharia
 *  (`features/trend/trendTheme.ts`, `LIMITE_PENAS`), que serve outro caso de uso. */
export const TETO_PENAS_OPERACAO = 8;

export type CategoriaVarOperacao = "cv" | "constraint" | "mv" | "dv";

/** Custo em penas de cada categoria: CV soma PV+SP (2 traços na mesma legenda); Restrição
 *  soma só o traço de PV — a banda low/high não é uma pena adicional (brief 5.3); MV/DV
 *  custam 1 quando o operador liga pela legenda. */
export const CUSTO_PENAS: Readonly<Record<CategoriaVarOperacao, number>> = {
  cv: 2,
  constraint: 1,
  mv: 1,
  dv: 1,
};

export interface PenaLegenda {
  readonly id: string;
  readonly categoria: CategoriaVarOperacao;
  readonly ligada: boolean;
  /** A seleção default ligaria esta pena, mas o teto cortou — a legenda precisa dizer isso,
   *  não só mostrar "desligada" como se fosse escolha do operador (brief 5.3). */
  readonly excedente: boolean;
}

/**
 * Seleção default de penas (decisão A-11, F5R-16): CVs (PV+SP) ligam na ordem do config até
 * o teto; Restrições ligam como banda (PV conta no teto) com o que sobrar; MVs e DVs nascem
 * desligadas — são opt-in pela legenda, mesmo com o teto livre. Pura: a UI (`TrendOperacao.tsx`)
 * decide o que fazer com um clique depois; esta função só decide o estado inicial.
 */
export function selecionarPenasDefault(
  cvs: readonly { readonly id: string }[],
  constraints: readonly { readonly id: string }[],
  mvs: readonly { readonly id: string }[],
  dvs: readonly { readonly id: string }[],
): PenaLegenda[] {
  let restante = TETO_PENAS_OPERACAO;

  function comTeto(id: string, categoria: "cv" | "constraint"): PenaLegenda {
    const custo = CUSTO_PENAS[categoria];
    const ligada = custo <= restante;
    if (ligada) restante -= custo;
    return { id, categoria, ligada, excedente: !ligada };
  }

  return [
    ...cvs.map((cv) => comTeto(cv.id, "cv")),
    ...constraints.map((c) => comTeto(c.id, "constraint")),
    ...mvs.map((mv) => ({ id: mv.id, categoria: "mv" as const, ligada: false, excedente: false })),
    ...dvs.map((dv) => ({ id: dv.id, categoria: "dv" as const, ligada: false, excedente: false })),
  ];
}

// ----------------------------------------------------------------------------------------
// 5.4 — Paleta de série (débito de frontend da F5, spec §6.6-5)
// ----------------------------------------------------------------------------------------

/** Tokens de cor de pena do trend de operação, um por posição 1..8 — tamanho igual a
 *  `TETO_PENAS_OPERACAO`, então a 8ª pena nunca envolve (wrap) numa cor já usada por outra.
 *  Paleta PRÓPRIA, distinta da paleta de 6 do trend de engenharia (`features/trend/trendTheme.ts`,
 *  `LIMITE_PENAS`) — outro caso de uso, teto distinto (brief 5.3, plano F6b). Só os nomes dos
 *  tokens aqui: os valores OKLCH têm fonte única em `tokens.css` (DESIGN.md §Do's) — este
 *  módulo não lê DOM (regra global 2), quem desenha resolve o valor em runtime. */
export const TOKENS_PENA_OPERACAO: readonly string[] = [
  "--color-pen-1",
  "--color-pen-2",
  "--color-pen-3",
  "--color-pen-4",
  "--color-pen-5",
  "--color-pen-6",
  "--color-pen-7",
  "--color-pen-8",
] as const;
