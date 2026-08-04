import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import { construirOpcoes, lerTemaTrend } from "./trendTheme";
import "./trend.css";

const ALTURA = 420;

export interface TrendChartProps {
  readonly dados: uPlot.AlignedData;
  /** Um rótulo por pena, na ordem da seleção. Mudar a lista muda a estrutura do gráfico. */
  readonly rotulos: readonly string[];
  readonly janelaSegundos: number;
}

export function TrendChart({ dados, rotulos, janelaSegundos }: TrendChartProps) {
  const container = useRef<HTMLDivElement>(null);
  const grafico = useRef<uPlot | null>(null);
  // O efeito de criação só pode depender da estrutura; os dados vivos entram por ref para
  // não recriar o gráfico a cada polling (pisca e perde o zoom).
  const ultimosDados = useRef(dados);
  ultimosDados.current = dados;
  const estrutura = `${String(janelaSegundos)}|${rotulos.join("\u0000")}`;
  const estruturaAtual = useRef({ rotulos, janelaSegundos });
  estruturaAtual.current = { rotulos, janelaSegundos };

  useEffect(() => {
    const alvo = container.current;
    if (!alvo) return;
    const instancia = new uPlot(
      construirOpcoes({
        tema: lerTemaTrend(),
        rotulos: estruturaAtual.current.rotulos,
        janelaSegundos: estruturaAtual.current.janelaSegundos,
        largura: alvo.clientWidth,
        altura: ALTURA,
      }),
      ultimosDados.current,
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
  }, [estrutura]);

  useEffect(() => {
    const instancia = grafico.current;
    if (!instancia) return;
    // Enquanto o engenheiro está com zoom aplicado, seguir o dado vivo apagaria o recorte.
    const x = instancia.data[0];
    const zoomado =
      x.length > 0 &&
      ((instancia.scales.x.min ?? 0) > x[0] || (instancia.scales.x.max ?? 0) < x[x.length - 1]);
    instancia.setData(dados, !zoomado);
  }, [dados]);

  return (
    <div data-testid="trend-chart" className="rounded-panel border border-hairline bg-well p-2">
      <div ref={container} className="w-full" />
    </div>
  );
}
