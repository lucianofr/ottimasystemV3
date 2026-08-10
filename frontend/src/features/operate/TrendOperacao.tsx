import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import { Button } from "../../components/ui/button";
import { Select } from "../../components/ui/select";
import type { MpcState } from "../../lib/contracts.gen";
import {
  chaveEscala,
  construirEscalasUplot,
  ESCALA_AUTO,
  gravarEscalas,
  lerEscalas,
  type EscalaVar,
} from "../trend/escalas";
import { FORMATO_VALOR, lerTemaTrend, type TemaTrend } from "../trend/trendTheme";
import "../trend/trend.css";
import { useJanelaDeslizante } from "../trend/useJanelaDeslizante";
import { LegendaOperacao } from "./LegendaOperacao";
import { calcularRangeXOperacao, pluginSecaoFutura } from "./secaoFutura";
import {
  CUSTO_PENAS,
  JANELAS_OPERACAO,
  JANELA_PADRAO_ID,
  OPCOES_DEGRAU_MV,
  TETO_PENAS_OPERACAO,
  TOKENS_PENA_OPERACAO,
  atribuirCoresPenas,
  dividirSpPorAuto,
  mesclarSeriesVivas,
  montarOverlayPrevisao,
  selecionarPenasDefault,
  type AmostraViva,
  type JanelaOperacao,
  type OverlayPrevisao,
  type PenaLegenda,
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

function corDessaturada(cor: string): string {
  return `color-mix(in oklch, ${cor}, var(--color-fg-muted) 60%)`;
}

function corBanda(poco: string): string {
  return `color-mix(in oklch, ${poco}, transparent 30%)`;
}

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
        ctx.strokeStyle = tema.texto;
        ctx.setLineDash([2, 2]);
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
): ColunasOperacao {
  const porId = new Map(seriesHistoricas.map((serie) => [serie.id, serie]));
  const eixoX = [...new Set([...seriesHistoricas.flatMap((s) => s.t), ...overlay.tAbs])].sort(
    (a, b) => a - b,
  );

  function remapear(t: readonly number[], valores: readonly (number | null)[]): (number | null)[] {
    const porT = new Map(t.map((ts, i) => [ts, valores[i]]));
    return eixoX.map((ts) => porT.get(ts) ?? null);
  }

  const dados: (number | null)[][] = [];
  const series: uPlot.Series[] = [{ label: "Tempo" }];
  const bands: uPlot.Band[] = [];

  function pushSerie(
    t: readonly number[],
    valores: readonly (number | null)[],
    opts: Omit<uPlot.Series, "label"> & { label: string },
  ): number {
    dados.push(remapear(t, valores));
    series.push(opts);
    return series.length - 1;
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
    pushSerie(historica.t, historica.v, {
      label: `${cv.name} PV`,
      stroke: cor,
      width: 1.5,
      spanGaps: false,
      points: { show: false },
      scale,
    });
    pushSerie(overlay.tAbs, overlay.cv[indiceLinha] ?? [], {
      label: `${cv.name} previsto`,
      stroke: tracoComFade(cor, overlay.agora),
      width: 1.5,
      dash: [4, 3],
      points: { show: false },
      scale,
    });
    const divisao = dividirSpPorAuto(historica.sp, historica.auto);
    pushSerie(historica.t, divisao.comandado, {
      label: `${cv.name} SP`,
      stroke: tema.accent,
      width: 1.5,
      points: { show: false },
      scale,
    });
    pushSerie(historica.t, divisao.rastreado, {
      label: `${cv.name} SP rastreado`,
      stroke: corDessaturada(tema.accent),
      width: 1.5,
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
    pushSerie(historica.t, historica.v, {
      label: `${restricao.name} PV`,
      stroke: cor,
      width: 1.5,
      spanGaps: false,
      points: { show: false },
      scale,
    });
    pushSerie(overlay.tAbs, overlay.cv[indiceLinha] ?? [], {
      label: `${restricao.name} previsto`,
      stroke: tracoComFade(cor, overlay.agora),
      width: 1.5,
      dash: [4, 3],
      points: { show: false },
      scale,
    });
    const idxLow = pushSerie(
      eixoX,
      eixoX.map(() => restricao.range.low),
      {
        label: `${restricao.name} mín.`,
        stroke: "transparent",
        width: 0,
        points: { show: false },
        scale,
      },
    );
    const idxHigh = pushSerie(
      eixoX,
      eixoX.map(() => restricao.range.high),
      {
        label: `${restricao.name} máx.`,
        stroke: "transparent",
        width: 0,
        points: { show: false },
        scale,
      },
    );
    bands.push({ series: [idxLow, idxHigh], fill: corBanda(tema.poco), dir: -1 });
  });

  // MVs — degrau fantasma stepped align:-1 (§3.3; `OPCOES_DEGRAU_MV` é a única fonte do
  // `align`, nunca `+1`). Opt-in pela legenda (brief 5.3): nasce fora de `ligadas`.
  mpc.variables.mvs.forEach((mv, indiceMv) => {
    if (!ligadas.has(mv.id)) return;
    const historica = porId.get(mv.id) ?? SERIE_VAZIA(mv.id);
    const cor = cores.get(mv.id) ?? corPadrao;
    const scale = chaveEscala(mv.id);
    pushSerie(historica.t, historica.v, {
      label: `${mv.name} PV`,
      stroke: cor,
      width: 1.5,
      spanGaps: false,
      points: { show: false },
      scale,
    });
    pushSerie(overlay.tAbs, overlay.mv[indiceMv] ?? [], {
      label: `${mv.name} previsto`,
      stroke: corClara(cor),
      width: 1.5,
      dash: [4, 3],
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
    pushSerie(historica.t, historica.v, {
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
    cursor: { y: false, points: { show: false } },
    series: colunas.series,
    bands: colunas.bands,
    // `x` é dinâmico (tarefa 2.2, `calcularRangeXOperacao`): a função é reavaliada a cada
    // re-range do uPlot, então lê `rangeXRef.current` sempre fresco sem recriar a instância.
    // As escalas Y (tarefa 2.3) vêm prontas de `construirEscalasUplot`, uma por variável.
    scales: {
      x: { range: (): uPlot.Range.MinMax => rangeXRef.current as [number, number] },
      ...escalasY,
    },
    plugins: [
      pluginLinhaAgora(agoraDivisorRef, tema),
      pluginSecaoFutura(agoraDivisorRef, semPredicaoRef, tema),
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
  const [janelaId, setJanelaId] = useState<JanelaOperacao["id"]>(JANELA_PADRAO_ID);
  const janela = JANELAS_OPERACAO.find((item) => item.id === janelaId) ?? JANELAS_OPERACAO[1];

  // Janela deslizante `<`/`>`/Reset (tarefa 2.4) — `fimEpochS === null` é ao vivo.
  const janelaDeslizante = useJanelaDeslizante(janela.segundos);

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
    janela.segundos,
    janelaDeslizante.fimEpochS,
  );

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

  // Pausado/deslizado (tarefa 2.4), a borda viva para de entrar no gráfico: a vista congelada
  // não pode ganhar pontos que "vazam" do fim escolhido pelo operador.
  const seriesMescladas = useMemo(() => {
    if (!historico.data) return null;
    if (!janelaDeslizante.aoVivo) {
      return mesclarSeriesVivas(historico.data, [], idsHistorico);
    }
    const corte = Date.now() / 1000 - janela.segundos;
    const vivasNaJanela = vivas.filter((a) => Date.parse(a.ts) / 1000 >= corte);
    return mesclarSeriesVivas(historico.data, vivasNaJanela, idsHistorico);
  }, [historico.data, vivas, janela.segundos, idsHistorico, janelaDeslizante.aoVivo]);

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

  function mudarEscalaFoco(escala: EscalaVar): void {
    if (foco === null) return;
    const alvo = foco;
    setEscalasPorVar((atual) => {
      const proximo = { ...atual, [alvo]: escala };
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

  const colunas = useMemo(
    () =>
      seriesMescladas
        ? montarColunas(mpc, seriesMescladas, overlay, tema, cores, coresPena[0], ligadas)
        : null,
    [mpc, seriesMescladas, overlay, tema, cores, coresPena, ligadas],
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
  const focoEscala = foco !== null ? (escalasPorVar[foco] ?? ESCALA_AUTO) : ESCALA_AUTO;

  // Horizonte futuro (tarefa 2.1/2.2): `Np × Ts_mpc`, derivado pelo servidor (`mpc.horizons`)
  // — o cliente nunca recalcula a partir de `tss` (a projeção não expõe, spec §4.1-3).
  const horizonteFuturoS = mpc.horizons.np * mpc.horizons.ts_mpc;
  const semPredicao = overlay.agora === null && janelaDeslizante.aoVivo;

  const container = useRef<HTMLDivElement>(null);
  const grafico = useRef<uPlot | null>(null);
  // Âncora do divisor "agora"/seção futura: sem predição, vira o relógio — nunca `null` em
  // vista ao vivo (o divisor não pode sumir só porque o bloco está fora de AUTO).
  const agoraDivisorRef = useRef<number | null>(null);
  agoraDivisorRef.current = janelaDeslizante.aoVivo ? (overlay.agora ?? Date.now() / 1000) : null;
  const semPredicaoRef = useRef(false);
  semPredicaoRef.current = semPredicao;
  const rangeXRef = useRef<readonly [number, number]>([0, 0]);
  rangeXRef.current = calcularRangeXOperacao({
    fimEpochS: janelaDeslizante.fimEpochS,
    agoraEpochS: Date.now() / 1000,
    janelaSegundos: janela.segundos,
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
  const estrutura = `${janela.id}|${idsEstrutura.join(",")}|${escalaAssinatura}|${foco ?? ""}`;

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estrutura, colunas === null]);

  useEffect(() => {
    const instancia = grafico.current;
    if (!instancia || !colunas) return;
    const x = instancia.data[0];
    const zoomado =
      x.length > 0 &&
      ((instancia.scales.x.min ?? 0) > x[0] || (instancia.scales.x.max ?? 0) < x[x.length - 1]);
    instancia.setData(colunas.dados, !zoomado);
  }, [colunas]);

  /** Reset layout (tarefa 2.4): volta ao vivo E limpa o zoom manual do uPlot no mesmo clique
   *  — sem o `setData(dados, true)` explícito, um zoom/pan em andamento sobreviveria ao
   *  `reset()` do hook (o efeito de dados acima preserva zoom por design). */
  function aoClicarReset(): void {
    janelaDeslizante.reset();
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
          <label className="flex items-center gap-2">
            <span className="plaqueta text-xs text-fg-muted">Janela</span>
            <Select
              data-testid="operate-trend-window"
              className="w-28"
              value={janelaId}
              onChange={(evento) => setJanelaId(evento.target.value as JanelaOperacao["id"])}
            >
              {JANELAS_OPERACAO.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.rotulo}
                </option>
              ))}
            </Select>
          </label>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="operate-janela-voltar"
            onClick={janelaDeslizante.voltar}
          >
            {"<"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="operate-janela-avancar"
            disabled={janelaDeslizante.aoVivo}
            onClick={janelaDeslizante.avancar}
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
        <div className="rounded-panel border border-hairline bg-well p-6">
          <p className="text-sm text-fg-muted">Carregando…</p>
        </div>
      )}

      {colunas && (
        <div
          data-testid="operate-trend-chart"
          className="rounded-panel border border-hairline bg-well p-2"
        >
          <div className="flex justify-between px-1 text-xs text-fg-muted">
            <span>Histórico</span>
            {janelaDeslizante.aoVivo && (
              <span data-testid="operate-trend-secao-futura">Previsão</span>
            )}
          </div>
          <div ref={container} className="w-full" />
          {semPredicao && (
            <p
              data-testid="operate-trend-sem-predicao"
              className="mt-1 text-center text-xs text-fg-muted"
            >
              Sem predição — MPC fora de AUTO
            </p>
          )}
        </div>
      )}

      <LegendaOperacao
        defaults={defaults}
        ligadas={ligadas}
        porIdDefinicao={porIdDefinicao}
        cores={cores}
        foco={foco}
        focoEscala={focoEscala}
        onAlternarPena={alternarPena}
        onMudarEscalaFoco={mudarEscalaFoco}
      />

      {aviso && (
        <p role="alert" data-testid="operate-trend-aviso" className="text-xs text-warn">
          {aviso}
        </p>
      )}
    </div>
  );
}
