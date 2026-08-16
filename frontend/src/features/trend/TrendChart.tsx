import { forwardRef, useImperativeHandle } from "react";
import type uPlot from "uplot";

import { useTema } from "../../lib/theme";
import { ESCALA_AUTO, construirEscalasUplot, type EscalaVar } from "./escalas";
import { useMotorTrend } from "./motorTrend";
import { construirOpcoes, lerTemaTrend } from "./trendTheme";
import "./trend.css";
import { estaZoomadoEmX } from "./zoomX";

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

/** Imperativo mínimo para o botão "Reset layout" do header: o motor detém a instância do
 *  uPlot, `TrendPage` só precisa limpar o zoom no mesmo clique que volta ao vivo. */
export interface TrendChartHandle {
  readonly resetZoom: () => void;
}

export const TrendChart = forwardRef<TrendChartHandle, TrendChartProps>(function TrendChart(
  { dados, ids, rotulos, janelaSegundos, escalas },
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
  const estrutura = `${tema}|${String(janelaSegundos)}|${idsTexto.join(",")}|${assinaturaEscalas}`;

  // Os rótulos ficam fora da estrutura de propósito: `useTags()` resolve depois de
  // `useHistory()`, e trocar o fallback `String(id)` pelo nome real recriaria a instância —
  // e o zoom do engenheiro iria junto — sem que nada de estrutural tivesse mudado.
  const motor = useMotorTrend({
    estrutura,
    altura: ALTURA,
    dados,
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
      }),
    // Tela de engenharia: o zoom é DERIVADO das escalas da instância (não há arrasto próprio
    // rastreado como na tela de operação), então a extensão do dado é a referência.
    deveRerange: (instancia) =>
      !estaZoomadoEmX(instancia.scales.x.min, instancia.scales.x.max, instancia.data[0]),
  });

  useImperativeHandle(handleRef, () => ({ resetZoom: motor.aplicarDadosComRerange }), [motor]);

  return (
    <div
      data-testid="trend-chart"
      className="rounded-md border border-well-chart-border bg-well-chart p-3 shadow-sm"
    >
      <div ref={motor.container} className="w-full" />
    </div>
  );
});
