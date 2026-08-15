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

/** Ponto da ponta viva na taxa OPC (canal `opc.values`, decisão F6 A-1 revertida): só `v`
 *  — SP/modo seguem vindo do `mpc.state` (o merge abaixo carrega o último conhecido). */
export interface PontoOpc {
  readonly t: number;
  readonly v: number;
}

/**
 * Une o histórico do poll (`GET /api/history/mpc`) com a borda viva (`mpc.state` via WS):
 * cada amostra vira um ponto por `ts`, deduplicado — quando o poll re-sincroniza e já traz um
 * instante que a borda viva também tinha capturado ao vivo, o ponto não duplica (o histórico
 * e a borda viva descrevem o mesmo `ts`, então o `Map` por `ts` funde os dois sem distinção;
 * não importa qual "vence", os dois têm que concordar por construção — mesmo `mpc.state` que
 * o recorder persistiu). Pura: não muta `historico` nem `vivas`.
 *
 * `pontosOpc` (opcional): adensamento da ponta viva na taxa OPC por variável. Ponto em `ts`
 * já coberto pelo histórico/borda viva é ignorado (o `mpc.state` manda); o `sp`/`auto` de um
 * ponto OPC herdam o último valor conhecido da série — SP e modo só mudam na cadência do
 * MPC, e um buraco `null` quebraria a linha de SP a cada ponto adensado.
 */
export function mesclarSeriesVivas(
  historico: MpcHistoryResponse,
  vivas: readonly AmostraViva[],
  ordem: readonly string[],
  pontosOpc?: ReadonlyMap<string, readonly PontoOpc[]>,
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
    const tsOpc = new Set<number>();
    for (const ponto of pontosOpc?.get(id) ?? []) {
      if (pontos.has(ponto.t)) continue;
      // sp/auto provisórios: o passe cronológico abaixo troca pelo último conhecido.
      pontos.set(ponto.t, { v: ponto.v, sp: null, auto: false });
      tsOpc.add(ponto.t);
    }

    const t = [...pontos.keys()].sort((a, b) => a - b);
    const v: number[] = [];
    const sp: (number | null)[] = [];
    const auto: boolean[] = [];
    let spVigente: number | null = null;
    let autoVigente = false;
    for (const ts of t) {
      const ponto = pontos.get(ts)!;
      if (tsOpc.has(ts)) {
        sp.push(spVigente);
        auto.push(autoVigente);
      } else {
        spVigente = ponto.sp ?? spVigente;
        autoVigente = ponto.auto;
        sp.push(ponto.sp);
        auto.push(ponto.auto);
      }
      v.push(ponto.v);
    }
    return { id, t, v, sp, auto };
  });
}

/** Cadências perdidas até a pena virar gap — mesma regra do trend de engenharia
 *  (`useHistory.ts`, `CADENCIAS_ATE_SEM_DADO`): uma só viraria falso positivo em qualquer
 *  jitter de gravação ou de fronteira de bucket. */
const CADENCIAS_ATE_SEM_DADO = 2;

/** Cadência do modo agregado: um ponto por bucket de 1 min, por construção de `mpc_samples_1m`
 *  (`routers/history.py`). No modo bruto a cadência é o próprio Ts_mpc do bloco. */
const CADENCIA_1M_S = 60;

/**
 * Teto do carry-forward do eixo compartilhado (ver `alinharNoEixo`). Repetir o último valor
 * conhecido além dele desenharia reta contínua numa variável que parou de amostrar — a mentira
 * que a Regra do Canal Redundante (DESIGN.md) proíbe.
 */
export function tetoCarryForwardOperacaoS(
  modo: MpcHistoryResponse["mode"],
  tsMpcS: number,
): number {
  return CADENCIAS_ATE_SEM_DADO * (modo === "1m" ? CADENCIA_1M_S : tsMpcS);
}

/**
 * Fronteira entre o passado e a seção futura: o carimbo mais novo que alguma pena de fato
 * amostrou. O eixo x do gráfico é a união dos carimbos das penas COM os da predição
 * (`montarColunas` em `TrendOperacao.tsx`), então o carry-forward de `alinharNoEixo` tem um
 * limite a respeitar aqui: repetir a última medição num carimbo do horizonte desenharia
 * medição onde não houve medição — a pena sólida atravessa a linha do "agora" e termina à
 * direita de onde a tracejada começa (a emenda "tinta que ainda não secou" quebra nas duas
 * pontas). O limite é o carimbo mais novo de TODAS as penas, não o de cada uma: é isso que
 * mantém a pena esparsa alcançando a ponta densa de quem tem tag OPC (`alinharNoEixo`).
 */
export function ultimoCarimboHistorico(series: readonly SerieOperacao[]): number {
  let ultimo = Number.NEGATIVE_INFINITY;
  for (const serie of series) {
    // `t` é crescente por construção (ver `SerieOperacao`): o último elemento é o mais novo.
    const carimbo = serie.t[serie.t.length - 1];
    if (carimbo !== undefined && carimbo > ultimo) ultimo = carimbo;
  }
  return ultimo;
}

/**
 * Coluna de uma pena no eixo x compartilhado do uPlot (união dos carimbos de todas as penas,
 * `montarColunas` em `TrendOperacao.tsx`).
 *
 * Cada variável tem carimbos próprios — quem tem tag OPC adensa a ponta viva na taxa do worker
 * (`PontoOpc`), quem não tem (CV vinda de script, MV sem readback) só existe na cadência do
 * MPC — e a predição só vive no horizonte. Nos instantes em que a pena não amostrou ela repete
 * o último valor conhecido, que é o que o valor fez de fato no processo: sem isso a pena mais
 * esparsa fica com um `null` entre cada par de carimbos alheios, vira trecho de 1 ponto e não
 * desenha nada (`spanGaps: false`, sem marcador). Três coisas cortam a repetição e as três
 * viram gap: `null` na própria série (SP dividido por `auto`, ponto sem valor), silêncio além
 * de `tetoS` (`tetoCarryForwardOperacaoS`) — flow parado, recorder fora do ar — e carimbo além
 * de `limiteS`, a fronteira do passado (`ultimoCarimboHistorico`): pena medida não entra na
 * seção futura. `tetoS = 0` desliga a repetição por inteiro, que é como a própria predição
 * entra (só nos seus carimbos, o traço entre eles é do `spanGaps` do uPlot).
 *
 * Mesma regra do trend de engenharia (`montarMatriz` em `useHistory.ts`), aqui por coluna
 * porque o eixo já vem montado (histórico + horizonte da predição). `eixoX` crescente é
 * pré-condição (uPlot já exige x monotônico): num salto para trás a diferença fica negativa e
 * o teto nunca dispararia.
 */
export function alinharNoEixo(
  eixoX: readonly number[],
  t: readonly number[],
  valores: readonly (number | null | undefined)[],
  tetoS: number,
  limiteS = Number.POSITIVE_INFINITY,
): (number | null)[] {
  const porT = new Map(t.map((ts, i) => [ts, valores[i] ?? null]));
  let atual: number | null = null;
  let ultimaAmostra = Number.NEGATIVE_INFINITY;
  return eixoX.map((ts) => {
    const amostra = porT.get(ts);
    if (amostra !== undefined) {
      atual = amostra;
      ultimaAmostra = ts;
    }
    if (ts > limiteS) return null;
    return ts - ultimaAmostra > tetoS ? null : atual;
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

/**
 * Recorte de apresentação do plano na emenda com o traço sólido (DESIGN §Overview, assinatura
 * "tinta que ainda não secou": o histórico é traço sólido, a linha-cursor marca "agora" e a
 * predição CONTINUA dali — tinta molhada na ponta, não traço voltando por cima do que já secou).
 *
 * O plano publicado num quadro foi despachado pelo menos uma fronteira antes (`prediction.ts =
 * _dispatch_ts` em `blocks/mpc.py`, spec §3.5/F5R-01) e `t[0] = 0`, então `tAbs[0]` cai ATRÁS da
 * ponta viva: desenhado inteiro, o tracejado começa antes do fim do sólido e volta por cima do
 * histórico. Aqui nada se move no tempo — a âncora continua sendo `prediction.ts` e cada ponto
 * mantém seu instante absoluto (re-ancorar adiantaria o horizonte em 1×Ts_mpc, o que F5R-01
 * proíbe): só o trecho JÁ DECORRIDO sai de cena, e entra um ponto no próprio divisor para o
 * tracejado começar exatamente onde o sólido termina — sem sobreposição e sem buraco.
 *
 * `degrau` (MVs, §3.3 `align: -1`): o valor no divisor é o do PRÓXIMO ponto, que é o degrau
 * vigente no intervalo que termina nele — interpolar reta ali moveria a quina do degrau. CVs e
 * Restrições são trajetória contínua: reta entre os dois pontos que cercam o divisor.
 */
export function emendarPlanoNoDivisor(
  tAbs: readonly number[],
  valores: readonly number[],
  divisorS: number,
  degrau: boolean,
): { readonly t: readonly number[]; readonly v: readonly number[] } {
  // Linha ausente no quadro (`overlay.cv[i] ?? []`) ou fora de passo com o vetor de tempo: sem
  // par (t, v) não há plano para desenhar — nunca meia pena.
  if (valores.length !== tAbs.length) return { t: [], v: [] };
  const primeiroFuturo = tAbs.findIndex((ts) => ts > divisorS);
  if (primeiroFuturo === 0) return { t: tAbs, v: valores };
  // `-1`: todo o plano já decorreu (quadro velho, relógio adiantado) — nada a desenhar.
  if (primeiroFuturo < 0) return { t: [], v: [] };
  const anterior = tAbs[primeiroFuturo - 1];
  const passo = tAbs[primeiroFuturo] - anterior;
  const fracao = passo > 0 ? (divisorS - anterior) / passo : 1;
  const vAnterior = valores[primeiroFuturo - 1];
  const vProximo = valores[primeiroFuturo];
  return {
    t: [divisorS, ...tAbs.slice(primeiroFuturo)],
    v: [
      degrau ? vProximo : vAnterior + (vProximo - vAnterior) * fracao,
      ...valores.slice(primeiroFuturo),
    ],
  };
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

/** Cor de cada variável por posição — ordem MV→CV→Restrição→DV fixa de `mpc.variables`
 *  (mesma ordem de `FaceplateVariavel`/`gradeDeVariaveis`), independente de qual pena está
 *  ligada: ligar/desligar pela legenda nunca reatribui a cor de uma variável já visível.
 *  Extraída de `TrendOperacao.tsx` (era `atribuirCoresPenas(mpc, tema)`, acoplada a
 *  `MpcNodeOut`/`TemaTrend`) — é lógica pura (regra global 3), então mora aqui: quem chama
 *  já traz a lista de ids pronta e a paleta JÁ RESOLVIDA (valores reais, não nomes de token
 *  — este módulo não lê DOM, regra global 2; `TrendOperacao.tsx` resolve `TOKENS_PENA_OPERACAO`
 *  via `getComputedStyle` e passa o resultado aqui). Sem wrap até o teto: `cores.length` é o
 *  tamanho da paleta (8 para operação) — só ids além do teto reciclam por módulo, mesmo
 *  comportamento de antes (variáveis que nunca cabem na legenda ainda ganham uma cor "de
 *  casa" para quando ligadas, mesmo que nunca apareçam ao mesmo tempo que as 8 primeiras). */
export function atribuirCoresPenas(
  ids: readonly string[],
  cores: readonly string[],
): ReadonlyMap<string, string> {
  return new Map(ids.map((id, i) => [id, cores[i % cores.length]]));
}
