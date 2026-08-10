import { expect, test } from "@playwright/test";

import { chaveEscala } from "./escalas";
import { montarEixosValor } from "./trendTheme";

/**
 * `trendTheme.ts::montarEixosValor` — um eixo Y por tag (Fase 4.1). O que precisa de prova:
 * a chave de escala de cada eixo, o módulo de cor quando há mais tags que penas cadastradas,
 * e a grade aparecendo só no primeiro eixo (senão escalas independentes empilhadas desenham
 * grades cruzadas sem relação nenhuma entre si).
 */

test("um eixo por tag, na chave de escala e na cor da pena correspondente", () => {
  const scaleKeyPorVar = new Map([
    ["10", chaveEscala("10")],
    ["20", chaveEscala("20")],
  ]);
  const eixos = montarEixosValor(["10", "20"], ["#111", "#222", "#333"], scaleKeyPorVar);
  expect(eixos).toEqual([
    { scale: "v10", stroke: "#111", grid: true },
    { scale: "v20", stroke: "#222", grid: false },
  ]);
});

test("cor da pena repete em módulo quando há mais tags que penas cadastradas", () => {
  const scaleKeyPorVar = new Map([
    ["1", chaveEscala("1")],
    ["2", chaveEscala("2")],
    ["3", chaveEscala("3")],
  ]);
  const eixos = montarEixosValor(["1", "2", "3"], ["#a", "#b"], scaleKeyPorVar);
  expect(eixos.map((eixo) => eixo.stroke)).toEqual(["#a", "#b", "#a"]);
});

test("grade só aparece no primeiro eixo", () => {
  const scaleKeyPorVar = new Map([
    ["1", chaveEscala("1")],
    ["2", chaveEscala("2")],
  ]);
  const eixos = montarEixosValor(["1", "2"], ["#a"], scaleKeyPorVar);
  expect(eixos.map((eixo) => eixo.grid)).toEqual([true, false]);
});

test("chave de escala cai no fallback chaveEscala quando o mapa não tem a variável", () => {
  const eixos = montarEixosValor(["5"], ["#a"], new Map());
  expect(eixos[0].scale).toBe(chaveEscala("5"));
});
