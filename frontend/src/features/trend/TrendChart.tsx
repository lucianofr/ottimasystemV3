import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import type uPlot from "uplot";

import { useTema } from "../../lib/theme";
import { ESCALA_AUTO, construirEscalasUplot, type EscalaVar } from "./escalas";
import { useMotorTrend } from "./motorTrend";
import { pluginCursorIdx, pluginZoomX, type FaixaX } from "./plugins";
import { construirOpcoes, lerTemaTrend } from "./trendTheme";
import { faixaJanelaX } from "./useJanelaDeslizante";
import "./trend.css";

const ALTURA = 420;

/** Carimbo apontado pelo cursor: hora cheia, mesma leitura do trend de operação. */
const FORMATO_CARIMBO = new Intl.DateTimeFormat("pt-BR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export interface TrendChartProps {
  readonly dados: uPlot.AlignedData;
  /** Ids das penas, na ordem da seleção: número e ordem de séries são a estrutura do gráfico. */
  readonly ids: readonly number[];
  /** Um rótulo por pena, na ordem de `ids`. Texto exibido, nunca estrutura. */
  readonly rotulos: readonly string[];
  readonly janelaSegundos: number;
  /** Fim da janela (`useJanelaDeslizante`); `null` = ao vivo, e aí a vista segue o relógio. */
  readonly fimEpochS: number | null;
  /** Escala Y de cada tag (`./escalas`), chaveada pelo id da tag em texto. */
  readonly escalas: Readonly<Record<string, EscalaVar>>;
  /** Pena dona do único eixo Y desenhado; `null` = um eixo por pena (ver `construirOpcoes`). */
  readonly foco: number | null;
  /** Índice do carimbo sob o ponteiro, para a legenda da tela ler o valor de cada pena ali.
   *  `null` = ponteiro fora da área de plotagem. Ausente = a tela não mostra leitura no cursor. */
  readonly onCursorIdx?: (idx: number | null) => void;
}

/** Imperativo mínimo que `TrendPage` precisa da instância do uPlot (o motor é o dono dela):
 *  limpar o zoom no clique de "Reset layout" e LER a faixa visível de x, porque o export de CSV
 *  tem de recortar o arquivo no que está na tela, não na janela buscada. */
export interface TrendChartHandle {
  readonly resetZoom: () => void;
  /** Faixa de x visível quando há zoom aplicado; `null` sem zoom (a janela da tela manda). */
  readonly faixaX: () => FaixaX | null;
}

export const TrendChart = forwardRef<TrendChartHandle, TrendChartProps>(function TrendChart(
  { dados, ids, rotulos, janelaSegundos, fimEpochS, escalas, foco, onCursorIdx },
  handleRef,
) {
  const idsTexto = ids.map(String);
  // Escala manual ENTRA na estrutura: editá-la é ação deliberada e rara, e o próprio ajuste
  // de faixa já invalida qualquer zoom em andamento — não vale a pena imitar `setScale`
  // imperativo do uPlot só para preservar um recorte que a edição descartaria de qualquer jeito.
  const assinaturaEscalas = idsTexto
    .map((id) => {
      const escala = escalas[id] ?? ESCALA_AUTO;
      return `${id}:${escala.auto ? "a" : "m"}:${String(escala.min)}:${String(escala.max)}`;
    })
    .join(",");
  // O tema entra na estrutura: o uPlot pinta no canvas com as cores lidas na montagem, então
  // alternar claro/escuro só reflete no gráfico recriando a instância.
  const tema = useTema();
  const estrutura = `${tema}|${String(janelaSegundos)}|${idsTexto.join(",")}|${assinaturaEscalas}|${String(foco ?? "")}`;

  // Zoom por arrasto: estado para a tela avisar que a vista parou de seguir o relógio, e ref
  // porque o `range` do eixo x roda DENTRO do `setScale` do próprio arrasto — esperar o
  // re-render do React devolveria a janela velha e comeria o recorte. O ref também sobrevive à
  // recriação da instância (ligar pena, editar faixa, trocar tema).
  const [zoom, setZoom] = useState<FaixaX | null>(null);
  const zoomRef = useRef<FaixaX | null>(null);
  const aplicarZoom = useRef((faixa: FaixaX | null) => {
    zoomRef.current = faixa;
    setZoom(faixa);
  }).current;

  // Janela do eixo x (política pura com check próprio em `./useJanelaDeslizante`), reavaliada
  // a cada render com o relógio de parede — o `range` do uPlot lê deste ref.
  const rangeXRef = useRef<readonly [number, number]>([0, 0]);
  rangeXRef.current = faixaJanelaX(fimEpochS, janelaSegundos, Date.now() / 1000);

  // Leitura no cursor: o índice mora aqui (o carimbo é desenhado no cabeçalho do poço) e a
  // tela recebe o mesmo índice para traduzir em valor por pena, sem segundo caminho de dados.
  const [idxCursor, setIdxCursor] = useState<number | null>(null);
  const onCursorIdxRef = useRef(onCursorIdx);
  onCursorIdxRef.current = onCursorIdx;

  const motor = useMotorTrend({
    estrutura,
    altura: ALTURA,
    dados,
    // Os rótulos ficam fora da estrutura de propósito: `useTags()` resolve depois de
    // `useHistory()`, e trocar o fallback `String(id)` pelo nome real recriaria a instância —
    // e o zoom do engenheiro iria junto — sem que nada de estrutural tivesse mudado.
    montarOpcoes: (largura, altura) =>
      construirOpcoes({
        tema: lerTemaTrend(),
        rotulos,
        ids: idsTexto,
        escalas: construirEscalasUplot(
          idsTexto.map((id) => ({ id, escala: escalas[id] ?? ESCALA_AUTO })),
        ),
        janelaSegundos,
        largura,
        altura,
        foco: foco === null ? null : String(foco),
        rangeX: () => {
          const recorte = zoomRef.current;
          return recorte === null ? rangeXRef.current : [recorte.min, recorte.max];
        },
        plugins: [
          pluginZoomX((min, max) => {
            aplicarZoom({ min, max });
          }),
          pluginCursorIdx((idx) => {
            setIdxCursor(idx);
            onCursorIdxRef.current?.(idx);
          }),
        ],
        aoLimparZoom: () => {
          aplicarZoom(null);
        },
      }),
    // Com recorte ativo, dado novo entra sem re-ranger: o usuário está olhando um pedaço e a
    // vista não pode andar debaixo dele. O recorte é RASTREADO (não derivado das escalas da
    // instância) porque o `range` do eixo x roda dentro do `setScale` do próprio arrasto.
    deveRerange: () => zoomRef.current === null,
  });

  // A janela anda com o relógio de parede, não com a chegada de dado: sem o tique, com o WS
  // quieto por alguns segundos a borda direita congelava e o gráfico parecia travado. Trocar
  // de janela ou deslizar no tempo solta o recorte — ele era um pedaço da janela ANTERIOR.
  useEffect(() => {
    aplicarZoom(null);
    const aplicar = () => {
      const instancia = motor.instancia.current;
      if (instancia === null || zoomRef.current !== null) return;
      rangeXRef.current = faixaJanelaX(fimEpochS, janelaSegundos, Date.now() / 1000);
      instancia.setScale("x", { min: rangeXRef.current[0], max: rangeXRef.current[1] });
    };
    aplicar();
    // Vista congelada (janela deslizada): não há relógio a seguir.
    if (fimEpochS !== null) return;
    const id = window.setInterval(aplicar, 1000);
    return () => {
      window.clearInterval(id);
    };
  }, [fimEpochS, janelaSegundos, motor, aplicarZoom]);

  useImperativeHandle(
    handleRef,
    () => ({
      resetZoom: () => {
        aplicarZoom(null);
        motor.aplicarDadosComRerange();
      },
      faixaX: () => zoomRef.current,
    }),
    [motor, aplicarZoom],
  );

  const carimboCursor = idxCursor === null ? undefined : dados[0][idxCursor];

  return (
    <div className="space-y-2">
      <div
        data-testid="trend-chart"
        className="rounded-md border border-well-chart-border bg-well-chart p-3 shadow-sm"
      >
        {/* Altura fixa: a linha existe sempre, senão o gráfico pularia quando o ponteiro entra. */}
        <div className="flex h-4 justify-end px-1 text-xs text-well-chart-fg">
          {carimboCursor !== undefined && (
            <span data-testid="trend-cursor-hora" className="process-value">
              {FORMATO_CARIMBO.format(new Date(carimboCursor * 1000))}
            </span>
          )}
        </div>
        <div ref={motor.container} className="w-full" />
      </div>

      {/* Fora do poço: `text-warn-fg` é escuro por design (superfície clara) e sumiria contra o
          fundo do gráfico — dentro do poço só entra texto em `text-well-chart-fg`. */}
      {zoom !== null && (
        <p role="status" data-testid="trend-zoom" className="text-xs text-warn-fg">
          Zoom manual — a vista não segue o tempo. Duplo-clique ou Reset layout para voltar
        </p>
      )}
    </div>
  );
});
