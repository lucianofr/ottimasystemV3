import type uPlot from "uplot";

/**
 * Plugins de interação compartilhados pelas telas de tendência (ADR-030: as três telas reusam
 * a mesma máquina, não reimplementam). Nasceram dentro de `../operate/TrendOperacao.tsx` e
 * subiram para cá quando o trend de engenharia (`TrendChart.tsx`) passou a ter a mesma
 * interação — zoom por arrasto rastreado fora da instância e leitura no carimbo sob o ponteiro.
 *
 * Os dois publicam NÚMEROS, nunca a forma do estado do consumidor: a tela de operação guarda o
 * recorte numa tupla (`[min, max]`, o que o `range` do eixo x dela devolve direto) e a de
 * engenharia num objeto (`FaixaX`, o que o recorte do CSV consome). O plugin não tem opinião
 * sobre isso.
 *
 * Só DOM/canvas mora aqui — nenhum teste unitário (regra global 3: asserts leem dados, nunca
 * pixel). A prova destes dois é de browser (roteiro Playwright das telas).
 */

/** Faixa do eixo x: extremos em segundos de época. O gráfico produz (faixa visível, quando há
 *  zoom) e o export de CSV consome (recorte do arquivo). */
export interface FaixaX {
  readonly min: number;
  readonly max: number;
}

/**
 * Zoom manual em X (arrasto sobre o gráfico).
 *
 * As telas de trend têm `range` PRÓPRIO no eixo x (a janela é a escolhida no seletor, não a
 * extensão do dado), e o uPlot chama esse `range` também no zoom por arrasto — devolver a
 * janela da tela ali engole o recorte pedido. O `setSelect` dispara ANTES do `setScale` do zoom
 * (uPlot `mouseUp`), então guardar o recorte aqui faz o `range` já responder com ele.
 *
 * Quem consome guarda o recorte em ref (não dentro da instância) para ele sobreviver à
 * recriação do gráfico — trocar o eixo Y, ligar/desligar pena, editar faixa.
 */
export function pluginZoomX(aoRecortar: (min: number, max: number) => void): uPlot.Plugin {
  return {
    hooks: {
      setSelect: (u: uPlot) => {
        if (u.select.width <= 0) return;
        aoRecortar(u.posToVal(u.select.left, "x"), u.posToVal(u.select.left + u.select.width, "x"));
      },
    },
  };
}

/** Leitura no cursor (hover): publica o índice do carimbo sob o ponteiro. O uPlot já resolve o
 *  ponto mais próximo (`cursor.idx`, `null` fora da área de plotagem) — aqui só se filtra a
 *  repetição, senão cada pixel de mousemove viraria um `setState` e um re-render da legenda
 *  inteira. Quem traduz índice em valor por pena é a tela. */
export function pluginCursorIdx(aoMover: (idx: number | null) => void): uPlot.Plugin {
  let ultimo: number | null = null;
  return {
    hooks: {
      setCursor: (u: uPlot) => {
        const idx = u.cursor.idx ?? null;
        if (idx === ultimo) return;
        ultimo = idx;
        aoMover(idx);
      },
    },
  };
}
