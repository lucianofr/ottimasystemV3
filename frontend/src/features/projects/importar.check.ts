import { expect, test } from "@playwright/test";

import {
  comoObjeto,
  contarBundle,
  extrairBlocosScript,
  nomeInicialDoBundle,
  particionarDetalhe,
} from "./importar";

/**
 * `importar.ts` — tarefa 2.4 do plano F6b (spec §3.2-5, §6.1-6, F6R-03). Lógica pura do
 * fluxo de import de arquivo de projeto: partição do `detail` agregado de 422, contagens
 * de conexões/tags/flows e extração dos blocos Script para revisão do admin. Sem I/O, sem
 * DOM — o componente `ImportarProjeto.tsx` é quem lê o arquivo e envia.
 */

// --------------------------------------------------------------------------------------
// particionarDetalhe — separador ` | `, nunca `;` (UX-06)
// --------------------------------------------------------------------------------------

test("particionarDetalhe quebra o detail agregado em uma linha por problema, node_id com ; íntegro", () => {
  const detail =
    "Import recusado (2 problemas) | tags[7]: nó 'x7k2' refere tag inexistente (conexão " +
    "'gateway-2', tag 'ns=2;s=TT101') | connections[0]: SecurityPolicy None exige modo None";
  expect(particionarDetalhe(detail)).toEqual([
    "tags[7]: nó 'x7k2' refere tag inexistente (conexão 'gateway-2', tag 'ns=2;s=TT101')",
    "connections[0]: SecurityPolicy None exige modo None",
  ]);
});

test("particionarDetalhe com o exemplo normativo da spec F6 §3.2-5 (cabeçalho + 3 problemas)", () => {
  const detail =
    "Import recusado (3 problemas) | flows[2].graph: nó 'mpc_x7k2' refere tag inexistente " +
    "(conexão 'gateway-1', tag 'TT-999') | tags[7]: conexão 'gateway-2' não existe no arquivo " +
    "| connections[0]: SecurityPolicy None exige modo None";
  expect(particionarDetalhe(detail)).toEqual([
    "flows[2].graph: nó 'mpc_x7k2' refere tag inexistente (conexão 'gateway-1', tag 'TT-999')",
    "tags[7]: conexão 'gateway-2' não existe no arquivo",
    "connections[0]: SecurityPolicy None exige modo None",
  ]);
});

test("particionarDetalhe preserva o sufixo ' | e mais N' como último item, sem truncar os 10 exibidos", () => {
  const problemas = Array.from({ length: 10 }, (_, i) => `p${String(i + 1)}`);
  const detail = `Import recusado (13 problemas) | ${problemas.join(" | ")} | e mais 3`;
  const partes = particionarDetalhe(detail);
  expect(partes).toHaveLength(11);
  expect(partes.slice(0, 10)).toEqual(problemas);
  expect(partes[10]).toBe("e mais 3");
});

test("particionarDetalhe com um problema só ainda usa '(1 problemas)' (backend nunca singulariza)", () => {
  const detail = "Import recusado (1 problemas) | schema_version 2 não suportado; esperado 1";
  expect(particionarDetalhe(detail)).toEqual(["schema_version 2 não suportado; esperado 1"]);
});

test("particionarDetalhe NÃO explode detail fora do formato agregado (413 de tamanho)", () => {
  const detail = "Corpo do import excede o limite de 4 MiB.";
  expect(particionarDetalhe(detail)).toEqual([detail]);
});

test("particionarDetalhe NÃO explode detail fora do formato agregado (409 de nome duplicado)", () => {
  const detail = "Nome de projeto já em uso";
  expect(particionarDetalhe(detail)).toEqual([detail]);
});

test("particionarDetalhe NÃO explode detail fora do formato agregado (422 de corpo não-JSON)", () => {
  const detail = "Corpo não é JSON válido";
  expect(particionarDetalhe(detail)).toEqual([detail]);
});

// --------------------------------------------------------------------------------------
// comoObjeto — único ponto de checagem de forma do módulo
// --------------------------------------------------------------------------------------

test("comoObjeto aceita objeto plano e recusa array/primitivo/null", () => {
  expect(comoObjeto({ a: 1 })).toEqual({ a: 1 });
  expect(comoObjeto([1, 2])).toBeNull();
  expect(comoObjeto("texto")).toBeNull();
  expect(comoObjeto(42)).toBeNull();
  expect(comoObjeto(null)).toBeNull();
  expect(comoObjeto(undefined)).toBeNull();
});

// --------------------------------------------------------------------------------------
// contarBundle — tolerante a arquivo malformado, nunca lança
// --------------------------------------------------------------------------------------

test("contarBundle conta connections/tags/flows de um arquivo bem formado", () => {
  const bundle = {
    connections: [{ name: "gw1" }, { name: "gw2" }],
    tags: [{ name: "TT-101" }],
    flows: [{ name: "f1" }, { name: "f2" }, { name: "f3" }],
  };
  expect(contarBundle(bundle)).toEqual({ connections: 2, tags: 1, flows: 3 });
});

test("contarBundle devolve zeros para arquivo malformado, sem lançar", () => {
  expect(contarBundle({})).toEqual({ connections: 0, tags: 0, flows: 0 });
  expect(contarBundle({ connections: "não é array", tags: 5, flows: null })).toEqual({
    connections: 0,
    tags: 0,
    flows: 0,
  });
  expect(contarBundle(null)).toEqual({ connections: 0, tags: 0, flows: 0 });
  expect(contarBundle("texto")).toEqual({ connections: 0, tags: 0, flows: 0 });
  expect(contarBundle([1, 2, 3])).toEqual({ connections: 0, tags: 0, flows: 0 });
});

// --------------------------------------------------------------------------------------
// nomeInicialDoBundle — decisão A-6, campo editável pré-preenchido
// --------------------------------------------------------------------------------------

test("nomeInicialDoBundle lê bundle.project.name", () => {
  expect(nomeInicialDoBundle({ project: { name: "Planta C-101" } })).toBe("Planta C-101");
});

test("nomeInicialDoBundle devolve string vazia para arquivo sem project.name, sem lançar", () => {
  expect(nomeInicialDoBundle({ project: {} })).toBe("");
  expect(nomeInicialDoBundle({})).toBe("");
  expect(nomeInicialDoBundle({ project: null })).toBe("");
  expect(nomeInicialDoBundle("texto")).toBe("");
  expect(nomeInicialDoBundle(null)).toBe("");
});

// --------------------------------------------------------------------------------------
// extrairBlocosScript — F6R-03: o admin nunca importa às cegas
// --------------------------------------------------------------------------------------

function noScript(label: string, code: string): unknown {
  return {
    id: "s1",
    type: "script",
    position: { x: 0, y: 0 },
    data: { exec_order: 1, label, n_inputs: 1, n_outputs: 1, code, output_eu: {} },
  };
}

function noLeitura(): unknown {
  return {
    id: "r1",
    type: "opc_read",
    position: { x: 0, y: 0 },
    data: { exec_order: 1, label: "", tag_id: null },
  };
}

test("extrairBlocosScript extrai só os nós type=script, com nome do flow, rótulo e código", () => {
  const bundle = {
    flows: [
      {
        name: "Coluna C-101",
        graph: { nodes: [noLeitura(), noScript("Conversor", "OUT1 = IN1 * 2")], edges: [] },
      },
    ],
  };
  expect(extrairBlocosScript(bundle)).toEqual([
    { flow: "Coluna C-101", label: "Conversor", code: "OUT1 = IN1 * 2" },
  ]);
});

test("extrairBlocosScript preserva a ordem: flow a flow, nó a nó, como no arquivo", () => {
  const bundle = {
    flows: [
      { name: "f1", graph: { nodes: [noScript("a", "codeA")], edges: [] } },
      { name: "f2", graph: { nodes: [noScript("b", "codeB"), noScript("c", "codeC")], edges: [] } },
    ],
  };
  expect(extrairBlocosScript(bundle)).toEqual([
    { flow: "f1", label: "a", code: "codeA" },
    { flow: "f2", label: "b", code: "codeB" },
    { flow: "f2", label: "c", code: "codeC" },
  ]);
});

test("extrairBlocosScript devolve [] quando não há bloco Script no arquivo", () => {
  const bundle = { flows: [{ name: "f1", graph: { nodes: [noLeitura()], edges: [] } }] };
  expect(extrairBlocosScript(bundle)).toEqual([]);
});

test("extrairBlocosScript tolera grafo malformado sem lançar (flow sem graph, nodes que não é array)", () => {
  const bundle = {
    flows: [
      { name: "sem-graph" },
      { name: "nodes-nao-e-array", graph: { nodes: "não é array" } },
      { name: "graph-nulo", graph: null },
      "flow não é objeto",
    ],
  };
  expect(() => extrairBlocosScript(bundle)).not.toThrow();
  expect(extrairBlocosScript(bundle)).toEqual([]);
});

test("extrairBlocosScript tolera nó script sem data (label vira 'Script', code vira '')", () => {
  const bundle = {
    flows: [
      {
        name: "f1",
        graph: { nodes: [{ id: "s1", type: "script", position: { x: 0, y: 0 } }], edges: [] },
      },
    ],
  };
  expect(extrairBlocosScript(bundle)).toEqual([{ flow: "f1", label: "Script", code: "" }]);
});

test("extrairBlocosScript tolera bundle malformado (não-objeto) sem lançar", () => {
  expect(extrairBlocosScript(null)).toEqual([]);
  expect(extrairBlocosScript("texto")).toEqual([]);
  expect(extrairBlocosScript({})).toEqual([]);
});
