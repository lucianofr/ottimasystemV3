import { expect, test } from "@playwright/test";

import {
  criarBloco,
  deGraphJson,
  handlesEntrada,
  handlesSaida,
  motivoRecusa,
  paraGraphJson,
  ROTULO_BLOCO,
  TIPOS_BLOCO,
  tipoPorta,
  type BlocoEdge,
  type BlocoNode,
  type MapaTags,
} from "./graph";

/**
 * Bloco PID no modelo do editor (RF-551..554, ADR-031).
 *
 * Arquivo próprio, mesmo precedente de `filtros.check.ts`: um `*.check.ts` por bloco novo em
 * vez de inchar `graph.check.ts`.
 */

const POS = { x: 0, y: 0 };

const TAGS: MapaTags = new Map([
  [10, "float"],
  [11, "bool"],
]);

function pid(id = "p1", ordem = 2): BlocoNode {
  return criarBloco("pid", id, POS, ordem);
}

function leitura(id: string, ordem: number, tag: number | null): BlocoNode {
  return { id, type: "opc_read", position: POS, data: { exec_order: ordem, label: "", tag_id: tag } };
}

// --------------------------------------------------------------------------------------
// Paleta e portas
// --------------------------------------------------------------------------------------

test("PID está na paleta com rótulo em pt-BR", () => {
  expect(TIPOS_BLOCO).toContain("pid");
  expect(ROTULO_BLOCO.pid).toBe("PID");
});

test("PID tem pv/sp de entrada e out de saída", () => {
  const no = pid();

  expect(handlesEntrada(no)).toEqual(["pv", "sp"]);
  expect(handlesSaida(no)).toEqual(["out"]);
});

test("PID tem portas numéricas", () => {
  expect(tipoPorta(pid(), TAGS)).toBe("num");
});

test("PID recusa ligação com porta booleana", () => {
  const nos = [leitura("r1", 1, 11), pid()];

  const motivo = motivoRecusa(
    { source: "r1", target: "p1", sourceHandle: "out", targetHandle: "pv" },
    nos,
    [],
    TAGS,
  );

  expect(motivo).toContain("booleana");
});

// --------------------------------------------------------------------------------------
// Config: defaults, serialização e leitura
// --------------------------------------------------------------------------------------

test("PID nasce com os defaults ISA do gate (ADR-031)", () => {
  const no = pid();
  if (no.type !== "pid") throw new Error("tipo preservado");

  expect(no.data).toEqual({
    exec_order: 2,
    label: "",
    kc: 1,
    ti_seconds: 60,
    td_seconds: 0,
    setpoint: 0,
    output_min: 0,
    output_max: 100,
    auto_mode: true,
    proportional_on_measurement: false,
    differential_on_measurement: true,
    starting_output: 0,
  });
});

test("round-trip preserva os dez campos do PID, incluindo output_min nulo", () => {
  const base = pid("p1", 2);
  if (base.type !== "pid") throw new Error("tipo preservado");
  const nos: BlocoNode[] = [
    {
      ...base,
      data: {
        ...base.data,
        label: "Malha de vazão",
        kc: -2.5,
        ti_seconds: 30,
        td_seconds: 5,
        setpoint: 42,
        output_min: null,
        output_max: 80,
        auto_mode: false,
        proportional_on_measurement: true,
        differential_on_measurement: false,
        starting_output: 10,
      },
    },
  ];
  const arestas: BlocoEdge[] = [];

  const lido = deGraphJson(paraGraphJson(nos, arestas));

  expect(lido.nodes).toEqual(nos);
  expect(lido.edges).toEqual(arestas);
});

test("campo numérico corrompido cai no padrão, mas output_min nulo sobrevive (ADR-031)", () => {
  const bruto = {
    nodes: [
      {
        id: "p1",
        type: "pid",
        position: POS,
        data: {
          exec_order: 1,
          label: "",
          kc: "alto",
          ti_seconds: 60,
          td_seconds: 0,
          setpoint: 0,
          output_min: null,
          output_max: "cem",
          auto_mode: true,
          proportional_on_measurement: false,
          differential_on_measurement: true,
          starting_output: 0,
        },
      },
    ],
    edges: [],
  };

  const { nodes } = deGraphJson(bruto);
  const [no] = nodes;
  if (no.type !== "pid") throw new Error("tipo preservado");

  // `kc` corrompido cai no padrão do gate.
  expect(no.data.kc).toBe(1);
  // `null` explícito é uma escolha do engenheiro (sem limite) — nunca vira default.
  expect(no.data.output_min).toBeNull();
  // já `output_max` corrompido (não-`null`, porém inutilizável) cai no padrão, não em `null`:
  // são dois defeitos diferentes, e o segundo não pode se disfarçar do primeiro.
  expect(no.data.output_max).toBe(100);
});

test("data serializado do PID carrega só as chaves que o servidor aceita", () => {
  const { nodes } = paraGraphJson([pid("p1", 1)], []);

  expect(Object.keys(nodes[0].data).sort()).toEqual([
    "auto_mode",
    "differential_on_measurement",
    "exec_order",
    "kc",
    "label",
    "output_max",
    "output_min",
    "proportional_on_measurement",
    "setpoint",
    "starting_output",
    "td_seconds",
    "ti_seconds",
  ]);
});
