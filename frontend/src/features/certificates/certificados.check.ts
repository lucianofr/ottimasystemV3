import { expect, test } from "@playwright/test";

import type { ConnectionOut } from "../../lib/api";
import { conexoesAfetadasPorRegeracao } from "./certificados";

/**
 * `conexoesAfetadasPorRegeracao` — tarefa 3.1 do plano F6b (spec §6.2-1, SEC-06).
 *
 * Domínio de `security_policy` (2 valores) x `auth_mode` (3 valores) enumerado de
 * `frontend/src/lib/api-types.ts:722,734` — não por amostra. `security_mode` não entra na
 * fórmula (a spec só cita `security_policy`/`auth_mode`), então fica fixo em "none" nos
 * casos e a `id`/`name` variam só para conferir que a função devolve o objeto inteiro,
 * não uma projeção.
 */
type ConexaoTeste = Pick<ConnectionOut, "id" | "name" | "security_policy" | "auth_mode">;

const POLICIES: ConexaoTeste["security_policy"][] = ["none", "basic256sha256"];
const AUTH_MODES: ConexaoTeste["auth_mode"][] = ["anonymous", "user_password", "certificate"];

/** Fórmula transcrita da spec, independente da implementação sob teste. */
function esperado(policy: ConexaoTeste["security_policy"], mode: ConexaoTeste["auth_mode"]): boolean {
  return policy !== "none" || mode === "certificate";
}

test("tabela-verdade completa: 2(security_policy) x 3(auth_mode) = 6 casos batem com §6.2-1/SEC-06", () => {
  let casos = 0;
  for (const security_policy of POLICIES) {
    for (const auth_mode of AUTH_MODES) {
      casos += 1;
      const conexao: ConexaoTeste = { id: casos, name: `conexao-${String(casos)}`, security_policy, auth_mode };
      const resultado = conexoesAfetadasPorRegeracao([conexao]);
      expect(resultado).toEqual(esperado(security_policy, auth_mode) ? [conexao] : []);
    }
  }
  expect(casos).toBe(6);
});

test("inclui security_policy != none (basic256sha256, anonymous)", () => {
  const conexao: ConexaoTeste = { id: 1, name: "c1", security_policy: "basic256sha256", auth_mode: "anonymous" };
  expect(conexoesAfetadasPorRegeracao([conexao])).toEqual([conexao]);
});

test("inclui auth_mode == certificate com policy none", () => {
  const conexao: ConexaoTeste = { id: 2, name: "c2", security_policy: "none", auth_mode: "certificate" };
  expect(conexoesAfetadasPorRegeracao([conexao])).toEqual([conexao]);
});

test("exclui anônima sem segurança (none / anonymous)", () => {
  const conexao: ConexaoTeste = { id: 3, name: "c3", security_policy: "none", auth_mode: "anonymous" };
  expect(conexoesAfetadasPorRegeracao([conexao])).toEqual([]);
});

test("preserva ordem e devolve os objetos inteiros da lista original, não uma projeção", () => {
  const afetada: ConexaoTeste = { id: 10, name: "afetada", security_policy: "basic256sha256", auth_mode: "anonymous" };
  const neutra: ConexaoTeste = { id: 11, name: "neutra", security_policy: "none", auth_mode: "anonymous" };
  const outraAfetada: ConexaoTeste = { id: 12, name: "outra", security_policy: "none", auth_mode: "certificate" };
  expect(conexoesAfetadasPorRegeracao([afetada, neutra, outraAfetada])).toEqual([afetada, outraAfetada]);
});

test("lista vazia devolve lista vazia", () => {
  expect(conexoesAfetadasPorRegeracao([])).toEqual([]);
});
