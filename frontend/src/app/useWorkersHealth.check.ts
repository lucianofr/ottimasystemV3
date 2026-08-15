import { expect, test } from "@playwright/test";

import { derivarLampadas, type WorkersHealth } from "./useWorkersHealth";

/**
 * `derivarLampadas` (tarefa 3.2 do plano F5b) — única lógica pura da lâmpada de workers: fixa
 * as 4 entradas na ordem opc_worker/flow_runtime/recorder/calc_worker e traduz `up` em rótulo +
 * estado textual (Regra do Canal Redundante, DESIGN.md §Colors), independente do que mais o
 * agregador (`GET /api/health/workers`) trouxer em cada worker.
 */

function saude(overrides: Partial<WorkersHealth> = {}): WorkersHealth {
  const base: WorkersHealth = {
    opc_worker: { up: true },
    flow_runtime: { up: true },
    recorder: { up: true },
    calc_worker: { up: true },
  };
  return { ...base, ...overrides };
}

test("sem resposta ainda: as 4 lâmpadas ficam indisponíveis, nunca somem", () => {
  expect(derivarLampadas(undefined)).toEqual([
    { id: "opc_worker", rotulo: "OPC Worker", estado: "Indisponível", ativo: false },
    { id: "flow_runtime", rotulo: "Flow Runtime", estado: "Indisponível", ativo: false },
    { id: "recorder", rotulo: "Recorder", estado: "Indisponível", ativo: false },
    { id: "calc_worker", rotulo: "Calc Worker", estado: "Indisponível", ativo: false },
  ]);
});

test("todos up: as 4 ficam ativas, na ordem opc_worker/flow_runtime/recorder/calc_worker", () => {
  const lampadas = derivarLampadas(saude());
  expect(lampadas.map((l) => l.id)).toEqual([
    "opc_worker",
    "flow_runtime",
    "recorder",
    "calc_worker",
  ]);
  expect(lampadas.every((l) => l.ativo && l.estado === "Ativo")).toBe(true);
});

test("um worker down: só a lâmpada dele muda, com rótulo textual junto (não só cor)", () => {
  const lampadas = derivarLampadas(saude({ recorder: { up: false } }));
  expect(lampadas.find((l) => l.id === "recorder")).toEqual({
    id: "recorder",
    rotulo: "Recorder",
    estado: "Indisponível",
    ativo: false,
  });
  expect(lampadas.filter((l) => l.ativo).map((l) => l.id)).toEqual([
    "opc_worker",
    "flow_runtime",
    "calc_worker",
  ]);
});

test("corpo extra do worker (status/service/version/connections) não interfere na derivação", () => {
  const lampadas = derivarLampadas(
    saude({ opc_worker: { up: true, status: "ok", service: "opc-worker", connections: {} } }),
  );
  expect(lampadas.find((l) => l.id === "opc_worker")?.ativo).toBe(true);
});
