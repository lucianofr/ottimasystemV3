import { expect, test } from "@playwright/test";

import type { GraphJson } from "./graph";
import { impactoDoSave } from "./impactoSave";

/**
 * `impactoDoSave` — tarefa 3.3 do plano (Flows/editor, Fase 3). Espelho de
 * `FlowNode.functional_config()` (`parse.py:148-154`) usado pelo diálogo de impacto do save
 * no editor: MV set + resto de `data` decide `preservado`/`rearme_bumpless`/`reset_local`
 * (TD-006, hot-swap com transplante de estado).
 *
 * Fixtures como JSON solto, sem tipar contra `DadosMpc`/`VariavelMv`: o contrato real de
 * `graph_json` na borda é `Record<string, unknown>` (mesmo formato que a API troca), e a
 * função sob teste também trata `data` como JSON genérico — então o teste não precisa
 * acompanhar campos que esses tipos ganham com o tempo (TD-007 acrescenta `du_min`/
 * `move_weight` à MV em paralelo a este plano).
 */

function noMpc(id: string, dados: Record<string, unknown>, position = { x: 0, y: 0 }) {
  return { id, type: "mpc", position, data: { exec_order: 1, label: "", ...dados } };
}

function noLeitura(id: string) {
  return {
    id,
    type: "opc_read",
    position: { x: 0, y: 0 },
    data: { exec_order: 1, label: "", tag_id: null },
  };
}

function grafo(nos: unknown[]): GraphJson {
  return { nodes: nos, edges: [] } as unknown as GraphJson;
}

const VARIAVEIS_BASE = {
  mvs: [{ id: "mv1" }, { id: "mv2" }],
  cvs: [{ id: "cv1", weight: 1 }],
  constraints: [],
  dvs: [],
};

const DADOS_BASE = { name: "mpc1", multiplier: 4, variables: VARIAVEIS_BASE, models: {} };

test("data idêntico -> preservado", () => {
  const original = grafo([noMpc("m1", DADOS_BASE)]);
  const atual = grafo([noMpc("m1", DADOS_BASE)]);
  expect(impactoDoSave(original, atual, false)).toEqual([
    { blockId: "m1", label: "MPC", efeito: "preservado" },
  ]);
});

test("só label mudou -> preservado", () => {
  const original = grafo([noMpc("m1", { ...DADOS_BASE, label: "Antigo" })]);
  const atual = grafo([noMpc("m1", { ...DADOS_BASE, label: "Novo" })]);
  expect(impactoDoSave(original, atual, false)).toEqual([
    { blockId: "m1", label: "Novo", efeito: "preservado" },
  ]);
});

test("só posição mudou -> preservado", () => {
  const original = grafo([noMpc("m1", DADOS_BASE, { x: 0, y: 0 })]);
  const atual = grafo([noMpc("m1", DADOS_BASE, { x: 480, y: 220 })]);
  expect(impactoDoSave(original, atual, false)).toEqual([
    { blockId: "m1", label: "MPC", efeito: "preservado" },
  ]);
});

test("MV set igual e resto de data mudou -> rearme_bumpless", () => {
  const original = grafo([noMpc("m1", DADOS_BASE)]);
  const atual = grafo([noMpc("m1", { ...DADOS_BASE, multiplier: 6 })]);
  expect(impactoDoSave(original, atual, false)).toEqual([
    { blockId: "m1", label: "MPC", efeito: "rearme_bumpless" },
  ]);
});

test("MV reordenada mantendo o conjunto -> rearme_bumpless (lista mudou de posição)", () => {
  const original = grafo([noMpc("m1", DADOS_BASE)]);
  const reordenado = {
    ...DADOS_BASE,
    variables: { ...VARIAVEIS_BASE, mvs: [{ id: "mv2" }, { id: "mv1" }] },
  };
  const atual = grafo([noMpc("m1", reordenado)]);
  expect(impactoDoSave(original, atual, false)).toEqual([
    { blockId: "m1", label: "MPC", efeito: "rearme_bumpless" },
  ]);
});

test("MV removida -> reset_local", () => {
  const original = grafo([noMpc("m1", DADOS_BASE)]);
  const semMv2 = { ...DADOS_BASE, variables: { ...VARIAVEIS_BASE, mvs: [{ id: "mv1" }] } };
  const atual = grafo([noMpc("m1", semMv2)]);
  expect(impactoDoSave(original, atual, false)).toEqual([
    { blockId: "m1", label: "MPC", efeito: "reset_local" },
  ]);
});

test("Ts do flow mudou, data idêntico -> reset_local", () => {
  const original = grafo([noMpc("m1", DADOS_BASE)]);
  const atual = grafo([noMpc("m1", DADOS_BASE)]);
  expect(impactoDoSave(original, atual, true)).toEqual([
    { blockId: "m1", label: "MPC", efeito: "reset_local" },
  ]);
});

test("grafo sem bloco MPC -> lista vazia", () => {
  const original = grafo([noLeitura("t1")]);
  const atual = grafo([noLeitura("t1")]);
  expect(impactoDoSave(original, atual, false)).toEqual([]);
});

test("bloco MPC novo, sem correspondente no grafo original, não aparece na lista", () => {
  const original = grafo([noLeitura("t1")]);
  const atual = grafo([noLeitura("t1"), noMpc("m1", DADOS_BASE)]);
  expect(impactoDoSave(original, atual, false)).toEqual([]);
});

test("dois blocos MPC com efeitos distintos, cada um com seu blockId/label", () => {
  const original = grafo([
    noMpc("m1", DADOS_BASE),
    noMpc("m2", { ...DADOS_BASE, label: "Secundário" }),
  ]);
  const atual = grafo([
    noMpc("m1", DADOS_BASE),
    noMpc("m2", { ...DADOS_BASE, label: "Secundário", multiplier: 8 }),
  ]);
  const impactos = impactoDoSave(original, atual, false);
  expect(impactos).toEqual([
    { blockId: "m1", label: "MPC", efeito: "preservado" },
    { blockId: "m2", label: "Secundário", efeito: "rearme_bumpless" },
  ]);
});
