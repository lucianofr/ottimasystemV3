import { expect, test } from "@playwright/test";

import { NAV_ADMIN, NAV_ENGENHARIA, NAV_OPERACAO, NAV_SENSOR_VIRTUAL } from "./AppShell";

/**
 * Contrato de navegação do shell, como função pura (sem browser, sem backend).
 *
 * Nasceu do defeito real registrado em `docs/reports/advisor/012-operacao-loop-na-navegacao.md`:
 * `/operacao/loop` — única superfície que comanda o modo dos blocos malha `pid_loop`/`fuzzy_loop`
 * (ADR-039) — entrou no produto sem nenhum link apontando para ela, e nada falhou, porque o
 * contrato de nav não era pinhado por teste nenhum. Um bloco de malha em execução ficava
 * invisível para o operador de turno (só alcançável digitando a URL).
 *
 * `router.tsx` NÃO é parseado de propósito: a lista literal abaixo é a cópia que se quer manter
 * sincronizada à mão. Rota nova sem item de nav (ou item de nav sem rota) quebra aqui — que é
 * exatamente o atrito desejado.
 */

/** Espelha `frontend/src/app/router.tsx` — todas as rotas filhas do `AppShell` que têm item de
 *  navegação. Ficam de fora, deliberadamente: `/login` (fora do shell), `/` (HomePage, marca do
 *  cabeçalho) e as rotas de detalhe `/operacao/:flowId/:blockId` e
 *  `/engenharia/flows/:flowId`, alcançadas por clique a partir das telas com item. */
const ROTAS_COM_NAV = [
  "/operacao",
  "/operacao/fuzzy",
  "/operacao/loop",
  "/eventos",
  "/engenharia/projetos",
  "/engenharia/conexoes",
  "/engenharia/tags",
  "/engenharia/flows",
  "/engenharia/trend",
  "/engenharia/sensor-virtual/coleta",
  "/engenharia/sensor-virtual/otimizacao",
  "/configuracoes",
] as const;

const GRUPOS = [
  { nome: "NAV_OPERACAO", itens: NAV_OPERACAO },
  { nome: "NAV_ENGENHARIA", itens: NAV_ENGENHARIA },
  { nome: "NAV_SENSOR_VIRTUAL", itens: NAV_SENSOR_VIRTUAL },
  { nome: "NAV_ADMIN", itens: NAV_ADMIN },
] as const;

test("toda rota com item de navegação tem item, e todo item aponta para rota existente", () => {
  const doShell = GRUPOS.flatMap((grupo) => grupo.itens.map((item) => item.para));

  expect([...new Set(doShell)].sort()).toEqual([...ROTAS_COM_NAV].sort());
});

test("nenhum data-testid de navegação se repete entre os grupos", () => {
  const testids = GRUPOS.flatMap((grupo) => grupo.itens.map((item) => item.testid));

  expect(new Set(testids).size).toBe(testids.length);
});

test("todo item tem rótulo não-vazio e destino absoluto", () => {
  for (const grupo of GRUPOS) {
    for (const item of grupo.itens) {
      expect(item.rotulo.trim(), `${grupo.nome} ${item.testid}`).not.toBe("");
      expect(item.para.startsWith("/"), `${grupo.nome} ${item.testid}`).toBe(true);
    }
  }
});

test("configurações vive só no grupo admin — o único condicionado a role", () => {
  const testidsForaDoAdmin = [...NAV_OPERACAO, ...NAV_ENGENHARIA].map((item) => item.testid);
  const paraForaDoAdmin = [...NAV_OPERACAO, ...NAV_ENGENHARIA].map((item) => item.para);

  expect(NAV_ADMIN.map((item) => item.para)).toEqual(["/configuracoes"]);
  expect(testidsForaDoAdmin).not.toContain("nav-configuracoes");
  expect(paraForaDoAdmin).not.toContain("/configuracoes");
});

test("sensor virtual vive em constante própria: NAV_ENGENHARIA segue estático (item condicional)", () => {
  const paraEngenharia = NAV_ENGENHARIA.map((item) => item.para);

  expect(NAV_SENSOR_VIRTUAL.map((item) => item.para)).toEqual([
    "/engenharia/sensor-virtual/coleta",
    "/engenharia/sensor-virtual/otimizacao",
  ]);
  expect(paraEngenharia).not.toContain("/engenharia/sensor-virtual/coleta");
  expect(paraEngenharia).not.toContain("/engenharia/sensor-virtual/otimizacao");
});

test("rota de otimização está na navegação", () => {
  // depois de "Coleta e treino", no mesmo grupo condicional (só com bloco de sensor virtual)
  expect(NAV_SENSOR_VIRTUAL.map((item) => item.testid)).toEqual(["nav-sv-coleta", "nav-sv-otim"]);
  expect(NAV_SENSOR_VIRTUAL[1]).toEqual({
    rotulo: "Otimização",
    para: "/engenharia/sensor-virtual/otimizacao",
    testid: "nav-sv-otim",
  });
});
