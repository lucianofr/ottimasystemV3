/**
 * Checks puros do heatmap de superficie (SPEC_FUZZY §5/§8): a escala de cor e o
 * posicionamento do ponto de operacao na grade.
 *
 * Vale um teste porque errar aqui e silencioso: um heatmap bonito com o ponto no lugar
 * errado leva o operador a concluir a coisa errada sobre a malha.
 */

import { expect, test } from "@playwright/test";

import { celula, cor } from "./HeatmapSuperficie";

test("regiao sem regra e cinza, nunca cor de valor", () => {
  expect(cor(null)).toEqual([64, 64, 64]);
  // cinza nao pode colidir com o branco do zero nem com as pontas
  expect(cor(0)).toEqual([255, 255, 255]);
});

test("escala de cor: azul no negativo, branco no zero, vermelho no positivo", () => {
  const [r1, g1, b1] = cor(-1);
  expect([r1, g1, b1]).toEqual([0, 0, 255]);
  const [r2, g2, b2] = cor(1);
  expect([r2, g2, b2]).toEqual([255, 0, 0]);
  expect(cor(0.5)).toEqual([255, 128, 128]);
});

test("valor fora de [-1,1] satura em vez de estourar o canal de cor", () => {
  expect(cor(7)).toEqual(cor(1));
  expect(cor(-7)).toEqual(cor(-1));
});

test("celula mapeia [-1,1] nas bordas e no centro exato da grade", () => {
  expect(celula(-1, 65)).toBe(0);
  expect(celula(0, 65)).toBe(32);
  expect(celula(1, 65)).toBe(64);
});

test("celula satura fora da faixa: indice nunca sai da grade", () => {
  expect(celula(-3, 65)).toBe(0);
  expect(celula(3, 65)).toBe(64);
});
