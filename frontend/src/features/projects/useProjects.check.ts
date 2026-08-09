import { expect, test } from "@playwright/test";

import type { ProjectOut } from "../../lib/api";
import { CHAVE_PROJETOS, chavesInvalidadasPor, selecionarProjetoAtivo } from "./useProjects";

function projeto(id: number, isActive: boolean): ProjectOut {
  return {
    id,
    name: `Projeto ${String(id)}`,
    description: "",
    is_active: isActive,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

// ----------------------------------------------------------------------------------------
// Chave da lista (contrato entre tarefas do preâmbulo: `CHAVE_PROJETOS = ["projects"]`)
// ----------------------------------------------------------------------------------------

test("CHAVE_PROJETOS é a chave literal usada hoje em useConnections.ts:16", () => {
  expect(CHAVE_PROJETOS).toEqual(["projects"]);
});

// ----------------------------------------------------------------------------------------
// Seleção do projeto ativo (movida de useConnections.ts, um só ativo por instalação)
// ----------------------------------------------------------------------------------------

test("projeto ativo é o único com is_active true", () => {
  const projetos = [projeto(1, false), projeto(2, true), projeto(3, false)];
  expect(selecionarProjetoAtivo(projetos)?.id).toBe(2);
});

test("nenhum projeto ativo devolve null, não undefined nem o primeiro da lista", () => {
  const projetos = [projeto(1, false), projeto(2, false)];
  expect(selecionarProjetoAtivo(projetos)).toBeNull();
});

test("lista vazia (dia 1 da instalação) também devolve null", () => {
  expect(selecionarProjetoAtivo([])).toBeNull();
});

// ----------------------------------------------------------------------------------------
// Tabela de invalidação de cache (spec §6.1-8, F6R-11) — o que motiva a fase
// ----------------------------------------------------------------------------------------

test("criar, renomear e excluir só invalidam a lista de projetos", () => {
  for (const acao of ["criar", "renomear", "excluir"] as const) {
    expect(chavesInvalidadasPor(acao)).toEqual([["projects"]]);
  }
});

test("ativar invalida projects, connections, tags, flows e operate.mpcs — o recorte inteiro das telas de engenharia", () => {
  expect(chavesInvalidadasPor("ativar")).toEqual([
    ["projects"],
    ["connections"],
    ["tags"],
    ["flows"],
    ["operate", "mpcs"],
  ]);
});

test("importar invalida o mesmo conjunto de ativar (o projeto nasce inativo, mas a lista muda)", () => {
  expect(chavesInvalidadasPor("importar")).toEqual(chavesInvalidadasPor("ativar"));
});
