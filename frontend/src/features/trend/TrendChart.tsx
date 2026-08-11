import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import { useTema } from "../../lib/theme";
import { ESCALA_AUTO, construirEscalasUplot, type EscalaVar } from "./escalas";
import { construirOpcoes, lerTemaTrend } from "./trendTheme";
import "./trend.css";

const ALTURA = 420;

export interface TrendChartProps {
  readonly dados: uPlot.AlignedData;
  /** Ids das penas, na ordem da seleção: número e ordem de séries são a estrutura do gráfico. */
  readonly ids: readonly number[];
  /** Um rótulo por pena, na ordem de `ids`. Texto exibido, nunca estrutura. */
  readonly rotulos: readonly string[];
  readonly janelaSegundos: number;
  /** Escala Y de cada tag (`./escalas`), chaveada pelo id da tag em texto. */
  readonly escalas: Readonly<Record<string, EscalaVar>>;
}

/** Imperativo mínimo para o botão "Reset layout" do header: `TrendChart` detém a instância
 *  do uPlot, `TrendPage` só precisa limpar o zoom no mesmo clique que volta ao vivo. */
export interface TrendChartHandle {
  readonly resetZoom: () => void;
}

export const TrendChart = forwardRef<TrendChartHandle, TrendChartProps>(function TrendChart(
  { dados, ids, rotulos, janelaSegundos, escalas },
  handleRef,
) {
  const container = useRef<HTMLDivElement>(null);
  const grafico = useRef<uPlot | null>(null);
  // O efeito de criação só pode depender da estrutura; os dados vivos entram por ref para
  // não recriar o gráfico a cada polling (pisca e perde o zoom).
  const ultimosDados = useRef(dados);
  ultimosDados.current = dados;
  const idsTexto = ids.map(String);
  // Os rótulos ficam fora da estrutura de propósito: `useTags()` resolve depois de
  // `useHistory()`, e trocar o fallback `String(id)` pelo nome real recriaria a instância —
  // e o zoom do engenheiro iria junto — sem que nada de estrutural tivesse mudado.
  const estruturaAtual = useRef({ rotulos, janelaSegundos, idsTexto, escalas });
  estruturaAtual.current = { rotulos, janelaSegundos, idsTexto, escalas };
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
  const estrutura = `${tema}|${String(janelaSegundos)}|${idsTexto.join(",")}|${assinaturaEscalas}`;

  useImperativeHandle(
    handleRef,
    () => ({
      resetZoom: () => {
        grafico.current?.setData(ultimosDados.current, true);
      },
    }),
    [],
  );

  useEffect(() => {
    const alvo = container.current;
    if (!alvo) return;
    const atual = estruturaAtual.current;
    const escalasUplot = construirEscalasUplot(
      atual.idsTexto.map((id) => ({ id, escala: atual.escalas[id] ?? ESCALA_AUTO })),
    );
    const instancia = new uPlot(
      construirOpcoes({
        tema: lerTemaTrend(),
        rotulos: atual.rotulos,
        ids: atual.idsTexto,
        escalas: escalasUplot,
        janelaSegundos: atual.janelaSegundos,
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
    <div
      data-testid="trend-chart"
      className="rounded-lg border border-border bg-surface p-3 shadow-sm"
    >
      <div ref={container} className="w-full" />
    </div>
  );
});
