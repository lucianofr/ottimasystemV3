import { expect, test } from "@playwright/test";

import {
  criarBloco,
  deGraphJson,
  handlesEntrada,
  handlesSaida,
  motivoRecusa,
  passagemDireta,
  paraGraphJson,
  podarArestasDoBloco,
  ROTULO_BLOCO,
  TIPOS_BLOCO,
  tipoPorta,
  type BlocoEdge,
  type BlocoNode,
  type MapaTags,
} from "./graph";

/**
 * Blocos de filtro no modelo do editor (RF-531/532/533, ADR-026).
 *
 * Arquivo próprio, e não mais casos em `graph.check.ts`: aquele arquivo já cobre os cinco
 * blocos originais e está perto do teto de linhas do projeto.
 */

const POS = { x: 0, y: 0 };

const TAGS: MapaTags = new Map([
  [10, "float"],
  [11, "bool"],
]);

function filtro(tipo: "first_order" | "kalman", id = "f1", ordem = 2): BlocoNode {
  return criarBloco(tipo, id, POS, ordem);
}

function leitura(id: string, ordem: number, tag: number | null): BlocoNode {
  return { id, type: "opc_read", position: POS, data: { exec_order: ordem, label: "", tag_id: tag } };
}

function escrita(id: string, ordem: number, tag: number | null): BlocoNode {
  return {
    id,
    type: "opc_write",
    position: POS,
    data: { exec_order: ordem, label: "", tag_id: tag },
  };
}

function aresta(id: string, source: string, target: string, entrada = "in"): BlocoEdge {
  return { id, source, target, sourceHandle: "out", targetHandle: entrada };
}

// --------------------------------------------------------------------------------------
// Paleta e portas
// --------------------------------------------------------------------------------------

test("os dois filtros estão na paleta com rótulo em pt-BR", () => {
  expect(TIPOS_BLOCO).toContain("first_order");
  expect(TIPOS_BLOCO).toContain("kalman");
  expect(ROTULO_BLOCO.first_order).toBe("Filtro 1ª ordem");
  expect(ROTULO_BLOCO.kalman).toBe("Filtro Kalman");
});

for (const tipo of ["first_order", "kalman"] as const) {
  test(`${tipo} tem exatamente uma entrada e uma saída`, () => {
    const no = filtro(tipo);

    expect(handlesEntrada(no)).toEqual(["in"]);
    expect(handlesSaida(no)).toEqual(["out"]);
  });

  test(`${tipo} tem portas numéricas`, () => {
    expect(tipoPorta(filtro(tipo), TAGS)).toBe("num");
  });

  test(`${tipo} recusa ligação com porta booleana`, () => {
    const nos = [leitura("r1", 1, 11), filtro(tipo)];

    const motivo = motivoRecusa(
      { source: "r1", target: "f1", sourceHandle: "out", targetHandle: "in" },
      nos,
      [],
      TAGS,
    );

    expect(motivo).toContain("booleana");
  });

  test(`${tipo} aceita ligação com tag numérica`, () => {
    const nos = [leitura("r1", 1, 10), filtro(tipo)];

    const motivo = motivoRecusa(
      { source: "r1", target: "f1", sourceHandle: "out", targetHandle: "in" },
      nos,
      [],
      TAGS,
    );

    expect(motivo).toBeNull();
  });

  test(`reconfigurar ${tipo} não poda a aresta da entrada`, () => {
    const no = filtro(tipo);
    const arestas = [aresta("e1", "r1", "f1"), aresta("e2", "f1", "w1")];

    expect(podarArestasDoBloco(arestas, no)).toEqual(arestas);
  });
}

test("aresta pendurada em porta que o filtro não tem é podada", () => {
  const arestas = [aresta("e1", "r1", "f1", "u1")];

  expect(podarArestasDoBloco(arestas, filtro("first_order"))).toEqual([]);
});

// --------------------------------------------------------------------------------------
// Config: defaults, serialização e leitura
// --------------------------------------------------------------------------------------

test("filtro de 1ª ordem nasce com tau padrão", () => {
  const no = filtro("first_order");
  if (no.type !== "first_order") throw new Error("tipo preservado");

  expect(no.data.tau).toBe(5);
  expect(no.data.exec_order).toBe(2);
});

// --------------------------------------------------------------------------------------
// passagemDireta — limiar Ts/10 do rótulo (TD-011), espelho de DIRECT_PASS_RATIO do runtime
// --------------------------------------------------------------------------------------

test("passagemDireta: tau=0 é sempre passagem direta, mesmo sem Ts do flow", () => {
  expect(passagemDireta(0, 0)).toBe(true);
  expect(passagemDireta(0, 10)).toBe(true);
});

test("passagemDireta: tau abaixo de Ts/10 é passagem direta", () => {
  expect(passagemDireta(0.05, 1)).toBe(true);
});

test("passagemDireta: tau exatamente em Ts/10 continua dinâmico (mesma fronteira do runtime)", () => {
  expect(passagemDireta(0.1, 1)).toBe(false);
});

test("passagemDireta: tau bem acima de Ts/10 continua dinâmico", () => {
  expect(passagemDireta(5, 1)).toBe(false);
});

test("Kalman nasce com ruído padrão que passa no save", () => {
  const no = filtro("kalman");
  if (no.type !== "kalman") throw new Error("tipo preservado");

  // `measurement_noise` é o divisor do ganho: zero seria 422 no save (ADR-026).
  expect(no.data.measurement_noise).toBeGreaterThan(0);
  expect(no.data.process_noise).toBeGreaterThanOrEqual(0);
});

test("round-trip preserva a config dos dois filtros", () => {
  const primeira = filtro("first_order", "f1", 2);
  const kalman = filtro("kalman", "k1", 3);
  if (primeira.type !== "first_order" || kalman.type !== "kalman") {
    throw new Error("tipo preservado");
  }
  const nos: BlocoNode[] = [
    leitura("r1", 1, 10),
    { ...primeira, data: { ...primeira.data, tau: 12.5, label: "Filtro da PV" } },
    { ...kalman, data: { ...kalman.data, measurement_noise: 0.8, process_noise: 0.02 } },
    escrita("w1", 4, 10),
  ];
  const arestas = [aresta("e1", "r1", "f1"), aresta("e2", "f1", "k1"), aresta("e3", "k1", "w1")];

  const lido = deGraphJson(paraGraphJson(nos, arestas));

  expect(lido.nodes).toEqual(nos);
  expect(lido.edges).toEqual(arestas);
});

test("campo corrompido no graph_json cai no padrão em vez de virar NaN", () => {
  const bruto = {
    nodes: [
      {
        id: "f1",
        type: "first_order",
        position: POS,
        data: { exec_order: 1, label: "", tau: "doze" },
      },
      {
        id: "k1",
        type: "kalman",
        position: POS,
        data: { exec_order: 2, label: "", measurement_noise: null, process_noise: 0.02 },
      },
    ],
    edges: [],
  };

  const { nodes } = deGraphJson(bruto);

  const [primeira, kalman] = nodes;
  if (primeira.type !== "first_order" || kalman.type !== "kalman") {
    throw new Error("tipo preservado");
  }
  expect(primeira.data.tau).toBe(5);
  expect(kalman.data.measurement_noise).toBe(1);
  expect(kalman.data.process_noise).toBe(0.02);
});

test("data serializado carrega só as chaves que o servidor aceita", () => {
  const { nodes } = paraGraphJson([filtro("kalman", "k1", 1)], []);

  expect(Object.keys(nodes[0].data).sort()).toEqual([
    "exec_order",
    "label",
    "measurement_noise",
    "process_noise",
  ]);
});
