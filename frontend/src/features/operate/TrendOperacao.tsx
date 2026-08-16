import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import { useCanalAoVivo } from "../../app/CanalAoVivo";
import { Button } from "../../components/ui/button";
import type { MpcState } from "../../lib/contracts.gen";
import {
  chaveEscala,
  construirEscalasUplot,
  ESCALA_AUTO,
  gravarEscalas,
  lerEscalas,
  limparEscalas,
  type EscalaVar,
} from "../trend/escalas";
import { JanelaTempo } from "../trend/JanelaTempo";
import { FORMATO_VALOR, lerTemaTrend, type TemaTrend } from "../trend/trendTheme";
import "../trend/trend.css";
import { useJanelaDeslizante } from "../trend/useJanelaDeslizante";
import { LegendaOperacao } from "./LegendaOperacao";
import { ancoraDivisorAgora, calcularRangeXOperacao, pluginSecaoFutura } from "./secaoFutura";
import {
  CUSTO_PENAS,
  OPCOES_DEGRAU_MV,
  TETO_PENAS_OPERACAO,
  TOKENS_PENA_OPERACAO,
  alinharNoEixo,
  atribuirCoresPenas,
  dividirSpPorAuto,
  emendarPlanoNoDivisor,
  mesclarSeriesVivas,
  montarOverlayPrevisao,
  selecionarPenasDefault,
  tetoCarryForwardOperacaoS,
  ultimoCarimboHistorico,
  type AmostraViva,
  type OverlayPrevisao,
  type PenaLegenda,
  type PontoOpc,
  type SerieOperacao,
} from "./trendOperacao";
import { useHistoryMpc } from "./useHistoryMpc";
import type { MpcNodeOut } from "./useMpcs";

/**
 * Trend central com predição (spec F5 §7.4-6; plano F5b tarefas 5.1-5.3; plano de melhorias
 * Fase 2). uPlot re-vestido no molde de `features/trend/TrendChart.tsx`/`trendTheme.ts`:
 * mesma separação entre "estrutura" (recriada só quando a janela, as penas ligadas, o foco
 * de escala ou as escalas manuais mudam) e "dados ao vivo" (aplicados via `setData`, sem
 * recriar a instância — o zoom do operador sobrevive ao poll e à borda viva). Este arquivo
 * faz a montagem visual; `trendOperacao.ts` guarda a lógica pura de dados testada em
 * `trendOperacao.check.ts`, `secaoFutura.ts` guarda a lógica pura da seção futura testada em
 * `secaoFutura.check.ts` (regra global 3: asserts leem dados, nunca pixel).
 *
 * Duas seções (Histórico | Previsão, tarefa 2.2): o eixo x sempre reserva o horizonte futuro
 * (`Np × Ts_mpc`) quando a vista está ao vivo — mesmo fora de AUTO, quando o overlay de
 * predição chega vazio por norma (spec F5 §3.4). Escala Y por variável (tarefa 2.3) e janela
 * deslizante `<`/`>`/Reset (tarefa 2.4) vêm de `features/trend/`, compartilhados com o trend
 * de engenharia — ver `escalas.ts`/`useJanelaDeslizante.ts`.
 */

const ALTURA = 420;
const OVERLAY_VAZIO: OverlayPrevisao = { tAbs: [], agora: null, cv: [], mv: [] };
const SERIE_VAZIA = (id: string): SerieOperacao => ({ id, t: [], v: [], sp: [], auto: [] });

const FORMATO_HORA = new Intl.DateTimeFormat("pt-BR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

// ----------------------------------------------------------------------------------------
// Cor: paleta de série (matiz mais claro + fade ao horizonte) via `color-mix` nativo do CSS
// (já usado em `trend.css` para a seleção de zoom) — nenhuma lib de cor, nenhuma matemática
// OKLCH própria (DESIGN.md §Do's: paleta tem fonte única nos tokens).
// ----------------------------------------------------------------------------------------

function corClara(cor: string): string {
  return `color-mix(in oklch, ${cor}, white 45%)`;
}

function corTransparente(cor: string): string {
  return `color-mix(in oklch, ${cor}, transparent 80%)`;
}

/** SP rastreado: mesmo matiz puxado para o texto do poço. O valor do texto entra RESOLVIDO
 *  (`tema.texto`) porque `color-mix` vai para o canvas, que não resolve `var()` — não há
 *  elemento de onde herdar a custom property. */
function corDessaturada(cor: string, texto: string): string {
  return `color-mix(in oklch, ${cor}, ${texto} 60%)`;
}

/** SP: pontilhado no matiz da própria CV. O Azul Único nunca codifica dado (DESIGN §Colors —
 *  A Regra do Azul Único), e pena azul sem entrada na legenda é linha órfã na tela do
 *  operador. Padrão distinto do tracejado da predição (`[5, 5]` em `tracoComFade`): sólido =
 *  PV medido, pontilhado = SP comandado, tracejado = futuro. */
const TRACO_SP = [2, 4];

/** CV/Restrição tracejada: mesmo matiz mais claro, com fade ao horizonte (§7.4-6). O
 *  gradiente vai de `corClara` em "agora" a quase transparente na ponta do horizonte —
 *  sem `agora` (sem overlay) cai para a cor clara sólida, nunca desenhada de qualquer jeito
 *  (a série fica vazia quando não há predição, §3.4). */
function tracoComFade(corBase: string, agora: number | null): uPlot.Series.Stroke {
  if (agora === null) return corClara(corBase);
  return (u: uPlot) => {
    const x0 = u.valToPos(agora, "x", true);
    const x1 = u.bbox.left + u.bbox.width;
    if (!Number.isFinite(x0) || !Number.isFinite(x1) || x1 <= x0) return corClara(corBase);
    const gradiente = u.ctx.createLinearGradient(x0, 0, x1, 0);
    gradiente.addColorStop(0, corClara(corBase));
    gradiente.addColorStop(1, corTransparente(corBase));
    return gradiente;
  };
}

/** Linha-cursor "agora" (§7.4-6): plugin de desenho, não série — não compete por espaço no
 *  teto de penas e não precisa de Y-range próprio. Lê de uma ref para atualizar a cada
 *  `setData` sem recriar a instância (mesma separação estrutura/dados do resto do arquivo).
 *  A ref não é mais só `overlay.agora`: sem predição, ela vira o relógio (ver componente) —
 *  o divisor entre "Histórico" e "Previsão" não pode sumir só porque o bloco está em LOCAL. */
function pluginLinhaAgora(agoraRef: { current: number | null }, tema: TemaTrend): uPlot.Plugin {
  return {
    hooks: {
      draw: (u: uPlot) => {
        const agora = agoraRef.current;
        if (agora === null) return;
        const x = u.valToPos(agora, "x", true);
        if (!Number.isFinite(x) || x < u.bbox.left || x > u.bbox.left + u.bbox.width) return;
        const { ctx } = u;
        ctx.save();
        ctx.strokeStyle = tema.agora;
        ctx.setLineDash([2, 3]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(Math.round(x) + 0.5, u.bbox.top);
        ctx.lineTo(Math.round(x) + 0.5, u.bbox.top + u.bbox.height);
        ctx.stroke();
        ctx.restore();
      },
    },
  };
}

/** Recorte em X que o operador arrastou no gráfico; `null` = a janela da tela manda. */
type ZoomX = readonly [number, number];

/** Zoom manual em X. O eixo x desta tela tem `range` próprio (a janela precisa incluir o
 *  horizonte da predição, o que a extensão dos dados não daria), e o uPlot chama esse `range`
 *  também no zoom por arrasto — devolver a janela da tela ali é o que engolia o recorte pedido.
 *  O `setSelect` dispara ANTES do `setScale` do zoom (uPlot `mouseUp`), então guardar o recorte
 *  aqui faz o `range` já responder com ele. Guardado em ref, e não dentro da instância, para
 *  sobreviver à recriação do gráfico (trocar o eixo Y, ligar/desligar pena, editar faixa). */
function pluginZoomX(aoRecortar: (faixa: ZoomX) => void): uPlot.Plugin {
  return {
    hooks: {
      setSelect: (u: uPlot) => {
        if (u.select.width <= 0) return;
        aoRecortar([
          u.posToVal(u.select.left, "x"),
          u.posToVal(u.select.left + u.select.width, "x"),
        ]);
      },
    },
  };
}

/** Paleta resolvida do trend de operação — mesmo padrão de `lerTemaTrend` (`getComputedStyle`
 *  sobre `document.documentElement`), mas com a paleta PRÓPRIA de 8 posições
 *  (`TOKENS_PENA_OPERACAO`, `trendOperacao.ts`), não a de 6 do trend de engenharia
 *  (`tema.penas`, `trendTheme.ts`) — §6.6-5: a 7ª/8ª pena colidiam reaproveitando a paleta
 *  de 6, que não bate com o teto de 8 (`TETO_PENAS_OPERACAO`) deste gráfico. */
function lerCoresPenaOperacao(): readonly string[] {
  const estilo = getComputedStyle(document.documentElement);
  return TOKENS_PENA_OPERACAO.map((token) => estilo.getPropertyValue(token).trim());
}

// ----------------------------------------------------------------------------------------
// Montagem das colunas do uPlot (eixo x único, união de histórico + horizonte da predição —
// é isso que dimensiona "o eixo futuro por Np×Ts_mpc": o próprio último ponto de `tAbs`).
// Só as penas em `ligadas` viram série — as demais ficam de fora da estrutura (brief 5.3).
// ----------------------------------------------------------------------------------------

interface ColunasOperacao {
  readonly dados: uPlot.AlignedData;
  readonly series: uPlot.Series[];
  readonly bands: uPlot.Band[];
}

function montarColunas(
  mpc: MpcNodeOut,
  seriesHistoricas: readonly SerieOperacao[],
  overlay: OverlayPrevisao,
  tema: TemaTrend,
  cores: ReadonlyMap<string, string>,
  corPadrao: string,
  ligadas: ReadonlySet<string>,
  tetoCarryS: number,
): ColunasOperacao {
  const porId = new Map(seriesHistoricas.map((serie) => [serie.id, serie]));
  const eixoX = [...new Set([...seriesHistoricas.flatMap((s) => s.t), ...overlay.tAbs])].sort(
    (a, b) => a - b,
  );

  // Fronteira do passado: `eixoX` inclui os carimbos do horizonte, então o carry-forward de
  // `alinharNoEixo` precisa parar aqui — repetir a última medição dentro da seção futura
  // desenhava a pena sólida atravessando a linha do "agora" e terminando à direita de onde a
  // tracejada começa (até 2×Ts_mpc adiante, o teto do carry).
  const limiteHistoricoS = ultimoCarimboHistorico(seriesHistoricas);

  const dados: (number | null)[][] = [];
  const series: uPlot.Series[] = [{ label: "Tempo" }];
  const bands: uPlot.Band[] = [];

  type OpcoesSerie = Omit<uPlot.Series, "label"> & { label: string };

  function pushColuna(coluna: (number | null)[], opts: OpcoesSerie): number {
    dados.push(coluna);
    series.push(opts);
    return series.length - 1;
  }

  /** Pena medida: nos instantes das outras penas repete o último valor conhecido, com gap além
   *  de `tetoCarryS` e nada além da fronteira do passado (ver `alinharNoEixo`). */
  function pushHistorico(
    t: readonly number[],
    valores: readonly (number | null)[],
    opts: OpcoesSerie,
  ): number {
    return pushColuna(alinharNoEixo(eixoX, t, valores, tetoCarryS, limiteHistoricoS), opts);
  }

  /** Pena de predição. Duas coisas, as duas de apresentação (a âncora do plano segue sendo
   *  `prediction.ts`, F5R-01): o trecho já decorrido sai de cena e o traço começa no fim do
   *  sólido (`emendarPlanoNoDivisor`), e o alinhamento é exato nos carimbos do plano
   *  (`tetoS = 0`) — repetir o valor num carimbo alheio viraria degrau numa pena de CV (reta
   *  entre pontos, §3.3) e deslocaria a quina do degrau da MV para fora da fronteira de Ts_mpc,
   *  que é justo o que `align: -1` garante. `spanGaps` liga os pontos do plano por cima dos
   *  carimbos alheios entre eles; a série não tem buraco por construção (o plano vem inteiro no
   *  quadro). */
  function pushPrevisao(valores: readonly number[], degrau: boolean, opts: OpcoesSerie): number {
    const plano = emendarPlanoNoDivisor(overlay.tAbs, valores, limiteHistoricoS, degrau);
    return pushColuna(alinharNoEixo(eixoX, plano.t, plano.v, 0), { ...opts, spanGaps: true });
  }

  // CVs (PV + SP) — linhas de `overlay.cv` = CVs na ordem do config, depois Restrições
  // (spec F4 §5.1/F5 §3.2); o índice de linha é sempre o da posição no config, ligada ou não.
  // Cada variável tem escala própria (`chaveEscala`, tarefa 2.3): PV, previsto, SP e SP
  // rastreado da MESMA CV compartilham a escala — sem isso uma CV em % e outra em t/h
  // achatariam uma contra a outra no mesmo eixo.
  mpc.variables.cvs.forEach((cv, indiceLinha) => {
    if (!ligadas.has(cv.id)) return;
    const historica = porId.get(cv.id) ?? SERIE_VAZIA(cv.id);
    const cor = cores.get(cv.id) ?? corPadrao;
    const scale = chaveEscala(cv.id);
    pushHistorico(historica.t, historica.v, {
      label: `${cv.name} PV`,
      stroke: cor,
      width: 1.5,
      spanGaps: false,
      points: { show: false },
      scale,
    });
    pushPrevisao(overlay.cv[indiceLinha] ?? [], false, {
      label: `${cv.name} previsto`,
      stroke: tracoComFade(cor, overlay.agora),
      width: 1.5,
      dash: [5, 5],
      points: { show: false },
      scale,
    });
    const divisao = dividirSpPorAuto(historica.sp, historica.auto);
    pushHistorico(historica.t, divisao.comandado, {
      label: `${cv.name} SP`,
      stroke: cor,
      width: 1.5,
      dash: TRACO_SP,
      points: { show: false },
      scale,
    });
    pushHistorico(historica.t, divisao.rastreado, {
      label: `${cv.name} SP rastreado`,
      stroke: corDessaturada(cor, tema.texto),
      width: 1.5,
      dash: TRACO_SP,
      points: { show: false },
      scale,
    });
  });

  // Restrições — banda low/high sombreada no Poço; a pena de PV conta no teto (brief 5.3), a
  // banda em si não é uma pena adicional. Mesma escala da própria Restrição: PV, previsto e
  // a banda low/high são a MESMA variável.
  mpc.variables.constraints.forEach((restricao, indiceRestricao) => {
    const indiceLinha = mpc.variables.cvs.length + indiceRestricao;
    if (!ligadas.has(restricao.id)) return;
    const historica = porId.get(restricao.id) ?? SERIE_VAZIA(restricao.id);
    const cor = cores.get(restricao.id) ?? corPadrao;
    const scale = chaveEscala(restricao.id);
    pushHistorico(historica.t, historica.v, {
      label: `${restricao.name} PV`,
      stroke: cor,
      width: 1.5,
      spanGaps: false,
      points: { show: false },
      scale,
    });
    pushPrevisao(overlay.cv[indiceLinha] ?? [], false, {
      label: `${restricao.name} previsto`,
      stroke: tracoComFade(cor, overlay.agora),
      width: 1.5,
      dash: [5, 5],
      points: { show: false },
      scale,
    });
    // A faixa da Restrição não expira em "agora": a banda atravessa o horizonte inteira, então
    // entra por `pushColuna` — sem carry-forward para repetir e sem fronteira para cortar.
    const idxLow = pushColuna(
      eixoX.map(() => restricao.range.low),
      {
        label: `${restricao.name} mín.`,
        stroke: "transparent",
        width: 0,
        points: { show: false },
        scale,
      },
    );
    const idxHigh = pushColuna(
      eixoX.map(() => restricao.range.high),
      {
        label: `${restricao.name} máx.`,
        stroke: "transparent",
        width: 0,
        points: { show: false },
        scale,
      },
    );
    bands.push({ series: [idxLow, idxHigh], fill: tema.banda, dir: -1 });
  });

  // MVs — degrau fantasma stepped align:-1 (§3.3; `OPCOES_DEGRAU_MV` é a única fonte do
  // `align`, nunca `+1`). Opt-in pela legenda (brief 5.3): nasce fora de `ligadas`.
  mpc.variables.mvs.forEach((mv, indiceMv) => {
    if (!ligadas.has(mv.id)) return;
    const historica = porId.get(mv.id) ?? SERIE_VAZIA(mv.id);
    const cor = cores.get(mv.id) ?? corPadrao;
    const scale = chaveEscala(mv.id);
    pushHistorico(historica.t, historica.v, {
      label: `${mv.name} PV`,
      stroke: cor,
      width: 1.5,
      spanGaps: false,
      points: { show: false },
      scale,
    });
    pushPrevisao(overlay.mv[indiceMv] ?? [], true, {
      label: `${mv.name} previsto`,
      stroke: corClara(cor),
      width: 1.5,
      dash: [5, 5],
      paths: (u, seriesIdx, idx0, idx1) =>
        (uPlot.paths.stepped as (opts: typeof OPCOES_DEGRAU_MV) => uPlot.Series.PathBuilder)(
          OPCOES_DEGRAU_MV,
        )(u, seriesIdx, idx0, idx1),
      points: { show: false },
      scale,
    });
  });

  // DVs — somente leitura, sem predição (não entram em `overlay`, §5.1 do F4). Opt-in.
  mpc.variables.dvs.forEach((dv) => {
    if (!ligadas.has(dv.id)) return;
    const historica = porId.get(dv.id) ?? SERIE_VAZIA(dv.id);
    const cor = cores.get(dv.id) ?? corPadrao;
    pushHistorico(historica.t, historica.v, {
      label: `${dv.name} PV`,
      stroke: cor,
      width: 1.5,
      spanGaps: false,
      points: { show: false },
      scale: chaveEscala(dv.id),
    });
  });

  return { dados: [eixoX, ...dados] as uPlot.AlignedData, series, bands };
}

function construirOpcoesOperacao(
  colunas: ColunasOperacao,
  tema: TemaTrend,
  largura: number,
  altura: number,
  agoraDivisorRef: { current: number | null },
  semPredicaoRef: { current: boolean },
  rangeXRef: { current: readonly [number, number] },
  zoomXRef: { current: ZoomX | null },
  aoZoom: (faixa: ZoomX | null) => void,
  escalasY: uPlot.Scales,
  eixoYChave: string,
  eixoYCor: string,
): uPlot.Options {
  const grade = { stroke: tema.linha, width: 1 };
  const fonte = `11px ${tema.mono}`;
  return {
    width: largura,
    height: altura,
    legend: { show: false },
    cursor: {
      y: false,
      points: { show: false },
      // Duplo-clique é o reset de zoom do uPlot (`autoScaleX`): o recorte precisa cair ANTES,
      // senão o `range` abaixo devolveria o recorte velho e o reset não resetaria nada. Do bind
      // default do uPlot (`filtBtn0`) só o filtro de botão principal é replicado — o alvo não,
      // porque o retângulo de seleção fica por cima do `.u-over` e resetar por ele é o esperado.
      bind: {
        dblclick: (_u, _alvo, padrao) => (evento) => {
          if (evento.button !== 0) return null;
          aoZoom(null);
          return padrao(evento);
        },
      },
    },
    series: colunas.series,
    bands: colunas.bands,
    // `x` é dinâmico (tarefa 2.2, `calcularRangeXOperacao`): a função é reavaliada a cada
    // re-range do uPlot, então lê as refs sempre frescas sem recriar a instância. O zoom
    // manual do operador tem precedência sobre a janela da tela enquanto existir. O `as` é só
    // interoperabilidade: `Range.MinMax` do uPlot é tupla mutável e ele nunca escreve nela.
    // As escalas Y (tarefa 2.3) vêm prontas de `construirEscalasUplot`, uma por variável.
    scales: {
      x: {
        range: (): uPlot.Range.MinMax =>
          (zoomXRef.current ?? rangeXRef.current) as [number, number],
      },
      ...escalasY,
    },
    plugins: [
      pluginLinhaAgora(agoraDivisorRef, tema),
      pluginSecaoFutura(agoraDivisorRef, semPredicaoRef, tema),
      pluginZoomX(aoZoom),
    ],
    axes: [
      {
        stroke: tema.texto,
        font: fonte,
        grid: grade,
        ticks: grade,
        border: grade,
        space: 90,
        values: (_u, marcas) => marcas.map((s) => FORMATO_HORA.format(new Date(s * 1000))),
      },
      {
        // Eixo Y visível único, vinculado à variável focada (tarefa 2.3) — as demais escalas
        // existem (série a usa) mas não ganham eixo desenhado.
        scale: eixoYChave,
        stroke: eixoYCor,
        font: fonte,
        grid: grade,
        ticks: grade,
        border: grade,
        size: 64,
        values: (_u, marcas) => marcas.map((v) => FORMATO_VALOR.format(v)),
      },
    ],
  };
}

// ----------------------------------------------------------------------------------------
// Componente
// ----------------------------------------------------------------------------------------

export interface TrendOperacaoProps {
  readonly flowId: number;
  readonly blockId: string;
  readonly mpc: MpcNodeOut;
  readonly mpcState: MpcState | undefined;
}

export function TrendOperacao({ flowId, blockId, mpc, mpcState }: TrendOperacaoProps) {
  // Janela por valor+unidade (B-7): inteiro em segundos/minutos, default 30 min.
  const [janelaSegundos, setJanelaSegundos] = useState(1800);

  // Janela deslizante `<`/`>`/Reset (tarefa 2.4) — `fimEpochS === null` é ao vivo.
  const janelaDeslizante = useJanelaDeslizante(janelaSegundos);

  // Todas as variáveis são buscadas de uma vez (teto de 14 do `/api/history/mpc` cobre o
  // teto de config do bloco inteiro — 4 MV + 6 CV/Restr + 4 DV): ligar uma pena pela legenda
  // nunca dispara requisição nova, só muda o que a estrutura do gráfico desenha.
  const idsHistorico = useMemo(
    () => [
      ...mpc.variables.cvs.map((cv) => cv.id),
      ...mpc.variables.constraints.map((c) => c.id),
      ...mpc.variables.mvs.map((mv) => mv.id),
      ...mpc.variables.dvs.map((dv) => dv.id),
    ],
    [mpc],
  );

  const historico = useHistoryMpc(
    flowId,
    blockId,
    idsHistorico,
    janelaSegundos,
    janelaDeslizante.fimEpochS,
  );

  // Mapa variável → tag OPC (B-2): a ponta viva adensa na taxa OPC para as variáveis com
  // tag mapeada; as demais seguem só na cadência do `mpc.state` (fallback, sem erro).
  const tagsPorVar = useMemo(() => {
    const mapa = new Map<string, number>();
    for (const v of [
      ...mpc.variables.cvs,
      ...mpc.variables.constraints,
      ...mpc.variables.mvs,
      ...mpc.variables.dvs,
    ]) {
      if (v.tag_id != null) mapa.set(v.id, v.tag_id);
    }
    return mapa;
  }, [mpc]);

  // Borda viva (brief 5.1): cada `mpc.state` empilha uma amostra; o corte pela janela atual
  // acontece na leitura (useMemo abaixo), não aqui — trocar de janela não precisa esperar o
  // próximo quadro para reduzir o que está fora dela.
  const [vivas, setVivas] = useState<AmostraViva[]>([]);
  useEffect(() => {
    if (!mpcState) return;
    const emAuto = mpcState.modes.local_remote === "remote" && mpcState.modes.man_auto === "auto";
    setVivas((atual) => [
      ...atual.filter((a) => Date.parse(a.ts) / 1000 >= Date.now() / 1000 - 8 * 3600),
      { ts: mpcState.ts, vars: mpcState.vars, auto: emAuto },
    ]);
  }, [mpcState]);

  // Ponta viva na taxa OPC (B-4): o provider já coalesce a 250 ms (`tagValues`); aqui cada
  // flush anexa os pontos novos de cada variável com tag (dedupe pelo `ts` da leitura) e o
  // buffer publicado alimenta o merge. O histórico REST segue amostrado por Ts_mpc — o
  // adensamento é só da borda viva (PRD §5.12).
  const { tagValues } = useCanalAoVivo();
  const vivasOpcRef = useRef(new Map<string, { ultimoTs: string; pontos: PontoOpc[] }>());
  const [pontosOpc, setPontosOpc] = useState<ReadonlyMap<string, readonly PontoOpc[]>>(
    new Map(),
  );
  useEffect(() => {
    if (tagsPorVar.size === 0) return;
    const buffer = vivasOpcRef.current;
    let mudou = false;
    for (const [varId, tagId] of tagsPorVar) {
      const leitura = tagValues.get(tagId);
      if (leitura === undefined || !leitura.ok || leitura.v === null) continue;
      const entrada = buffer.get(varId) ?? { ultimoTs: "", pontos: [] };
      if (leitura.ts === entrada.ultimoTs) continue;
      entrada.ultimoTs = leitura.ts;
      const corte = Date.now() / 1000 - janelaSegundos;
      entrada.pontos = [
        ...entrada.pontos.filter((p) => p.t >= corte),
        { t: Date.parse(leitura.ts) / 1000, v: leitura.v },
      ];
      buffer.set(varId, entrada);
      mudou = true;
    }
    if (mudou) {
      setPontosOpc(new Map([...buffer].map(([varId, e]) => [varId, e.pontos] as const)));
    }
  }, [tagValues, tagsPorVar, janelaSegundos]);

  // Pausado/deslizado (tarefa 2.4), a borda viva para de entrar no gráfico: a vista congelada
  // não pode ganhar pontos que "vazam" do fim escolhido pelo operador.
  const seriesMescladas = useMemo(() => {
    if (!historico.data) return null;
    if (!janelaDeslizante.aoVivo) {
      return mesclarSeriesVivas(historico.data, [], idsHistorico);
    }
    const corte = Date.now() / 1000 - janelaSegundos;
    const vivasNaJanela = vivas.filter((a) => Date.parse(a.ts) / 1000 >= corte);
    return mesclarSeriesVivas(historico.data, vivasNaJanela, idsHistorico, pontosOpc);
  }, [historico.data, vivas, janelaSegundos, idsHistorico, janelaDeslizante.aoVivo, pontosOpc]);

  const overlay = useMemo(
    () => (mpcState ? montarOverlayPrevisao(mpcState.prediction) : OVERLAY_VAZIO),
    [mpcState],
  );

  const tema = useMemo(() => lerTemaTrend(), []);
  // Paleta PRÓPRIA do trend de operação (§6.6-5) — não `tema.penas` (6, do trend de
  // engenharia): o resto do tema (grade, eixos, mono, accent, poço) segue vindo de
  // `lerTemaTrend()`, só a cor de pena tem fonte própria de 8 posições.
  const coresPena = useMemo(() => lerCoresPenaOperacao(), []);
  const cores = useMemo(
    () => atribuirCoresPenas(idsHistorico, coresPena),
    [idsHistorico, coresPena],
  );

  // Defaults (decisão A-11, F5R-16): calculados uma vez por MPC aberto — recalcular a cada
  // refetch de `useMpcs()` religaria penas que o operador tinha desligado deliberadamente.
  const defaults = useMemo(
    () =>
      selecionarPenasDefault(
        mpc.variables.cvs,
        mpc.variables.constraints,
        mpc.variables.mvs,
        mpc.variables.dvs,
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mpc.flow_id, mpc.block_id],
  );
  const porIdDefinicao = useMemo(
    () =>
      new Map(
        [
          ...mpc.variables.cvs,
          ...mpc.variables.constraints,
          ...mpc.variables.mvs,
          ...mpc.variables.dvs,
        ].map((v) => [v.id, v]),
      ),
    [mpc],
  );

  const [ligadas, setLigadas] = useState<ReadonlySet<string>>(
    () => new Set(defaults.filter((pena) => pena.ligada).map((pena) => pena.id)),
  );
  // Variável focada (tarefa 2.3): dona do único eixo Y visível. Default = primeira ligada;
  // depois disso, a última ligada pela legenda assume o foco (ver `alternarPena`).
  const [foco, setFoco] = useState<string | null>(
    () => defaults.find((pena) => pena.ligada)?.id ?? null,
  );
  const [aviso, setAviso] = useState<string | null>(null);

  // Escala Y por variável (tarefa 2.3) — persistida por flow+bloco: trocar de MPC não herda
  // a preferência de outro bloco.
  const chaveEscalasStorage = `ottima.operate.escalas.v1:${String(flowId)}/${blockId}`;
  const [escalasPorVar, setEscalasPorVar] = useState<Readonly<Record<string, EscalaVar>>>(() =>
    lerEscalas(chaveEscalasStorage),
  );

  function mudarEscala(varId: string, escala: EscalaVar): void {
    setEscalasPorVar((atual) => {
      const proximo = { ...atual, [varId]: escala };
      gravarEscalas(chaveEscalasStorage, proximo);
      return proximo;
    });
  }

  /** Clique na legenda (brief 5.3): desligar nunca é bloqueado; ligar respeita o mesmo teto
   *  de 8 penas dos defaults — sem isso o operador furaria o teto pena por pena. A variável
   *  ligada por último vira o foco do eixo Y (tarefa 2.3); desligar a focada passa o foco
   *  para outra ligada (ou nenhuma, se essa era a última). */
  function alternarPena(pena: PenaLegenda): void {
    if (ligadas.has(pena.id)) {
      const proxima = new Set(ligadas);
      proxima.delete(pena.id);
      setLigadas(proxima);
      setAviso(null);
      if (foco === pena.id) setFoco([...proxima][0] ?? null);
      return;
    }
    const custoAtual = defaults.reduce(
      (soma, item) => soma + (ligadas.has(item.id) ? CUSTO_PENAS[item.categoria] : 0),
      0,
    );
    if (custoAtual + CUSTO_PENAS[pena.categoria] > TETO_PENAS_OPERACAO) {
      setAviso(`Máximo de ${String(TETO_PENAS_OPERACAO)} penas por gráfico`);
      return;
    }
    setLigadas(new Set([...ligadas, pena.id]));
    setFoco(pena.id);
    setAviso(null);
  }

  /** Clique na linha da legenda: a variável clicada passa a ser dona do único eixo Y visível.
   *  Pena desligada não pode ser foco — o eixo pertence a quem está desenhado —, então a linha
   *  liga a pena pelo mesmo caminho do checkbox, que já respeita o teto e leva o foco com ela.
   *  Nenhum clique na linha desliga pena nenhuma: mover o eixo nunca apaga uma variável. */
  function focarPena(pena: PenaLegenda): void {
    if (ligadas.has(pena.id)) {
      setFoco(pena.id);
      // O aviso do teto é de uma tentativa de ligar pena, não do eixo: sem limpar aqui, ele
      // ficaria pendurado na tela enquanto o operador só troca de eixo, descrevendo outra ação.
      setAviso(null);
      return;
    }
    alternarPena(pena);
  }

  // Teto do carry-forward do eixo compartilhado: a cadência do histórico é Ts_mpc no modo bruto
  // e o bucket de 1 min no agregado (`GET /api/history/mpc`), então o modo entra no cálculo.
  const tetoCarryS = tetoCarryForwardOperacaoS(
    historico.data?.mode ?? "raw",
    mpc.horizons.ts_mpc,
  );

  const colunas = useMemo(
    () =>
      seriesMescladas
        ? montarColunas(mpc, seriesMescladas, overlay, tema, cores, coresPena[0], ligadas, tetoCarryS)
        : null,
    [mpc, seriesMescladas, overlay, tema, cores, coresPena, ligadas, tetoCarryS],
  );

  const escalasUplot = useMemo(
    () =>
      construirEscalasUplot(
        [...ligadas].map((id) => ({ id, escala: escalasPorVar[id] ?? ESCALA_AUTO })),
      ),
    [ligadas, escalasPorVar],
  );
  const eixoYChave = (foco !== null ? escalasUplot.scaleKeyPorVar.get(foco) : undefined) ?? "y";
  const eixoYCor = (foco !== null ? cores.get(foco) : undefined) ?? tema.texto;

  // Horizonte futuro (tarefa 2.1/2.2): `Np × Ts_mpc`, derivado pelo servidor (`mpc.horizons`)
  // — o cliente nunca recalcula a partir de `tss` (a projeção não expõe, spec §4.1-3).
  const horizonteFuturoS = mpc.horizons.np * mpc.horizons.ts_mpc;
  const semPredicao = overlay.agora === null && janelaDeslizante.aoVivo;

  const container = useRef<HTMLDivElement>(null);
  const grafico = useRef<uPlot | null>(null);
  // Zoom manual em X (arrasto no gráfico): estado porque a tela precisa avisar que a vista
  // parou de seguir o relógio, e ref porque o `range` do eixo x roda DENTRO do `setScale` do
  // próprio zoom — esperar o re-render do React devolveria a janela velha e comeria o recorte.
  // Declarado antes da âncora do "agora" porque é ela que decide se o divisor anda.
  const [zoomX, setZoomX] = useState<ZoomX | null>(null);
  const zoomXRef = useRef<ZoomX | null>(null);
  function aplicarZoomX(faixa: ZoomX | null): void {
    zoomXRef.current = faixa;
    setZoomX(faixa);
  }

  // Âncora do divisor "agora"/seção futura — política em `ancoraDivisorAgora` (uma só, também
  // usada pelo tique de 1 s abaixo): relógio de parede ao vivo (B-5), congelada sob zoom manual,
  // nula na janela deslizada. O overlay de predição segue ancorado em `prediction.ts` (F5R-01),
  // isso é só a LINHA.
  const agoraDivisorRef = useRef<number | null>(null);
  agoraDivisorRef.current = ancoraDivisorAgora(
    agoraDivisorRef.current,
    janelaDeslizante.aoVivo,
    zoomXRef.current !== null,
    Date.now() / 1000,
  );
  const semPredicaoRef = useRef(false);
  semPredicaoRef.current = semPredicao;
  const rangeXRef = useRef<readonly [number, number]>([0, 0]);
  rangeXRef.current = calcularRangeXOperacao({
    fimEpochS: janelaDeslizante.fimEpochS,
    agoraEpochS: Date.now() / 1000,
    janelaSegundos,
    horizonteFuturoS,
  });
  const colunasAtuais = useRef(colunas);
  colunasAtuais.current = colunas;

  const idsEstrutura = defaults.filter((pena) => ligadas.has(pena.id)).map((pena) => pena.id);
  const escalaAssinatura = idsEstrutura
    .map((id) => {
      const e = escalasPorVar[id] ?? ESCALA_AUTO;
      return e.auto ? `${id}:a` : `${id}:${String(e.min)}-${String(e.max)}`;
    })
    .join(",");
  const estrutura = `${String(janelaSegundos)}|${idsEstrutura.join(",")}|${escalaAssinatura}|${foco ?? ""}`;

  useEffect(() => {
    const alvo = container.current;
    const atuais = colunasAtuais.current;
    if (!alvo || !atuais) return;
    const instancia = new uPlot(
      construirOpcoesOperacao(
        atuais,
        tema,
        alvo.clientWidth,
        ALTURA,
        agoraDivisorRef,
        semPredicaoRef,
        rangeXRef,
        zoomXRef,
        aplicarZoomX,
        escalasUplot.scales,
        eixoYChave,
        eixoYCor,
      ),
      atuais.dados,
      alvo,
    );
    grafico.current = instancia;
    const observador = new ResizeObserver(() => {
      instancia.setSize({ width: alvo.clientWidth, height: ALTURA });
    });
    observador.observe(alvo);
    return () => {
      observador.disconnect();
      instancia.destroy();
      grafico.current = null;
    };
    // Só a `estrutura` recria a instância: tudo o mais que entra em `construirOpcoesOperacao`
    // é estável entre renders (refs e o setter do zoom, que `aplicarZoomX` só fecha por cima).
    // Nunca passe daqui um valor reativo sem colocá-lo na `estrutura` — ele congelaria no
    // fechamento da instância criada aqui.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estrutura, colunas === null]);

  useEffect(() => {
    const instancia = grafico.current;
    if (!instancia || !colunas) return;
    // Com zoom manual o dado novo entra sem re-ranger: re-ranger devolveria a janela da tela
    // e apagaria o recorte que o operador está olhando.
    instancia.setData(colunas.dados, zoomXRef.current === null);
  }, [colunas]);

  // Tique de 1 s da linha "agora" (B-5): re-ancora no relógio de parede e reaplica a janela X
  // via `setScale`, para o redesenho (plugin `pluginLinhaAgora`) acontecer mesmo sem dado novo
  // chegando. A âncora passa pela MESMA política do render (`ancoraDivisorAgora`) — quem congela
  // sob zoom manual é ela, não este `if`, senão os dois escritores voltam a divergir. O
  // `setScale` é que continua condicionado ao recorte: o operador está olhando um pedaço e a
  // vista não pode andar debaixo dele.
  useEffect(() => {
    const id = window.setInterval(() => {
      const instancia = grafico.current;
      if (!instancia) return;
      const agora = Date.now() / 1000;
      agoraDivisorRef.current = ancoraDivisorAgora(
        agoraDivisorRef.current,
        janelaDeslizante.aoVivo,
        zoomXRef.current !== null,
        agora,
      );
      if (!janelaDeslizante.aoVivo || zoomXRef.current !== null) return;
      rangeXRef.current = calcularRangeXOperacao({
        fimEpochS: janelaDeslizante.fimEpochS,
        agoraEpochS: agora,
        janelaSegundos,
        horizonteFuturoS,
      });
      instancia.setScale("x", { min: rangeXRef.current[0], max: rangeXRef.current[1] });
    }, 1000);
    return () => {
      window.clearInterval(id);
    };
  }, [janelaDeslizante.aoVivo, janelaDeslizante.fimEpochS, janelaSegundos, horizonteFuturoS]);

  /** Reset layout (tarefa 2.4): volta ao vivo, solta o zoom manual e re-ranger no mesmo clique
   *  — sem o `setData(dados, true)` explícito, o recorte sobreviveria ao `reset()` do hook (o
   *  efeito de dados acima preserva zoom por design). Completo (B-6): zera também as escalas Y
   *  por variável — e remove a preferência persistida, senão o próximo reload ressuscitaria a
   *  escala que o reset acabou de apagar. */
  function aoClicarReset(): void {
    aplicarZoomX(null);
    janelaDeslizante.reset();
    limparEscalas(chaveEscalasStorage);
    setEscalasPorVar({});
    const instancia = grafico.current;
    const atuais = colunasAtuais.current;
    if (instancia && atuais) {
      instancia.setData(atuais.dados, true);
    }
  }

  return (
    <div data-testid="operate-trend" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="plaqueta text-xs text-fg-muted">Trend</h2>
        <div className="flex flex-wrap items-center gap-2">
          {/* Largura da janela, deslizar e reset re-miram o eixo x: o recorte do operador era
              um pedaço da janela ANTERIOR, mantê-lo ignoraria o comando que ele acabou de dar. */}
          <JanelaTempo
            prefixoTestid="operate"
            segundos={janelaSegundos}
            onChange={(segundos) => {
              aplicarZoomX(null);
              setJanelaSegundos(segundos);
            }}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="operate-janela-voltar"
            onClick={() => {
              aplicarZoomX(null);
              janelaDeslizante.voltar();
            }}
          >
            {"<"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="operate-janela-avancar"
            disabled={janelaDeslizante.aoVivo}
            onClick={() => {
              aplicarZoomX(null);
              janelaDeslizante.avancar();
            }}
          >
            {">"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="operate-janela-reset"
            onClick={aoClicarReset}
          >
            Reset layout
          </Button>
        </div>
      </div>

      {historico.isError && (
        <p role="alert" data-testid="operate-trend-erro" className="text-sm text-alarm">
          Falha ao consultar o histórico do bloco
        </p>
      )}

      {!colunas && !historico.isError && (
        <div className="rounded-md border border-well-chart-border bg-well-chart p-6">
          <p className="text-sm text-well-chart-fg">Carregando…</p>
        </div>
      )}

      {colunas && (
        <div
          data-testid="operate-trend-chart"
          className="rounded-md border border-well-chart-border bg-well-chart p-2"
        >
          <div className="flex justify-between px-1 text-xs text-well-chart-fg">
            <span>Histórico</span>
            {janelaDeslizante.aoVivo && (
              <span data-testid="operate-trend-secao-futura">Previsão</span>
            )}
          </div>
          <div ref={container} className="w-full" />
          {semPredicao && (
            <p
              data-testid="operate-trend-sem-predicao"
              className="mt-1 text-center text-xs text-well-chart-fg"
            >
              Sem predição — MPC fora de AUTO
            </p>
          )}
        </div>
      )}

      {/* Fora do poço: `text-warn-fg` é escuro por design (superfície clara) e sumiria contra o
          fundo do gráfico — dentro do poço só entra texto em `text-well-chart-fg`. */}
      {zoomX !== null && (
        <p role="status" data-testid="operate-trend-zoom" className="text-xs text-warn-fg">
          Zoom manual — a vista não segue o tempo. Duplo-clique ou Reset layout para voltar
        </p>
      )}

      <LegendaOperacao
        defaults={defaults}
        ligadas={ligadas}
        porIdDefinicao={porIdDefinicao}
        cores={cores}
        foco={foco}
        escalas={escalasPorVar}
        onAlternarPena={alternarPena}
        onFocarPena={focarPena}
        onMudarEscala={mudarEscala}
      />

      {aviso && (
        <p role="alert" data-testid="operate-trend-aviso" className="text-xs text-warn-fg">
          {aviso}
        </p>
      )}
    </div>
  );
}
