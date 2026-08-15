import { expect, test } from "@playwright/test";

import {
  agregar,
  ALTURA_VIEWBOX,
  implicar,
  LARGURA_VIEWBOX,
  normaAgregacaoSuportada,
  normaImplicacaoSuportada,
  pontosArea,
  pontosPolilinha,
  rodapeMuDeX,
  rodapeYChapeu,
  silhuetaAgregada,
  tresCasas,
  xDoMarcador,
  xParaSvg,
  yParaSvg,
} from "./fuzzyMath";

/**
 * `fuzzyMath.ts` — lógica pura da FUZZY OPERATE (ADR-030): normas de implicação/agregação
 * da silhueta agregada de saída, geometria de escala do SVG (`PainelVariavelFuzzy.tsx`) e
 * montagem dos rodapés `μ(x)`/`ŷ`. Funções puras, sem I/O: mesmo padrão de `clamp.check.ts`.
 */

// ----------------------------------------------------------------------------------------
// Normas de implicação
// ----------------------------------------------------------------------------------------

test("implicar Minimum recorta (clip) no menor entre grau e y", () => {
  expect(implicar("Minimum", 0.6, 0.9)).toBe(0.6);
  expect(implicar("Minimum", 0.6, 0.3)).toBe(0.3);
});

test("implicar AlgebraicProduct escala y pelo grau", () => {
  expect(implicar("AlgebraicProduct", 0.5, 0.8)).toBeCloseTo(0.4);
});

test("normaImplicacaoSuportada: Minimum e AlgebraicProduct são suportadas, o resto não", () => {
  expect(normaImplicacaoSuportada("Minimum")).toBe(true);
  expect(normaImplicacaoSuportada("AlgebraicProduct")).toBe(true);
  expect(normaImplicacaoSuportada("Einstein")).toBe(false);
  expect(normaImplicacaoSuportada(null)).toBe(false);
});

// ----------------------------------------------------------------------------------------
// Normas de agregação
// ----------------------------------------------------------------------------------------

test("agregar Maximum devolve o maior dos dois pontos", () => {
  expect(agregar("Maximum", 0.3, 0.7)).toBe(0.7);
});

test("agregar AlgebraicSum: a + b - a*b", () => {
  expect(agregar("AlgebraicSum", 0.5, 0.5)).toBeCloseTo(0.75);
});

test("agregar BoundedSum: satura em 1", () => {
  expect(agregar("BoundedSum", 0.7, 0.7)).toBe(1);
  expect(agregar("BoundedSum", 0.2, 0.3)).toBeCloseTo(0.5);
});

test("agregar UnboundedSum: soma crua, sem teto", () => {
  expect(agregar("UnboundedSum", 0.7, 0.7)).toBeCloseTo(1.4);
});

test("normaAgregacaoSuportada: as 4 normas suportadas passam, 'none' e desconhecida não", () => {
  expect(normaAgregacaoSuportada("Maximum")).toBe(true);
  expect(normaAgregacaoSuportada("AlgebraicSum")).toBe(true);
  expect(normaAgregacaoSuportada("BoundedSum")).toBe(true);
  expect(normaAgregacaoSuportada("UnboundedSum")).toBe(true);
  expect(normaAgregacaoSuportada("none")).toBe(false);
  expect(normaAgregacaoSuportada(null)).toBe(false);
});

// ----------------------------------------------------------------------------------------
// Silhueta agregada
// ----------------------------------------------------------------------------------------

test("silhuetaAgregada: Minimum + Maximum combina dois termos recortados ponto a ponto", () => {
  const termos = [
    { y: [0, 1, 0], grau: 0.5 },
    { y: [0, 0.4, 1], grau: 0.3 },
  ];
  // recortado termo 1: [0, 0.5, 0]; termo 2: [0, 0.3, 0.3]; Maximum ponto a ponto: [0, 0.5, 0.3]
  expect(silhuetaAgregada(termos, "Minimum", "Maximum", 3)).toEqual([0, 0.5, 0.3]);
});

test("silhuetaAgregada: norma de implicação não suportada devolve null (sem silhueta)", () => {
  const termos = [{ y: [0, 1, 0], grau: 0.5 }];
  expect(silhuetaAgregada(termos, "Einstein", "Maximum", 3)).toBeNull();
});

test("silhuetaAgregada: aggregation 'none' devolve null (sem silhueta)", () => {
  const termos = [{ y: [0, 1, 0], grau: 0.5 }];
  expect(silhuetaAgregada(termos, "Minimum", "none", 3)).toBeNull();
  expect(silhuetaAgregada(termos, "Minimum", null, 3)).toBeNull();
});

// ----------------------------------------------------------------------------------------
// Geometria de escala do SVG
// ----------------------------------------------------------------------------------------

test("xParaSvg: mapeia o domínio linearmente para [0, largura]", () => {
  expect(xParaSvg(0, 0, 10, 100)).toBe(0);
  expect(xParaSvg(5, 0, 10, 100)).toBe(50);
  expect(xParaSvg(10, 0, 10, 100)).toBe(100);
});

test("xParaSvg: domínio degenerado (maximo <= minimo) nunca divide por zero", () => {
  expect(xParaSvg(5, 10, 10, 100)).toBe(0);
  expect(xParaSvg(5, 20, 10, 100)).toBe(0);
});

test("yParaSvg: mu=1 no topo (y=0), mu=0 na base (y=altura)", () => {
  expect(yParaSvg(1, 120)).toBe(0);
  expect(yParaSvg(0, 120)).toBe(120);
  expect(yParaSvg(0.5, 120)).toBe(60);
});

test("yParaSvg: grau fora de [0,1] é clampado", () => {
  expect(yParaSvg(1.5, 120)).toBe(0);
  expect(yParaSvg(-0.5, 120)).toBe(120);
});

test("pontosPolilinha: um par 'x,y' por ponto da grade, na ordem", () => {
  const pontos = pontosPolilinha([0, 5, 10], [0, 1, 0], 0, 10, 100, 120);
  expect(pontos).toBe("0,120 50,0 100,120");
});

test("pontosArea: fecha o polígono na base (mu=0) nas duas pontas", () => {
  const area = pontosArea([0, 5, 10], [0, 1, 0], 0, 10, 100, 120);
  expect(area).toBe("0,120 0,120 50,0 100,120 100,120");
});

test("pontosArea: grade vazia devolve string vazia", () => {
  expect(pontosArea([], [], 0, 10, 100, 120)).toBe("");
});

test("xDoMarcador: clampa o valor ao domínio antes de mapear", () => {
  expect(xDoMarcador(-5, 0, 10, LARGURA_VIEWBOX)).toBe(0);
  expect(xDoMarcador(50, 0, 10, LARGURA_VIEWBOX)).toBe(LARGURA_VIEWBOX);
  expect(xDoMarcador(5, 0, 10, LARGURA_VIEWBOX)).toBeCloseTo(LARGURA_VIEWBOX / 2);
});

test("viewBox padrão: constantes exportadas para o SVG do painel", () => {
  expect(LARGURA_VIEWBOX).toBeGreaterThan(0);
  expect(ALTURA_VIEWBOX).toBeGreaterThan(0);
});

// ----------------------------------------------------------------------------------------
// Rodapés μ(x) / ŷ
// ----------------------------------------------------------------------------------------

test("rodapeMuDeX: soma só os termos com grau > 0, 3 casas, ponto decimal", () => {
  const texto = rodapeMuDeX([
    { term: "MEDIUM", degree: 0.9235 },
    { term: "LOW", degree: 0 },
    { term: "HIGH", degree: 0.1128 },
  ]);
  expect(texto).toBe("μ(x) = 0.924/MEDIUM + 0.113/HIGH");
});

test("tresCasas: empate decimal sobe (meia-para-cima), não segue o acaso do double", () => {
  // `toFixed(3)` devolveria "0.923" aqui: o double de 0.9235 é 0.92349999999999998757.
  expect(tresCasas(0.9235)).toBe("0.924");
  expect(tresCasas(0.0045)).toBe("0.005");
  expect(tresCasas(-0.9235)).toBe("-0.924");
});

test("tresCasas: sem separador de milhar e sem zero negativo", () => {
  // `ŷ` está na EU da planta e passa de mil; o `Intl` agruparia em "1,234.568".
  expect(tresCasas(1234.5678)).toBe("1234.568");
  // `-0` sairia como "-0.000" sem a normalização.
  expect(tresCasas(-0)).toBe("0.000");
  expect(tresCasas(0)).toBe("0.000");
});

test("tresCasas: sempre três casas, mesmo em inteiro", () => {
  expect(tresCasas(1)).toBe("1.000");
  expect(tresCasas(23.4562)).toBe("23.456");
});

test("rodapeMuDeX: nenhum termo ativo devolve 'μ(x) = 0'", () => {
  expect(rodapeMuDeX([{ term: "LOW", degree: 0 }])).toBe("μ(x) = 0");
  expect(rodapeMuDeX([])).toBe("μ(x) = 0");
});

test("rodapeYChapeu: valor com EU", () => {
  expect(rodapeYChapeu(23.4562, "°C")).toBe("ŷ = 23.456 °C");
});

test("rodapeYChapeu: valor sem EU (string vazia ou ausente) não deixa espaço sobrando", () => {
  expect(rodapeYChapeu(10, null)).toBe("ŷ = 10.000");
  expect(rodapeYChapeu(10, "")).toBe("ŷ = 10.000");
});

test("rodapeYChapeu: v null (cold-start) cai no travessão, nunca finge um número", () => {
  expect(rodapeYChapeu(null, "°C")).toBe("ŷ = —");
});
