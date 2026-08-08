import { expect, test } from "@playwright/test";

import { textoBotaoAtivar } from "./ConfirmarAtivacao";

/**
 * `textoBotaoAtivar` — tarefa 2.2 do plano F6b (spec §6.1-4, UX-07). O botão de confirmação de
 * Ativar carrega o verbo com a contagem de flows que serão parados — nunca um "OK" genérico.
 * As três formas são verbatim do plano/spec (`docs/specs/F6-portabilidade-hardening.md:311`),
 * testadas por igualdade exata, não por semelhança.
 */

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
