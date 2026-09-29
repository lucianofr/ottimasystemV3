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
 * Blocos de compensação dinâmica Lead-Lag e Tempo morto no modelo do editor.
 *
 * Arquivo próprio, mesmo motivo de `filtros.check.ts`/`utilitarios.check.ts`:
 * `graph.check.ts` está no teto de linhas do projeto.
 */

const POS = { x: 0, y: 0 };

const TAGS: MapaTags = new Map([
  [10, "float"],
  [11, "bool"],
]);

function compensador(tipo: "lead_lag" | "dead_time", id = "c1", ordem = 2): BlocoNode {
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

test("os dois blocos estão na paleta com rótulo em pt-BR", () => {
  expect(TIPOS_BLOCO).toContain("lead_lag");
  expect(TIPOS_BLOCO).toContain("dead_time");
  expect(ROTULO_BLOCO.lead_lag).toBe("Lead-Lag");
  expect(ROTULO_BLOCO.dead_time).toBe("Tempo morto");
});

for (const tipo of ["lead_lag", "dead_time"] as const) {
  test(`${tipo} tem exatamente uma entrada e uma saída`, () => {
    const no = compensador(tipo);

    expect(handlesEntrada(no)).toEqual(["in"]);
    expect(handlesSaida(no)).toEqual(["out"]);
  });

  test(`${tipo} tem portas numéricas`, () => {
    expect(tipoPorta(compensador(tipo), TAGS)).toBe("num");
  });

  test(`${tipo} recusa ligação com porta booleana`, () => {
    const nos = [leitura("r1", 1, 11), compensador(tipo)];

    const motivo = motivoRecusa(
      { source: "r1", target: "c1", sourceHandle: "out", targetHandle: "in" },
      nos,
      [],
      TAGS,
    );

    expect(motivo).toContain("booleana");
  });

  test(`${tipo} aceita ligação com tag numérica`, () => {
    const nos = [leitura("r1", 1, 10), compensador(tipo)];

    const motivo = motivoRecusa(
      { source: "r1", target: "c1", sourceHandle: "out", targetHandle: "in" },
      nos,
      [],
      TAGS,
    );

    expect(motivo).toBeNull();
  });

  test(`aresta pendurada em porta que ${tipo} não tem é podada`, () => {
    const arestas = [aresta("e1", "r1", "c1", "pv")];

    expect(podarArestasDoBloco(arestas, compensador(tipo))).toEqual([]);
  });
}

test("lead_lag nasce neutro: ganho 1 e razão 1, sem alterar o sinal até ser configurado", () => {
  const no = compensador("lead_lag");
  if (no.type !== "lead_lag") throw new Error("tipo preservado");

  expect(no.data.gain).toBe(1);
  expect(no.data.tau_lead).toBe(10);
  expect(no.data.tau_lag).toBe(10);
});

test("dead_time nasce com theta 0 (passagem direta)", () => {
  const no = compensador("dead_time");
  if (no.type !== "dead_time") throw new Error("tipo preservado");

  expect(no.data.theta).toBe(0);
});

test("round-trip preserva a config dos dois blocos", () => {
  const leadLag = compensador("lead_lag", "c1", 2);
  const deadTime = compensador("dead_time", "d1", 3);
  if (leadLag.type !== "lead_lag" || deadTime.type !== "dead_time") {
    throw new Error("tipo preservado");
  }
  const nos: BlocoNode[] = [
    leitura("r1", 1, 10),
    {
      ...leadLag,
      data: { ...leadLag.data, gain: -2.5, tau_lead: 40, tau_lag: 8, label: "FF da carga" },
    },
    { ...deadTime, data: { ...deadTime.data, theta: 45 } },
    escrita("w1", 4, 10),
  ];
  const arestas = [aresta("e1", "r1", "d1"), aresta("e2", "d1", "c1"), aresta("e3", "c1", "w1")];

  const lido = deGraphJson(paraGraphJson(nos, arestas));

  expect(lido.nodes).toEqual(nos);
  expect(lido.edges).toEqual(arestas);
});

test("campo corrompido no graph_json cai no padrão em vez de virar NaN", () => {
  const bruto = {
    nodes: [
      {
        id: "c1",
        type: "lead_lag",
        position: POS,
        data: { exec_order: 1, label: "", gain: "dois", tau_lead: 40, tau_lag: 8 },
      },
      {
        id: "d1",
        type: "dead_time",
        position: POS,
        data: { exec_order: 2, label: "", theta: null },
      },
    ],
    edges: [],
  };

  const { nodes } = deGraphJson(bruto);

  const [leadLag, deadTime] = nodes;
  if (leadLag.type !== "lead_lag" || deadTime.type !== "dead_time") {
    throw new Error("tipo preservado");
  }
  expect(leadLag.data.gain).toBe(1);
  expect(deadTime.data.theta).toBe(0);
});

test("data serializado carrega só as chaves que o servidor aceita", () => {
  const { nodes } = paraGraphJson(
    [compensador("lead_lag", "c1", 1), compensador("dead_time", "d1", 2)],
    [],
  );

  expect(Object.keys(nodes[0].data).sort()).toEqual([
    "exec_order",
    "gain",
    "label",
    "tau_lag",
    "tau_lead",
  ]);
  expect(Object.keys(nodes[1].data).sort()).toEqual(["exec_order", "label", "theta"]);
});
