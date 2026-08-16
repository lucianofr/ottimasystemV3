import type { MpcHistoryResponse } from "../../lib/api";
import type { MpcPrediction, MpcVarState } from "../../lib/contracts.gen";
import { alinharNoEixo } from "../trend/alinhamento";

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

/** Primitivo de alinhamento — fonte única em `../trend/alinhamento.ts` (ARCH-02); re-exportado
 *  aqui para não mexer nos imports de `TrendOperacao.tsx`/`trendOperacao.check.ts`. */
export { alinharNoEixo };

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

/** Categoria de pena da legenda: as quatro categorias de variável do bloco, mais `sp` — a
 *  pena de SP de uma CV é selecionável por si (o operador liga se quiser ver o alvo), então
 *  ela é uma LINHA da legenda, não um traço que a pena da CV arrasta junto. */
export type CategoriaVarOperacao = "cv" | "constraint" | "mv" | "dv" | "sp";

/** Custo em penas de cada categoria: um traço, uma pena. Restrição soma só o traço de PV — a
 *  banda low/high não é uma pena adicional (brief 5.3). CV custava 2 (PV+SP no mesmo item da
 *  legenda); com o SP em pena própria, cada um paga o seu. */
export const CUSTO_PENAS: Readonly<Record<CategoriaVarOperacao, number>> = {
  cv: 1,
  constraint: 1,
  mv: 1,
  dv: 1,
  sp: 1,
};

export interface PenaLegenda {
  /** Identidade da PENA (chave de `ligadas`, do `key` da legenda e da estrutura do gráfico):
   *  igual a `varId` nas penas de variável, `idPenaSp(varId)` na pena de SP. */
  readonly id: string;
  /** Variável a que a pena pertence — de quem vêm cor, nome, escala Y e faixa do operador. */
  readonly varId: string;
  readonly categoria: CategoriaVarOperacao;
  readonly ligada: boolean;
  /** A seleção default ligaria esta pena, mas o teto cortou — a legenda precisa dizer isso,
   *  não só mostrar "desligada" como se fosse escolha do operador (brief 5.3). */
  readonly excedente: boolean;
}

/** Id da pena de SP de uma CV. Prefixo, não campo separado, porque a pena de SP entra no MESMO
 *  conjunto de penas ligadas das variáveis: o teto de 8, o clique da legenda e a estrutura do
 *  gráfico continuam com uma fonte só. `PenaLegenda.varId` faz o caminho de volta — ninguém
 *  precisa desmontar a string. */
export function idPenaSp(cvId: string): string {
  return `sp:${cvId}`;
}

/** Valor corrente de uma linha da legenda (ARCH-04). A pena de variável lê o PV publicado; a
 *  pena de SP lê o ALVO da própria CV — cada uma devolve a série que ela desenha, e repetir o
 *  PV nas duas linhas da mesma CV faria o operador ler o alvo errado justamente na linha que
 *  existe para mostrá-lo. Devolve `null` — e a legenda escreve o travessão, como as telas de
 *  engenharia e fuzzy já fazem — quando a variável não está no último `mpc.state` (bloco
 *  recém-deployado, ou variável fora do quadro). O `sp` nulo é o OUTRO caminho, e hoje é só
 *  defesa contra o tipo do contrato (`MpcVarState.sp: number | null`): no backend atual uma CV
 *  presente em `vars` sempre tem alvo — `blocks/mpc.py` semeia `_sp` com `0.0` por CV e o
 *  publica congelado em AUTO ou rastreado por PV-tracking fora dele, nunca apagado. Penas de
 *  SP só existem para CV (`selecionarPenasDefault`), então o `null` de Restrição/MV/DV nunca
 *  chega aqui por essa via. */
export function valorDaPena(
  pena: PenaLegenda,
  vars: Readonly<Record<string, MpcVarState>>,
): number | null {
  const estado = vars[pena.varId];
  if (estado === undefined) return null;
  return pena.categoria === "sp" ? estado.sp : estado.v;
}

/**
 * Seleção default de penas (decisão A-11, F5R-16; emenda 2026-08-16): CVs (PV) ligam na ordem
 * do config até o teto; Restrições ligam como banda (PV conta no teto) com o que sobrar; MVs,
 * DVs **e a pena de SP de cada CV** nascem desligadas — são opt-in pela legenda, mesmo com o
 * teto livre. Pura: a UI (`TrendOperacao.tsx`) decide o que fazer com um clique depois; esta
 * função só decide o estado inicial.
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
    return { id, varId: id, categoria, ligada, excedente: !ligada };
  }

  function optIn(id: string, categoria: "mv" | "dv"): PenaLegenda {
    return { id, varId: id, categoria, ligada: false, excedente: false };
  }

  return [
    // A pena de SP vem logo abaixo da CV dela: mesma cor na faixa da legenda, e a linha de
    // cima diz de quem é o alvo.
    ...cvs.flatMap((cv) => [
      comTeto(cv.id, "cv"),
      {
        id: idPenaSp(cv.id),
        varId: cv.id,
        categoria: "sp" as const,
        ligada: false,
        excedente: false,
      },
    ]),
    ...constraints.map((c) => comTeto(c.id, "constraint")),
    ...mvs.map((mv) => optIn(mv.id, "mv")),
    ...dvs.map((dv) => optIn(dv.id, "dv")),
  ];
}

/** Pontilhado da pena de SP — padrão distinto do tracejado da predição (`[5, 5]`,
 *  `tracoComFade` em `TrendOperacao.tsx`): sólido = PV medido, pontilhado = SP comandado,
 *  tracejado = futuro. Fonte única do padrão, consumida pelo gráfico e pela faixa da legenda. */
const TINTA_SP = 2;
const VAO_SP = 4;
export const TRACO_SP: number[] = [TINTA_SP, VAO_SP];

/**
 * Traço da pena de SP: matiz da PRÓPRIA CV, pontilhado. O Azul Único nunca desenha dado
 * (DESIGN §Colors) — enquanto o SP saía em `--color-accent`, a tela mostrava uma linha azul que
 * a legenda não explicava, e as CVs ligadas saíam todas no mesmo azul. `rastreado` é o trecho
 * `auto = false`, que puxa o MESMO matiz para o texto do poço (§2.2-1, F5R-21): SP em
 * PV-tracking não é SP comandado. `texto` entra RESOLVIDO porque `color-mix` vai para o canvas,
 * que não resolve `var()` — não há elemento de onde herdar a custom property.
 */
export function tracoPenaSp(
  corDaCv: string,
  texto: string,
  rastreado: boolean,
): { readonly stroke: string; readonly dash: number[]; readonly width: number } {
  return {
    stroke: rastreado ? `color-mix(in oklch, ${corDaCv}, ${texto} 60%)` : corDaCv,
    dash: TRACO_SP,
    width: 1.5,
  };
}

/**
 * Faixa da pena de SP na legenda, no mesmo pontilhado do traço do gráfico. A pena de SP tem o
 * MESMO matiz da CV de propósito (é o alvo daquela variável), então a cor sozinha não separa as
 * duas linhas da legenda — cor + estilo separam (A Regra do Canal Redundante, DESIGN §Colors).
 */
export function faixaPontilhadaSp(cor: string): string {
  const tinta = `${String(TINTA_SP)}px`;
  const vao = `${String(TINTA_SP + VAO_SP)}px`;
  return `repeating-linear-gradient(to right, ${cor} 0 ${tinta}, transparent ${tinta} ${vao})`;
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
