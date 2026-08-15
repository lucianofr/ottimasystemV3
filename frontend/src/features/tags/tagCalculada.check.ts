import { expect, test } from "@playwright/test";

import type { TagOut } from "../../lib/api";
import {
  eCalculada,
  mover,
  rotuloEntrada,
  tagsElegiveis,
  validarTagCalculada,
  type ValoresTagCalculada,
} from "./tagCalculada";

function tag(parcial: Partial<TagOut> = {}): TagOut {
  return {
    id: 1,
    connection_id: 10,
    name: "TT-101",
    node_id: "ns=2;s=TT101",
    project_id: null,
    direction: "r",
    data_type: "float",
    eu: "degC",
    description: "",
    created_at: "2026-08-04T12:00:00Z",
    updated_at: "2026-08-04T12:00:00Z",
    ...parcial,
  };
}

/** Tag calculada mínima: sem conexão, com `project_id` (ADR-033 D1). */
function tagCalc(parcial: Partial<TagOut> = {}): TagOut {
  return tag({ id: 900, connection_id: null, node_id: null, project_id: 1, name: "CALC-1", ...parcial });
}

function valores(parcial: Partial<ValoresTagCalculada> = {}): ValoresTagCalculada {
  return { name: "Vazão total", code: "OUT = IN1 + IN2", inputTagIds: [1, 2], ...parcial };
}

test("rotuloEntrada numera a partir de 1: índice 0 vira IN1, índice 7 vira IN8", () => {
  expect(rotuloEntrada(0)).toBe("IN1");
  expect(rotuloEntrada(7)).toBe("IN8");
});

test("eCalculada é verdadeira só para uma linha de tags sem connection_id", () => {
  expect(eCalculada(tag())).toBe(false);
  expect(eCalculada(tagCalc())).toBe(true);
});

test("tagsElegiveis inclui tags OPC de conexões do projeto ativo e tags calculadas do próprio projeto", () => {
  const opcDoProjeto = tag({ id: 1, connection_id: 10 });
  const opcDeOutraConexao = tag({ id: 2, connection_id: 99 });
  const calcDoProjeto = tagCalc({ id: 3, project_id: 5 });
  const calcDeOutroProjeto = tagCalc({ id: 4, project_id: 6 });
  const conexoesDoProjeto = new Set([10]);

  const resultado = tagsElegiveis(
    [opcDoProjeto, opcDeOutraConexao, calcDoProjeto, calcDeOutroProjeto],
    5,
    conexoesDoProjeto,
    null,
  );

  expect(resultado.map((t) => t.id)).toEqual([1, 3]);
});

/** Auto-referência é recusada pelo banco (`calculated_tag_inputs.source_tag_id <> calc_tag_id`)
 *  — a tag em edição nunca pode se escolher como entrada, mesmo sendo do próprio projeto. */
test("tagsElegiveis exclui a própria tag em edição mesmo quando ela seria elegível por projeto", () => {
  const calc = tagCalc({ id: 3, project_id: 5 });
  const outraCalc = tagCalc({ id: 4, project_id: 5 });

  const resultado = tagsElegiveis([calc, outraCalc], 5, new Set(), 3);

  expect(resultado.map((t) => t.id)).toEqual([4]);
});

test("mover reordena imutavelmente: array original não é alterado", () => {
  const original = ["a", "b", "c"];

  const resultado = mover(original, 0, 2);

  expect(resultado).toEqual(["b", "c", "a"]);
  expect(original).toEqual(["a", "b", "c"]);
});

test("mover subir o primeiro item (destino negativo) devolve a lista sem alteração", () => {
  expect(mover(["a", "b", "c"], 0, -1)).toEqual(["a", "b", "c"]);
});

test("mover descer o último item (destino além do fim) devolve a lista sem alteração", () => {
  expect(mover(["a", "b", "c"], 2, 3)).toEqual(["a", "b", "c"]);
});

test("validarTagCalculada aprova valores completos sem entradas repetidas", () => {
  expect(validarTagCalculada(valores())).toEqual([]);
});

test("validarTagCalculada exige nome", () => {
  expect(validarTagCalculada(valores({ name: "   " }))).toContain("Nome é obrigatório");
});

test("validarTagCalculada exige script", () => {
  expect(validarTagCalculada(valores({ code: "" }))).toContain("Script é obrigatório");
});

test("validarTagCalculada recusa a mesma tag ocupando duas posições", () => {
  expect(validarTagCalculada(valores({ inputTagIds: [1, 1] }))).toContain(
    "A mesma tag não pode ocupar duas entradas",
  );
});

test("validarTagCalculada recusa mais de 8 entradas", () => {
  const nove = [1, 2, 3, 4, 5, 6, 7, 8, 9];

  expect(validarTagCalculada(valores({ inputTagIds: nove }))).toContain("No máximo 8 entradas");
});
