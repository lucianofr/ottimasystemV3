import { expect, test } from "@playwright/test";

import { PORT_CONTRACTS, type ContratoPortaDinamicaSensor } from "../../lib/contracts.gen";
import {
  criarBloco,
  deGraphJson,
  euDeSaidaPorNo,
  handlesEntrada,
  handlesSaida,
  MAX_ENTRADAS_SENSOR_VIRTUAL,
  motivoRecusa,
  paraGraphJson,
  podarArestasDoBloco,
  ROTULO_BLOCO,
  TIPOS_BLOCO,
  tipoPorta,
  type BlocoEdge,
  type BlocoNode,
  type MapaTags,
  type TipoSensorVirtual,
} from "./graph";
import { REGISTRO_BLOCO } from "./registro";

/**
 * Blocos de sensor virtual no modelo do editor (RF-301, RF-581, ADR-046).
 *
 * O canvas só edita o grafo (ADR-005): aqui se confere paleta, portas `IN1..INn` → `out`,
 * poda de arestas, tipagem na conexão e a leitura/gravação do `graph_json`. O modelo NÃO está
 * na config — o vínculo bloco → modelo mora em tabela (SPEC_SENSOR_VIRTUAL §5.1).
 */

const POS = { x: 0, y: 0 };

const TIPOS: readonly TipoSensorVirtual[] = ["soft_sensor_pls", "soft_sensor_esn", "soft_sensor_lstm"];

const ROTULOS: Record<TipoSensorVirtual, string> = {
  soft_sensor_pls: "Sensor virtual PLS",
  soft_sensor_esn: "Sensor virtual ESN",
  soft_sensor_lstm: "Sensor virtual LSTM",
};

const TAGS: MapaTags = new Map([
  [10, "float"],
  [11, "bool"],
]);

function sensor(tipo: TipoSensorVirtual, nInputs: number, outputEu = ""): BlocoNode {
  return {
    id: "s1",
    type: tipo,
    position: POS,
    data: { exec_order: 2, label: "", n_inputs: nInputs, output_eu: outputEu },
  };
}

function leitura(id: string, tag: number): BlocoNode {
  return { id, type: "opc_read", position: POS, data: { exec_order: 1, label: "", tag_id: tag } };
}

function escrita(id: string, tag: number): BlocoNode {
  return { id, type: "opc_write", position: POS, data: { exec_order: 3, label: "", tag_id: tag } };
}

function aresta(id: string, source: string, sourceHandle: string, target: string, targetHandle: string): BlocoEdge {
  return { id, source, sourceHandle, target, targetHandle };
}

// --------------------------------------------------------------------------------------
// Paleta e defaults
// --------------------------------------------------------------------------------------

for (const tipo of TIPOS) {
  test(`${tipo} está na paleta com rótulo e descrição em pt-BR`, () => {
    expect(TIPOS_BLOCO).toContain(tipo);
    expect(ROTULO_BLOCO[tipo]).toBe(ROTULOS[tipo]);
    expect(REGISTRO_BLOCO[tipo].descricao).toBe("Estima uma variável de laboratório por modelo treinado");
  });

  test(`criarBloco(${tipo}) nasce com 2 entradas e EU vazia`, () => {
    const no = criarBloco(tipo, "s1", POS, 4);

    expect(no.type).toBe(tipo);
    expect(no.data.exec_order).toBe(4);
    expect(no.data).toMatchObject({ n_inputs: 2, output_eu: "" });
  });

  test(`${tipo}: portas de entrada seguem n_inputs`, () => {
    expect(handlesEntrada(sensor(tipo, 3))).toEqual(["IN1", "IN2", "IN3"]);
    expect(handlesEntrada(sensor(tipo, 1))).toEqual(["IN1"]);
  });

  test(`${tipo}: saída é sempre 'out'`, () => {
    expect(handlesSaida(sensor(tipo, 1))).toEqual(["out"]);
    expect(handlesSaida(sensor(tipo, 7))).toEqual(["out"]);
  });

  test(`${tipo}: reduzir n_inputs remove as arestas das portas que sumiram e preserva a saída`, () => {
    const arestas = [
      aresta("e1", "r1", "out", "s1", "IN1"),
      aresta("e2", "r2", "out", "s1", "IN2"),
      aresta("e3", "s1", "out", "w1", "in"),
    ];

    const podadas = podarArestasDoBloco(arestas, sensor(tipo, 1));

    expect(podadas.map((a) => a.id)).toEqual(["e1", "e3"]);
  });

  test(`${tipo}: portas são numéricas e a entrada booleana é recusada na conexão`, () => {
    expect(tipoPorta(sensor(tipo, 2), TAGS)).toBe("num");

    const motivo = motivoRecusa(
      { source: "r1", target: "s1", sourceHandle: "out", targetHandle: "IN1" },
      [leitura("r1", 11), sensor(tipo, 2)],
      [],
      TAGS,
    );

    expect(motivo).toContain("booleana");
  });

  test(`${tipo}: aceita tag numérica na entrada e escrita numérica na saída`, () => {
    const nos = [leitura("r1", 10), sensor(tipo, 2), escrita("w1", 10)];

    expect(
      motivoRecusa({ source: "r1", target: "s1", sourceHandle: "out", targetHandle: "IN2" }, nos, [], TAGS),
    ).toBeNull();
    expect(
      motivoRecusa({ source: "s1", target: "w1", sourceHandle: "out", targetHandle: "in" }, nos, [], TAGS),
    ).toBeNull();
  });
}

// --------------------------------------------------------------------------------------
// Teto do contrato
// --------------------------------------------------------------------------------------

test("teto de entradas vem do contrato e vale 32", () => {
  expect(MAX_ENTRADAS_SENSOR_VIRTUAL).toBe(32);
  for (const tipo of TIPOS) {
    const contrato = PORT_CONTRACTS[tipo] as ContratoPortaDinamicaSensor;
    expect(contrato.rules[0].max).toBe(MAX_ENTRADAS_SENSOR_VIRTUAL);
  }
});

// --------------------------------------------------------------------------------------
// graph_json: gravação e leitura
// --------------------------------------------------------------------------------------

test("graph_json: o bloco sobrevive à ida e volta sem perder config", () => {
  for (const tipo of TIPOS) {
    const no = sensor(tipo, 5, "ppm");

    const { nodes } = deGraphJson(paraGraphJson([no], []));

    expect(nodes).toEqual([no]);
  }
});

test("graph_json: n_inputs corrompido cai na faixa 1..teto e output_eu inválido vira vazio", () => {
  const lido = (n_inputs: unknown, output_eu: unknown): BlocoNode | undefined =>
    deGraphJson({
      nodes: [{ id: "s1", type: "soft_sensor_pls", position: POS, data: { exec_order: 1, n_inputs, output_eu } }],
      edges: [],
    }).nodes[0];

  expect(lido(0, "x")?.data).toMatchObject({ n_inputs: 1, output_eu: "x" });
  expect(lido(99, 5)?.data).toMatchObject({ n_inputs: MAX_ENTRADAS_SENSOR_VIRTUAL, output_eu: "" });
  expect(lido("três", undefined)?.data).toMatchObject({ n_inputs: 2, output_eu: "" });
});

// --------------------------------------------------------------------------------------
// EU da saída
// --------------------------------------------------------------------------------------

test("euDeSaidaPorNo: a unidade da saída do sensor chega à porta 'out'", () => {
  expect(euDeSaidaPorNo([sensor("soft_sensor_lstm", 2, "ppm")], new Map()).get("s1")).toEqual({ out: "ppm" });
});

test("euDeSaidaPorNo: sensor sem unidade fica fora do mapa", () => {
  expect(euDeSaidaPorNo([sensor("soft_sensor_pls", 2)], new Map()).has("s1")).toBe(false);
});
