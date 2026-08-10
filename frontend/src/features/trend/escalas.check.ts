import { expect, test } from "@playwright/test";

import {
  chaveEscala,
  construirEscalasUplot,
  ESCALA_AUTO,
  gravarEscalas,
  lerEscalas,
  type EscalaVar,
} from "./escalas";

/**
 * `escalas.ts` — escala Y por variável, compartilhada pelos dois trends.
 *
 * Funções puras + as duas de armazenamento. `localStorage` não existe no Node puro deste
 * runner (`playwright.unit.config.ts` não carrega jsdom): o stub abaixo é o mínimo de
 * "browser" necessário, no mesmo molde de `lib/api.check.ts`.
 */

type LocalStorageMinimo = {
  getItem: (chave: string) => string | null;
  setItem: (chave: string, valor: string) => void;
  removeItem: (chave: string) => void;
};

const navegadorFalso = globalThis as unknown as { localStorage: LocalStorageMinimo };

const CHAVE = "ottima.teste.escalas.v1";

test.beforeEach(() => {
  const armazenamento = new Map<string, string>();
  navegadorFalso.localStorage = {
    getItem: (chave) => armazenamento.get(chave) ?? null,
    setItem: (chave, valor) => {
      armazenamento.set(chave, valor);
    },
    removeItem: (chave) => {
      armazenamento.delete(chave);
    },
  };
});

const MANUAL: EscalaVar = { auto: false, min: 0, max: 100 };

test("chaveEscala prefixa com 'v' para não colidir com as escalas x/y do uPlot", () => {
  expect(chaveEscala("cv_1")).toBe("vcv_1");
  expect(chaveEscala("12")).toBe("v12");
});

test("construirEscalasUplot: variável em auto vira escala com autoscale", () => {
  const { scales, scaleKeyPorVar } = construirEscalasUplot([{ id: "cv_1", escala: ESCALA_AUTO }]);
  expect(scaleKeyPorVar.get("cv_1")).toBe("vcv_1");
  expect(scales["vcv_1"]).toEqual({ auto: true });
});

test("construirEscalasUplot: faixa manual completa vira range fixo", () => {
  const { scales } = construirEscalasUplot([{ id: "cv_1", escala: MANUAL }]);
  expect(scales["vcv_1"]).toEqual({ auto: false, range: [0, 100] });
});

test("construirEscalasUplot: cada variável ganha uma escala independente", () => {
  const { scales } = construirEscalasUplot([
    { id: "cv_1", escala: MANUAL },
    { id: "mv_1", escala: ESCALA_AUTO },
  ]);
  expect(Object.keys(scales).sort()).toEqual(["vcv_1", "vmv_1"]);
  expect(scales["vmv_1"]).toEqual({ auto: true });
});

test("construirEscalasUplot: faixa meio preenchida cai para autoscale", () => {
  const { scales } = construirEscalasUplot([
    { id: "cv_1", escala: { auto: false, min: 10, max: null } },
    { id: "cv_2", escala: { auto: false, min: null, max: 90 } },
  ]);
  expect(scales["vcv_1"]).toEqual({ auto: true });
  expect(scales["vcv_2"]).toEqual({ auto: true });
});

test("construirEscalasUplot: faixa invertida ou degenerada cai para autoscale", () => {
  const { scales } = construirEscalasUplot([
    { id: "cv_1", escala: { auto: false, min: 100, max: 0 } },
    { id: "cv_2", escala: { auto: false, min: 50, max: 50 } },
  ]);
  expect(scales["vcv_1"]).toEqual({ auto: true });
  expect(scales["vcv_2"]).toEqual({ auto: true });
});

test("construirEscalasUplot: faixa manual com mínimo negativo é honrada", () => {
  const { scales } = construirEscalasUplot([
    { id: "cv_1", escala: { auto: false, min: -20, max: -5 } },
  ]);
  expect(scales["vcv_1"]).toEqual({ auto: false, range: [-20, -5] });
});

test("gravar e ler devolve as mesmas escalas", () => {
  gravarEscalas(CHAVE, { cv_1: MANUAL, mv_1: ESCALA_AUTO });
  expect(lerEscalas(CHAVE)).toEqual({ cv_1: MANUAL, mv_1: ESCALA_AUTO });
});

test("lerEscalas: chave ausente devolve mapa vazio", () => {
  expect(lerEscalas(CHAVE)).toEqual({});
});

test("lerEscalas: JSON corrompido devolve mapa vazio em vez de estourar", () => {
  navegadorFalso.localStorage.setItem(CHAVE, "{isto não é json");
  expect(lerEscalas(CHAVE)).toEqual({});
});

test("lerEscalas: JSON válido que não é objeto devolve mapa vazio", () => {
  navegadorFalso.localStorage.setItem(CHAVE, "[1, 2, 3]");
  expect(lerEscalas(CHAVE)).toEqual({});
});

test("lerEscalas: entrada fora de forma é descartada sem derrubar as vizinhas", () => {
  navegadorFalso.localStorage.setItem(
    CHAVE,
    JSON.stringify({
      cv_1: MANUAL,
      cv_2: { auto: "sim", min: 0, max: 1 },
      cv_3: { auto: false, min: "0", max: 1 },
      cv_4: null,
    }),
  );
  expect(lerEscalas(CHAVE)).toEqual({ cv_1: MANUAL });
});

test("lerEscalas: NaN e Infinity não passam por número válido", () => {
  navegadorFalso.localStorage.setItem(CHAVE, '{"cv_1": {"auto": false, "min": null, "max": 1e999}}');
  expect(lerEscalas(CHAVE)).toEqual({});
});
