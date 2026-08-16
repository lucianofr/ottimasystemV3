import { expect, test } from "@playwright/test";

import { estaZoomadoEmX } from "./zoomX";

/**
 * `estaZoomadoEmX` é a regra que decide se o dado vivo pode re-ranger o eixo x ou se isso
 * apagaria o recorte que o usuário está olhando. Antes do motor de trend ela existia inline
 * dentro do efeito de dados do `TrendChart`, alcançável só por browser; aqui é pura.
 */

const X = [100, 110, 120, 130];

test("sem dado não há zoom a preservar", () => {
  expect(estaZoomadoEmX(0, 0, [])).toBe(false);
  expect(estaZoomadoEmX(undefined, undefined, [])).toBe(false);
});

test("escala cobrindo exatamente a extensão do dado não é zoom", () => {
  expect(estaZoomadoEmX(100, 130, X)).toBe(false);
});

test("escala mais larga que o dado não é zoom (janela com folga à direita)", () => {
  // A tela de operação range o eixo até o horizonte de predição, bem além do último ponto —
  // isso é a janela normal dela, não recorte do usuário.
  expect(estaZoomadoEmX(90, 200, X)).toBe(false);
});

test("recorte pela esquerda é zoom", () => {
  expect(estaZoomadoEmX(115, 130, X)).toBe(true);
});

test("recorte pela direita é zoom", () => {
  expect(estaZoomadoEmX(100, 125, X)).toBe(true);
});

test("escala ausente cai em 0 e conta como recorte à direita, nunca re-rangeando às cegas", () => {
  // `scales.x.min/max` são opcionais no uPlot; o fallback `0` mantém a decisão conservadora
  // (preserva o que está na tela) em vez de assumir "não está zoomado" e apagar o recorte.
  expect(estaZoomadoEmX(undefined, undefined, X)).toBe(true);
});
