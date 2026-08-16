import { expect, test } from "@playwright/test";
import { createElement, type ReactElement } from "react";

import { formatarValorLegenda, PainelLegendaTrend, type LinhaLegenda } from "./PainelLegendaTrend";

/**
 * Contrato do module de apresentação da legenda (ARCH-04, TD-024): valor+EU aparecem só
 * quando a linha fornece `valorEu` e somem quando omitido; o badge de qualidade aparece só
 * quando a linha fornece `badges`; cada linha mantém a própria identificação sem se fundir
 * com a vizinha. Sem jsdom no repo (`playwright.unit.config.ts` roda `.check.ts` puro, sem
 * navegador) — o teste chama o componente como função pura (não usa hooks, então é seguro
 * invocar direto) e varre a árvore de elementos React que ele devolve, em vez de montar DOM.
 */

interface NoTeste {
  readonly props?: { readonly children?: unknown; readonly [chave: string]: unknown };
}

function coletarPorTestId(no: unknown, alvo: Map<string, unknown>): Map<string, unknown> {
  if (no === null || no === undefined || typeof no !== "object") return alvo;
  if (Array.isArray(no)) {
    for (const item of no) coletarPorTestId(item, alvo);
    return alvo;
  }
  const props = (no as NoTeste).props;
  if (props === undefined) return alvo;
  const testId = props["data-testid"];
  if (typeof testId === "string") alvo.set(testId, props.children);
  coletarPorTestId(props.children, alvo);
  return alvo;
}

function linhaBase(overrides: Partial<LinhaLegenda> = {}): LinhaLegenda {
  return {
    chave: "l1",
    testId: "linha-item",
    className: "flex",
    identificacao: "identificacao-padrao",
    ...overrides,
  };
}

function renderizar(linhas: readonly LinhaLegenda[]): Map<string, unknown> {
  const arvore = PainelLegendaTrend({ testId: "painel", linhas }) as unknown as ReactElement;
  return coletarPorTestId(arvore, new Map());
}

test("formatarValorLegenda: número em pt-BR (Regra do Número Tabular), null vira travessão", () => {
  expect(formatarValorLegenda(1234.5)).toBe("1.234,5");
  expect(formatarValorLegenda(0)).toBe("0");
  expect(formatarValorLegenda(null)).toBe("—");
});

test("valor+EU aparecem quando a linha fornece valorEu", () => {
  const nos = renderizar([
    linhaBase({
      valorEu: { valor: 12.5, eu: "°C", muted: false, testIdValor: "v", testIdEu: "e" },
    }),
  ]);
  expect(nos.get("v")).toBe("12,5");
  expect(nos.get("e")).toBe("°C");
});

test("valor+EU somem quando a linha omite valorEu", () => {
  const nos = renderizar([linhaBase()]);
  expect(nos.has("v")).toBe(false);
  expect(nos.has("e")).toBe(false);
});

test("badge de qualidade aparece só quando a linha fornece badges, com o texto certo", () => {
  const comBadge = renderizar([
    linhaBase({ badges: [{ testId: "b1", texto: "BAD", className: "warn" }] }),
  ]);
  expect(comBadge.get("b1")).toBe("BAD");

  const semBadge = renderizar([linhaBase()]);
  expect(semBadge.has("b1")).toBe(false);
});

test("cada linha preserva a própria identificação, sem fundir com a vizinha", () => {
  const nos = renderizar([
    linhaBase({
      chave: "a",
      testId: "linha-a",
      identificacao: createElement("span", { "data-testid": "ident-a" }, "A"),
    }),
    linhaBase({
      chave: "b",
      testId: "linha-b",
      identificacao: createElement("span", { "data-testid": "ident-b" }, "B"),
    }),
  ]);
  expect(nos.get("ident-a")).toBe("A");
  expect(nos.get("ident-b")).toBe("B");
});

test("filho de editor de escala aparece só quando a linha fornece filhoEscala", () => {
  const comEscala = renderizar([
    linhaBase({ filhoEscala: createElement("span", { "data-testid": "escala-x" }, "escala") }),
  ]);
  expect(comEscala.has("escala-x")).toBe(true);

  const semEscala = renderizar([linhaBase()]);
  expect(semEscala.has("escala-x")).toBe(false);
});
