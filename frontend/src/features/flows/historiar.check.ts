import { expect, test } from "@playwright/test";

import type { HistorizedVarOut } from "../../lib/api";
import { registroDoBloco, portasComAresta } from "./config/CamposHistoriar";
import type { BlocoEdge } from "./graph";

/**
 * Lógica pura da seção "Historiar portas" (ADR-041): quais portas já têm registro e quais
 * portas de ENTRADA têm aresta chegando (D7 — sem aresta, o runtime nunca produz valor e o
 * cadastro seria 86 mil NULLs/dia; o backend recusa com 422, o checkbox nasce desabilitado).
 */

function registro(blockId: string, port: string, tagId: number): HistorizedVarOut {
  return { tag_id: tagId, flow_id: 1, block_id: blockId, port, name: `f.${blockId}.${port}`, eu: "" };
}

function aresta(id: string, source: string, target: string, targetHandle: string): BlocoEdge {
  return { id, source, target, sourceHandle: "out", targetHandle };
}

// --------------------------------------------------------------------------------------
// registroDoBloco
// --------------------------------------------------------------------------------------

test("registroDoBloco: indexa só os registros do bloco pedido, por porta", () => {
  const registros = [registro("b1", "IN1", 10), registro("b1", "OUT1", 11), registro("b2", "IN1", 12)];
  const mapa = registroDoBloco(registros, "b1");
  expect(mapa.size).toBe(2);
  expect(mapa.get("IN1")?.tag_id).toBe(10);
  expect(mapa.get("OUT1")?.tag_id).toBe(11);
  expect(mapa.has("b2")).toBe(false);
});

test("registroDoBloco: bloco sem registro nenhum devolve mapa vazio", () => {
  expect(registroDoBloco([registro("b1", "IN1", 10)], "b2").size).toBe(0);
});

// --------------------------------------------------------------------------------------
// portasComAresta
// --------------------------------------------------------------------------------------

test("portasComAresta: porta de entrada com aresta chegando entra no conjunto", () => {
  const conjunto = portasComAresta([aresta("e1", "b0", "b1", "IN1")], "b1");
  expect(conjunto.has("IN1")).toBe(true);
});

test("portasComAresta: aresta de OUTRO bloco não conta, mesmo com o mesmo nome de porta", () => {
  const conjunto = portasComAresta([aresta("e1", "b0", "b2", "IN1")], "b1");
  expect(conjunto.has("IN1")).toBe(false);
});

test("portasComAresta: aresta SAINDO do bloco (bloco é a origem, não o alvo) não conta como entrada", () => {
  const conjunto = portasComAresta([aresta("e1", "b1", "b2", "IN1")], "b1");
  expect(conjunto.size).toBe(0);
});

test("portasComAresta: duas arestas para portas diferentes do mesmo bloco entram as duas", () => {
  const conjunto = portasComAresta(
    [aresta("e1", "b0", "b1", "IN1"), aresta("e2", "b0", "b1", "IN2")],
    "b1",
  );
  expect([...conjunto].sort()).toEqual(["IN1", "IN2"]);
});
