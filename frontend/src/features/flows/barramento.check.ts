import { expect, test } from "@playwright/test";

import {
  criarBloco,
  deGraphJson,
  handlesEntrada,
  handlesSaida,
  paraGraphJson,
  ROTULO_BLOCO,
  TIPOS_BLOCO,
  tipoPorta,
  type BlocoNode,
  type MapaTags,
} from "./graph";

/**
 * Blocos de Barramento (ADR-042): `bus_publish` (Barramento-Publicar, sem saída) e
 * `bus_subscribe` (Barramento-Assinar, sem entrada) trocam uma variável entre FLOWS
 * diferentes pelo Redis. Config é só `key`; sem campo de tempo — a validade do assinante é
 * derivada no servidor (3 × Ts do publicador, D4).
 */

const POS = { x: 0, y: 0 };
const TAGS: MapaTags = new Map();

function barramento(tipo: "bus_publish" | "bus_subscribe", id = "b1", ordem = 2): BlocoNode {
  return criarBloco(tipo, id, POS, ordem);
}

// --------------------------------------------------------------------------------------
// Paleta e portas
// --------------------------------------------------------------------------------------

test("os dois blocos de barramento estão na paleta com rótulo em pt-BR", () => {
  expect(TIPOS_BLOCO).toContain("bus_publish");
  expect(TIPOS_BLOCO).toContain("bus_subscribe");
  expect(ROTULO_BLOCO.bus_publish).toBe("Barramento-Publicar");
  expect(ROTULO_BLOCO.bus_subscribe).toBe("Barramento-Assinar");
});

test("bus_publish tem só entrada 'in', nenhuma saída", () => {
  const no = barramento("bus_publish");

  expect(handlesEntrada(no)).toEqual(["in"]);
  expect(handlesSaida(no)).toEqual([]);
});

test("bus_subscribe tem só saída 'out', nenhuma entrada", () => {
  const no = barramento("bus_subscribe");

  expect(handlesEntrada(no)).toEqual([]);
  expect(handlesSaida(no)).toEqual(["out"]);
});

test("as portas dos dois blocos de barramento são bivalentes (ADR-042 D7)", () => {
  expect(tipoPorta(barramento("bus_publish"), TAGS)).toBe("bivalente");
  expect(tipoPorta(barramento("bus_subscribe"), TAGS)).toBe("bivalente");
});

// --------------------------------------------------------------------------------------
// Config: defaults, serialização e leitura
// --------------------------------------------------------------------------------------

test("os dois nascem com key vazia", () => {
  const publicar = barramento("bus_publish");
  const assinar = barramento("bus_subscribe");
  if (publicar.type !== "bus_publish" || assinar.type !== "bus_subscribe") {
    throw new Error("tipo preservado");
  }

  expect(publicar.data.key).toBe("");
  expect(assinar.data.key).toBe("");
});

test("round-trip preserva a key dos dois blocos de barramento", () => {
  const publicar = barramento("bus_publish", "bp1", 1);
  const assinar = barramento("bus_subscribe", "bs1", 2);
  if (publicar.type !== "bus_publish" || assinar.type !== "bus_subscribe") {
    throw new Error("tipo preservado");
  }
  const nos: BlocoNode[] = [
    { ...publicar, data: { ...publicar.data, key: "temperatura_reator_1", label: "Publica T1" } },
    { ...assinar, data: { ...assinar.data, key: "temperatura_reator_1", label: "Assina T1" } },
  ];

  const lido = deGraphJson(paraGraphJson(nos, []));

  expect(lido.nodes).toEqual(nos);
});

test("key corrompida no graph_json cai no padrão '' em vez de propagar o tipo errado", () => {
  const bruto = {
    nodes: [
      { id: "bp1", type: "bus_publish", position: POS, data: { exec_order: 1, label: "", key: 42 } },
      {
        id: "bs1",
        type: "bus_subscribe",
        position: POS,
        data: { exec_order: 2, label: "", key: null },
      },
    ],
    edges: [],
  };

  const { nodes } = deGraphJson(bruto);

  const [publicar, assinar] = nodes;
  if (publicar.type !== "bus_publish" || assinar.type !== "bus_subscribe") {
    throw new Error("tipo preservado");
  }
  expect(publicar.data.key).toBe("");
  expect(assinar.data.key).toBe("");
});

test("data serializado carrega só as chaves que o servidor aceita", () => {
  const { nodes } = paraGraphJson(
    [barramento("bus_publish", "bp1", 1), barramento("bus_subscribe", "bs1", 2)],
    [],
  );

  expect(Object.keys(nodes[0].data).sort()).toEqual(["exec_order", "key", "label"]);
  expect(Object.keys(nodes[1].data).sort()).toEqual(["exec_order", "key", "label"]);
});
