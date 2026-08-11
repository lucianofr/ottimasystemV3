import { expect, test } from "@playwright/test";

import { agruparMpcsPorFlow } from "./HomePage";

/**
 * `agruparMpcsPorFlow` (tarefa 3.2 do plano F5b) — única lógica pura da visão geral: agrupa a
 * projeção de `GET /api/operate/mpcs` por `flow_id` para o atalho de operação; um flow sem
 * bloco MPC não aparece na saída (a Home só mostra atalho onde há MPC).
 */

function mpc(overrides: { flow_id: number; block_id: string }) {
  return {
    flow_id: overrides.flow_id,
    flow_name: `flow-${overrides.flow_id}`,
    flow_ts_seconds: 1,
    block_id: overrides.block_id,
    name: overrides.block_id,
    multiplier: 1,
    variables: { mvs: [], cvs: [], constraints: [], dvs: [] },
    horizons: { ts_mpc: 1, np: 1, nc: 1 },
  };
}

test("sem MPCs: mapa vazio", () => {
  expect(agruparMpcsPorFlow([]).size).toBe(0);
});

test("um MPC por flow: cada flow ganha uma entrada com 1 bloco", () => {
  const mpcs = [mpc({ flow_id: 1, block_id: "mpc-a" }), mpc({ flow_id: 2, block_id: "mpc-b" })];
  const agrupado = agruparMpcsPorFlow(mpcs);
  expect(agrupado.get(1)?.map((m) => m.block_id)).toEqual(["mpc-a"]);
  expect(agrupado.get(2)?.map((m) => m.block_id)).toEqual(["mpc-b"]);
});

test("dois MPCs no mesmo flow: os dois blocos ficam na mesma entrada, na ordem recebida", () => {
  const mpcs = [
    mpc({ flow_id: 7, block_id: "mpc-a" }),
    mpc({ flow_id: 7, block_id: "mpc-b" }),
  ];
  const agrupado = agruparMpcsPorFlow(mpcs);
  expect(agrupado.get(7)?.map((m) => m.block_id)).toEqual(["mpc-a", "mpc-b"]);
});

test("flow sem MPC não entra no mapa", () => {
  const agrupado = agruparMpcsPorFlow([mpc({ flow_id: 3, block_id: "mpc-a" })]);
  expect(agrupado.has(9)).toBe(false);
});
