import { expect, test } from "@playwright/test";

import {
  criarBloco,
  deGraphJson,
  handlesEntrada,
  handlesSaida,
  motivoRecusa,
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
 * Blocos utilitários Scaler e Integrator no modelo do editor.
 *
 * Arquivo próprio, mesmo motivo de `filtros.check.ts`: `graph.check.ts` está no teto de
 * linhas do projeto.
 */

const POS = { x: 0, y: 0 };

const TAGS: MapaTags = new Map([
  [10, "float"],
  [11, "bool"],
]);

function utilitario(tipo: "scaler" | "integrator", id = "u1", ordem = 2): BlocoNode {
  return criarBloco(tipo, id, POS, ordem);
}

function leitura(id: string, ordem: number, tag: number | null): BlocoNode {
  return { id, type: "opc_read", position: POS, data: { exec_order: ordem, label: "", tag_id: tag } };
}

function escrita(id: string, ordem: number, tag: number | null): BlocoNode {
  return { id, type: "opc_write", position: POS, data: { exec_order: ordem, label: "", tag_id: tag } };
}

function aresta(id: string, source: string, target: string, entrada = "in"): BlocoEdge {
  return { id, source, target, sourceHandle: "out", targetHandle: entrada };
}

// --------------------------------------------------------------------------------------
// Paleta e portas
// --------------------------------------------------------------------------------------

test("os dois utilitários estão na paleta com rótulo em pt-BR", () => {
  expect(TIPOS_BLOCO).toContain("scaler");
  expect(TIPOS_BLOCO).toContain("integrator");
  expect(ROTULO_BLOCO.scaler).toBe("Scaler");
  expect(ROTULO_BLOCO.integrator).toBe("Integrador");
});

test("scaler tem exatamente uma entrada e uma saída", () => {
  const no = utilitario("scaler");

  expect(handlesEntrada(no)).toEqual(["in"]);
  expect(handlesSaida(no)).toEqual(["out"]);
});

test("integrator tem in + reset na entrada e out na saída", () => {
  const no = utilitario("integrator");

  expect(handlesEntrada(no)).toEqual(["in", "reset"]);
  expect(handlesSaida(no)).toEqual(["out"]);
});

for (const tipo of ["scaler", "integrator"] as const) {
  test(`${tipo} tem portas numéricas`, () => {
    expect(tipoPorta(utilitario(tipo), TAGS)).toBe("num");
  });

  test(`${tipo} recusa ligação com porta booleana`, () => {
    const nos = [leitura("r1", 1, 11), utilitario(tipo)];

    const motivo = motivoRecusa(
      { source: "r1", target: "u1", sourceHandle: "out", targetHandle: "in" },
      nos,
      [],
      TAGS,
    );

    expect(motivo).toContain("booleana");
  });

  test(`${tipo} aceita ligação com tag numérica`, () => {
    const nos = [leitura("r1", 1, 10), utilitario(tipo)];

    const motivo = motivoRecusa(
      { source: "r1", target: "u1", sourceHandle: "out", targetHandle: "in" },
      nos,
      [],
      TAGS,
    );

    expect(motivo).toBeNull();
  });

  test(`reconfigurar ${tipo} não poda a aresta da entrada`, () => {
    const no = utilitario(tipo);
    const arestas = [aresta("e1", "r1", "u1"), aresta("e2", "u1", "w1")];

    expect(podarArestasDoBloco(arestas, no)).toEqual(arestas);
  });

  test(`aresta pendurada em porta que ${tipo} não tem é podada`, () => {
    const arestas = [aresta("e1", "r1", "u1", "u1")];

    expect(podarArestasDoBloco(arestas, utilitario(tipo))).toEqual([]);
  });
}

// --------------------------------------------------------------------------------------
// Config: defaults, serialização e leitura
// --------------------------------------------------------------------------------------

test("scaler nasce com a escala padrão 0-100 → 4-20", () => {
  const no = utilitario("scaler");
  if (no.type !== "scaler") throw new Error("tipo preservado");

  // `in_max` > `in_min`: o divisor nunca zera — o bloco recém-arrastado passa no save.
  expect(no.data.in_min).toBe(0);
  expect(no.data.in_max).toBe(100);
  expect(no.data.out_min).toBe(4);
  expect(no.data.out_max).toBe(20);
});

test("integrator nasce na base por minuto", () => {
  const no = utilitario("integrator");
  if (no.type !== "integrator") throw new Error("tipo preservado");

  expect(no.data.time_base).toBe("min");
});

test("round-trip preserva a config dos dois utilitários", () => {
  const scaler = utilitario("scaler", "s1", 2);
  const integrator = utilitario("integrator", "i1", 3);
  if (scaler.type !== "scaler" || integrator.type !== "integrator") {
    throw new Error("tipo preservado");
  }
  const nos: BlocoNode[] = [
    leitura("r1", 1, 10),
    { ...scaler, data: { ...scaler.data, in_min: -50, in_max: 150, label: "mA da vazão" } },
    { ...integrator, data: { ...integrator.data, time_base: "h" } },
    escrita("w1", 4, 10),
  ];
  const arestas = [
    aresta("e1", "r1", "s1"),
    aresta("e2", "s1", "i1"),
    aresta("e3", "r1", "i1", "reset"),
    aresta("e4", "i1", "w1"),
  ];

  const lido = deGraphJson(paraGraphJson(nos, arestas));

  expect(lido.nodes).toEqual(nos);
  expect(lido.edges).toEqual(arestas);
});

test("campo corrompido no graph_json cai no padrão em vez de virar NaN", () => {
  const bruto = {
    nodes: [
      {
        id: "s1",
        type: "scaler",
        position: POS,
        data: { exec_order: 1, label: "", in_min: 0, in_max: "cem", out_min: 4, out_max: 20 },
      },
      {
        id: "i1",
        type: "integrator",
        position: POS,
        data: { exec_order: 2, label: "", time_base: "segundo" },
      },
    ],
    edges: [],
  };

  const { nodes } = deGraphJson(bruto);

  const [scaler, integrator] = nodes;
  if (scaler.type !== "scaler" || integrator.type !== "integrator") {
    throw new Error("tipo preservado");
  }
  expect(scaler.data.in_max).toBe(100);
  expect(integrator.data.time_base).toBe("min");
});

test("data serializado carrega só as chaves que o servidor aceita", () => {
  const { nodes } = paraGraphJson(
    [utilitario("scaler", "s1", 1), utilitario("integrator", "i1", 2)],
    [],
  );

  expect(Object.keys(nodes[0].data).sort()).toEqual([
    "exec_order",
    "in_max",
    "in_min",
    "label",
    "out_max",
    "out_min",
  ]);
  expect(Object.keys(nodes[1].data).sort()).toEqual(["exec_order", "label", "time_base"]);
});
