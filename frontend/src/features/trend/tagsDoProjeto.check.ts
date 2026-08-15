import { expect, test } from "@playwright/test";

import type { TagOut } from "../../lib/api";
import { tagDoProjeto } from "./tagsDoProjeto";

function tag(parcial: Partial<TagOut> = {}): TagOut {
  return {
    id: 1,
    connection_id: 10,
    name: "PV1",
    node_id: "ns=2;s=PV1",
    project_id: null,
    direction: "r",
    data_type: "float",
    eu: "°C",
    description: "",
    created_at: "2026-08-04T12:00:00Z",
    updated_at: "2026-08-04T12:00:00Z",
    ...parcial,
  };
}

const CONEXOES_DO_PROJETO = new Set([10, 20]);
const PROJETO_ATIVO = 7;

test("tag OPC de conexão do projeto ativo entra", () => {
  expect(tagDoProjeto(tag({ connection_id: 10 }), CONEXOES_DO_PROJETO, PROJETO_ATIVO)).toBe(true);
});

test("tag calculada do projeto ativo entra", () => {
  expect(
    tagDoProjeto(
      tag({ connection_id: null, project_id: PROJETO_ATIVO }),
      CONEXOES_DO_PROJETO,
      PROJETO_ATIVO,
    ),
  ).toBe(true);
});

test("tag calculada de outro projeto fica de fora", () => {
  expect(
    tagDoProjeto(tag({ connection_id: null, project_id: 99 }), CONEXOES_DO_PROJETO, PROJETO_ATIVO),
  ).toBe(false);
});

test("tag OPC de conexão fora do projeto fica de fora", () => {
  expect(tagDoProjeto(tag({ connection_id: 30 }), CONEXOES_DO_PROJETO, PROJETO_ATIVO)).toBe(false);
});
