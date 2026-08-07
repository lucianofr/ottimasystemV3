import { expect, test } from "@playwright/test";

import { clampNaFaixa, dentroDaFaixa } from "./clamp";

/**
 * `clampNaFaixa`/`dentroDaFaixa` — tarefa 4.4 do plano F5b (spec F5 §7.4-5; RF-702/704).
 * Espelho leve do clamp client-side em `limits` (MV) / `sp_limits` (CV) — o servidor
 * permanece a barreira real (RF-704); aqui só evita round-trip óbvio pro operador. Funções
 * puras, sem I/O: dentro/fora/borda cobertos nos dois lados da faixa.
 */

const FAIXA = { min: 10, max: 90 };

test("dentroDaFaixa: valor estritamente dentro é true", () => {
  expect(dentroDaFaixa(50, FAIXA)).toBe(true);
});

test("dentroDaFaixa: valor abaixo do mínimo é false", () => {
  expect(dentroDaFaixa(9.9, FAIXA)).toBe(false);
});

test("dentroDaFaixa: valor acima do máximo é false", () => {
  expect(dentroDaFaixa(90.1, FAIXA)).toBe(false);
});

test("dentroDaFaixa: borda inferior (== min) é true", () => {
  expect(dentroDaFaixa(10, FAIXA)).toBe(true);
});

test("dentroDaFaixa: borda superior (== max) é true", () => {
  expect(dentroDaFaixa(90, FAIXA)).toBe(true);
});

test("clampNaFaixa: valor dentro passa inalterado", () => {
  expect(clampNaFaixa(50, FAIXA)).toBe(50);
});

test("clampNaFaixa: valor abaixo do mínimo é elevado ao mínimo", () => {
  expect(clampNaFaixa(-5, FAIXA)).toBe(10);
});

test("clampNaFaixa: valor acima do máximo é reduzido ao máximo", () => {
  expect(clampNaFaixa(1000, FAIXA)).toBe(90);
});

test("clampNaFaixa: borda inferior (== min) passa inalterada", () => {
  expect(clampNaFaixa(10, FAIXA)).toBe(10);
});

test("clampNaFaixa: borda superior (== max) passa inalterada", () => {
  expect(clampNaFaixa(90, FAIXA)).toBe(90);
});
