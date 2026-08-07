import { expect, test } from "@playwright/test";

import type { CondicaoAtiva } from "./alarmes";
import { contarPorSeveridade } from "./AnnunciatorBar";

/**
 * `contarPorSeveridade` (tarefa 2.4) — única lógica pura extraída da faixa anunciadora: soma
 * condições por severidade para os badges do resumo (spec F5 §7.2-4).
 */

function condicao(severity: CondicaoAtiva["severity"]): CondicaoAtiva {
  return {
    familia: "estado",
    kind: "mpc_solver_error",
    origin: "flow:1/block:mpc",
    desde: "2026-01-01T00:00:00.000Z",
    severity,
    message: "mensagem",
  };
}

test("sem condições: as duas contagens ficam em zero", () => {
  expect(contarPorSeveridade([])).toEqual({ warning: 0, alarm: 0 });
});

test("mistura de severidades: cada uma soma na própria chave", () => {
  const condicoes = [condicao("alarm"), condicao("warning"), condicao("alarm")];
  expect(contarPorSeveridade(condicoes)).toEqual({ warning: 1, alarm: 2 });
});
