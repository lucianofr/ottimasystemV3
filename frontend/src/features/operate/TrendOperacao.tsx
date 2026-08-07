import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import { Select } from "../../components/ui/select";
import type { MpcState } from "../../lib/contracts.gen";
import { FORMATO_VALOR, lerTemaTrend, type TemaTrend } from "../trend/trendTheme";
import "../trend/trend.css";
import {
  JANELAS_OPERACAO,
  JANELA_PADRAO_ID,
  OPCOES_DEGRAU_MV,
  dividirSpPorAuto,
  mesclarSeriesVivas,
  montarOverlayPrevisao,
  type AmostraViva,
  type JanelaOperacao,
  type OverlayPrevisao,
  type SerieOperacao,
} from "./trendOperacao";
import { useHistoryMpc } from "./useHistoryMpc";
import type { MpcNodeOut } from "./useMpcs";

/**
 * Trend central com predição (spec F5 §7.4-6; plano F5b tarefas 5.1-5.3). uPlot re-vestido
 * no molde de `features/trend/TrendChart.tsx`/`trendTheme.ts`: mesma separação entre
 * "estrutura" (recriada só quando a janela ou o conjunto de variáveis muda) e "dados ao vivo"
 * (aplicados via `setData`, sem recriar a instância — o zoom do operador sobrevive ao poll e
 * à borda viva). Este arquivo faz a montagem visual; `trendOperacao.ts` guarda a lógica pura
 * testada em `trendOperacao.check.ts` (regra global 3: asserts leem dados, nunca pixel).
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
 *  `setData` sem recriar a instância (mesma separação estrutura/dados do resto do arquivo). */
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

// ----------------------------------------------------------------------------------------
// Montagem das colunas do uPlot (eixo x único, união de histórico + horizonte da predição —
// é isso que dimensiona "o eixo futuro por Np×Ts_mpc": o próprio último ponto de `tAbs`).
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
  let corIndice = 0;

  function pushSerie(
    t: readonly number[],
    valores: readonly (number | null)[],
    opts: Omit<uPlot.Series, "label"> & { label: string },
  ): number {
    dados.push(remapear(t, valores));
    series.push(opts);
    return series.length - 1;
  }

  // CVs (PV + SP) — linhas = CVs na ordem do config, depois Restrições (spec F4 §5.1/F5 §3.2).
  mpc.variables.cvs.forEach((cv, indiceLinha) => {
    const historica = porId.get(cv.id) ?? SERIE_VAZIA(cv.id);
    const cor = tema.penas[corIndice % tema.penas.length];
    corIndice++;
    pushSerie(historica.t, historica.v, {
      label: `${cv.name} PV`,
      stroke: cor,
      width: 1.5,
      spanGaps: false,
      points: { show: false },
    });
    pushSerie(overlay.tAbs, overlay.cv[indiceLinha] ?? [], {
      label: `${cv.name} previsto`,
      stroke: tracoComFade(cor, overlay.agora),
      width: 1.5,
      dash: [4, 3],
      points: { show: false },
    });
    const divisao = dividirSpPorAuto(historica.sp, historica.auto);
    pushSerie(historica.t, divisao.comandado, {
      label: `${cv.name} SP`,
      stroke: tema.accent,
      width: 1.5,
      points: { show: false },
    });
    pushSerie(historica.t, divisao.rastreado, {
      label: `${cv.name} SP rastreado`,
      stroke: corDessaturada(tema.accent),
      width: 1.5,
      points: { show: false },
    });
  });

  // Restrições — banda low/high sombreada no Poço; a pena de PV conta no teto (brief 5.3), a
  // banda em si não é uma pena adicional.
  mpc.variables.constraints.forEach((restricao, indiceRestricao) => {
    const indiceLinha = mpc.variables.cvs.length + indiceRestricao;
    const historica = porId.get(restricao.id) ?? SERIE_VAZIA(restricao.id);
    const cor = tema.penas[corIndice % tema.penas.length];
    corIndice++;
    pushSerie(historica.t, historica.v, {
      label: `${restricao.name} PV`,
      stroke: cor,
      width: 1.5,
      spanGaps: false,
      points: { show: false },
    });
    pushSerie(overlay.tAbs, overlay.cv[indiceLinha] ?? [], {
      label: `${restricao.name} previsto`,
      stroke: tracoComFade(cor, overlay.agora),
      width: 1.5,
      dash: [4, 3],
      points: { show: false },
    });
    const idxLow = pushSerie(
      eixoX,
      eixoX.map(() => restricao.range.low),
      { label: `${restricao.name} mín.`, stroke: "transparent", width: 0, points: { show: false } },
    );
    const idxHigh = pushSerie(
      eixoX,
      eixoX.map(() => restricao.range.high),
      { label: `${restricao.name} máx.`, stroke: "transparent", width: 0, points: { show: false } },
    );
    bands.push({ series: [idxLow, idxHigh], fill: corBanda(tema.poco), dir: -1 });
  });

  // MVs — degrau fantasma stepped align:-1 (§3.3; `OPCOES_DEGRAU_MV` é a única fonte do
  // `align`, nunca `+1`).
  mpc.variables.mvs.forEach((mv, indiceMv) => {
    const historica = porId.get(mv.id) ?? SERIE_VAZIA(mv.id);
    const cor = tema.penas[corIndice % tema.penas.length];
    corIndice++;
    pushSerie(historica.t, historica.v, {
      label: `${mv.name} PV`,
      stroke: cor,
      width: 1.5,
      spanGaps: false,
      points: { show: false },
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
    });
  });

  return { dados: [eixoX, ...dados] as uPlot.AlignedData, series, bands };
}

function construirOpcoesOperacao(
  colunas: ColunasOperacao,
  tema: TemaTrend,
  largura: number,
  altura: number,
  agoraRef: { current: number | null },
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
    plugins: [pluginLinhaAgora(agoraRef, tema)],
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
        stroke: tema.texto,
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

  const idsHistorico = useMemo(
    () => [
      ...mpc.variables.cvs.map((cv) => cv.id),
      ...mpc.variables.constraints.map((c) => c.id),
      ...mpc.variables.mvs.map((mv) => mv.id),
    ],
    [mpc],
  );

  const historico = useHistoryMpc(flowId, blockId, idsHistorico, janela.segundos);

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

  const seriesMescladas = useMemo(() => {
    if (!historico.data) return null;
    const corte = Date.now() / 1000 - janela.segundos;
    const vivasNaJanela = vivas.filter((a) => Date.parse(a.ts) / 1000 >= corte);
    return mesclarSeriesVivas(historico.data, vivasNaJanela, idsHistorico);
  }, [historico.data, vivas, janela.segundos, idsHistorico]);

  const overlay = useMemo(
    () => (mpcState ? montarOverlayPrevisao(mpcState.prediction) : OVERLAY_VAZIO),
    [mpcState],
  );

  const tema = useMemo(() => lerTemaTrend(), []);

  const colunas = useMemo(
    () => (seriesMescladas ? montarColunas(mpc, seriesMescladas, overlay, tema) : null),
    [mpc, seriesMescladas, overlay, tema],
  );

  const container = useRef<HTMLDivElement>(null);
  const grafico = useRef<uPlot | null>(null);
  const agoraRef = useRef<number | null>(null);
  agoraRef.current = overlay.agora;
  const colunasAtuais = useRef(colunas);
  colunasAtuais.current = colunas;

  const estrutura = `${janela.id}|${idsHistorico.join(",")}`;

  useEffect(() => {
    const alvo = container.current;
    const atuais = colunasAtuais.current;
    if (!alvo || !atuais) return;
    const instancia = new uPlot(
      construirOpcoesOperacao(atuais, tema, alvo.clientWidth, ALTURA, agoraRef),
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

  return (
    <div data-testid="operate-trend" className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="plaqueta text-xs text-fg-muted">Trend</h2>
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
          <div ref={container} className="w-full" />
        </div>
      )}
    </div>
  );
}
