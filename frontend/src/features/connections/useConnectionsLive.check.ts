import { expect, test } from "@playwright/test";

import { derivarConectadas } from "./useConnectionsLive";

/**
 * `derivarConectadas` — única lógica pura da bolinha de conexão viva: traduz o `state` da
 * máquina do opc-worker (connecting/up/failed) em booleano e só confia no dado quando o
 * worker respondeu (`up: true`). Worker em queda devolve mapa vazio: a célula então cai no
 * estado derivado de eventos, nunca inventa "Conectado".
 */

type Saude = Parameters<typeof derivarConectadas>[0];

test("sem resposta ainda: mapa vazio, célula fica no estado de eventos", () => {
  expect(derivarConectadas(undefined).size).toBe(0);
});

test("worker em queda: estado da conexão é desconhecido, não 'desconectada'", () => {
  const saude: Saude = { opc_worker: { up: false, connections: { 587: { state: "up" } } } };
  expect(derivarConectadas(saude).size).toBe(0);
});

test("state 'up' marca a conexão como viva", () => {
  const saude: Saude = { opc_worker: { up: true, connections: { 587: { state: "up" } } } };
  expect(derivarConectadas(saude).get(587)).toBe(true);
});

test("'connecting' e 'failed' marcam como não-viva (chave presente, falsa)", () => {
  const saude: Saude = {
    opc_worker: {
      up: true,
      connections: { 587: { state: "connecting" }, 1: { state: "failed" } },
    },
  };
  const mapa = derivarConectadas(saude);
  expect(mapa.get(587)).toBe(false);
  expect(mapa.get(1)).toBe(false);
});
