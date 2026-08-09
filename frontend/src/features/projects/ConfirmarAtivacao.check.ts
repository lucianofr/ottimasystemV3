import { expect, test } from "@playwright/test";

import { contarFlowsRodando, textoBotaoAtivar } from "./ConfirmarAtivacao";

/**
 * `contarFlowsRodando`/`textoBotaoAtivar` — tarefa 2.2 do plano F6b (spec §6.1-4, UX-07,
 * fix round 2/5). O botão de confirmação de Ativar carrega o verbo com a contagem de flows
 * que **de fato vão parar** — só os com `desired_state === "running"` (spec §6.1-4 governa
 * sobre o parêntese do plano; o backend confirma em `flow-runtime/supervisor.py:502-507`,
 * `on_project_activated` itera só os runtimes rodando). Nunca um "OK" genérico. As três
 * formas são verbatim do plano/spec (`docs/specs/F6-portabilidade-hardening.md:311`),
 * testadas por igualdade exata, não por semelhança.
 */

function flow(desiredState: "running" | "stopped") {
  return { desired_state: desiredState };
}

test("zero flows degrada para 'Ativar' sem contagem (UX-07)", () => {
  expect(textoBotaoAtivar(0)).toBe("Ativar");
});

test("um flow usa singular: 'Ativar e parar 1 flow'", () => {
  expect(textoBotaoAtivar(1)).toBe("Ativar e parar 1 flow");
});

test("dois ou mais flows usam plural com a contagem: 'Ativar e parar N flows'", () => {
  expect(textoBotaoAtivar(2)).toBe("Ativar e parar 2 flows");
  expect(textoBotaoAtivar(11)).toBe("Ativar e parar 11 flows");
});

test("conta só os flows com desired_state 'running' — os parados não entram na contagem", () => {
  expect(contarFlowsRodando([flow("running"), flow("stopped"), flow("running")])).toBe(2);
  expect(contarFlowsRodando([flow("stopped"), flow("stopped")])).toBe(0);
  expect(contarFlowsRodando([])).toBe(0);
});

test("N flows totais, M rodando: o texto do botão usa M, não N — o caso que separa as duas leituras da spec/plano", () => {
  const flows = [flow("stopped"), flow("stopped"), flow("running"), flow("stopped")];
  expect(contarFlowsRodando(flows)).toBe(1);
  expect(textoBotaoAtivar(contarFlowsRodando(flows))).toBe("Ativar e parar 1 flow");
});

test("projeto com flows cadastrados mas todos parados: zero rodando degrada para 'Ativar', não 'Ativar e parar 0 flows'", () => {
  const flows = [flow("stopped"), flow("stopped"), flow("stopped")];
  expect(contarFlowsRodando(flows)).toBe(0);
  expect(textoBotaoAtivar(contarFlowsRodando(flows))).toBe("Ativar");
});
