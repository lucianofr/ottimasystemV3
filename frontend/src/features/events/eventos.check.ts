import { expect, test } from "@playwright/test";

import type { ConnectionOut, EventOut, FlowOut } from "../../lib/api";
import {
  calcularEventosVisiveis,
  casaFiltros,
  chaveEvento,
  origensConhecidas,
  temPeriodo,
  type FiltrosEventos,
  type MpcNodeOut,
} from "./eventos";

/**
 * Lógica pura de filtro/prepend/origens da página `/eventos` (tarefa 3.3, spec F5 §7.5;
 * decisão A-13; RF-803; F5R-24). Casos: `casaFiltros` (severidade/origem por igualdade
 * exata — a API nunca aceita texto livre), `temPeriodo` (gate do prepend), 
 * `calcularEventosVisiveis` (com período = consulta histórica pura, sem período = prepend
 * ao vivo com marca de recém-chegado, sem duplicar o que já veio da REST), e
 * `origensConhecidas` (select montado de flows + mpcs + conexões + origens distintas do
 * resultado carregado).
 */

function evento(parcial: Partial<EventOut> = {}): EventOut {
  return {
    ts: parcial.ts ?? "2026-01-01T00:00:00.000Z",
    severity: parcial.severity ?? "info",
    origin: parcial.origin ?? "conn:1",
    message: parcial.message ?? "mensagem padrão",
    payload: parcial.payload ?? {},
  };
}

const SEM_FILTRO: FiltrosEventos = { severity: null, origin: null, start: null, end: null };

function flow(id: number, name: string): FlowOut {
  return {
    id,
    project_id: 1,
    name,
    ts_seconds: 1,
    desired_state: "running",
    updated_at: "2026-01-01T00:00:00.000Z",
  };
}

function mpc(flowId: number, flowName: string, blockId: string, name: string): MpcNodeOut {
  return {
    flow_id: flowId,
    flow_name: flowName,
    flow_ts_seconds: 1,
    block_id: blockId,
    name,
    multiplier: 1,
    variables: { mvs: [], cvs: [], constraints: [], dvs: [] },
  };
}

function conexao(id: number, name: string): ConnectionOut {
  return {
    name,
    endpoint: "opc.tcp://host:4840",
    security_policy: "none",
    security_mode: "none",
    auth_mode: "anonymous",
    watchdog_period_ms: 1500,
    id,
    project_id: 1,
    has_password: false,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
  };
}

// --------------------------------------------------------------------------------- casaFiltros

test("casaFiltros: sem severidade/origem no filtro, qualquer evento casa", () => {
  expect(casaFiltros(evento({ severity: "alarm", origin: "conn:1" }), SEM_FILTRO)).toBe(true);
});

test("casaFiltros: severidade divergente não casa; igual casa", () => {
  const filtros = { severity: "warning" as const, origin: null };
  expect(casaFiltros(evento({ severity: "alarm" }), filtros)).toBe(false);
  expect(casaFiltros(evento({ severity: "warning" }), filtros)).toBe(true);
});

test("casaFiltros: origem por igualdade exata (nunca substring)", () => {
  const filtros = { severity: null, origin: "conn:1" };
  expect(casaFiltros(evento({ origin: "conn:12" }), filtros)).toBe(false);
  expect(casaFiltros(evento({ origin: "conn:1" }), filtros)).toBe(true);
});

// ---------------------------------------------------------------------------------- temPeriodo

test("temPeriodo: falso sem início/fim, verdadeiro com qualquer um dos dois", () => {
  expect(temPeriodo(SEM_FILTRO)).toBe(false);
  expect(temPeriodo({ ...SEM_FILTRO, start: "2026-01-01T00:00" })).toBe(true);
  expect(temPeriodo({ ...SEM_FILTRO, end: "2026-01-02T00:00" })).toBe(true);
});

// --------------------------------------------------------------------- calcularEventosVisiveis

test("com período ativo: histórico puro, sem prepend mesmo com evento ao vivo casando", () => {
  const historico = [evento({ ts: "2026-01-01T00:00:00.000Z", message: "antigo" })];
  const aoVivo = [evento({ ts: "2026-01-01T01:00:00.000Z", message: "novo" })];
  const filtros: FiltrosEventos = { ...SEM_FILTRO, start: "2026-01-01T00:00" };
  const resultado = calcularEventosVisiveis(historico, aoVivo, filtros);
  expect(resultado.eventos).toEqual(historico);
  expect(resultado.recentes.size).toBe(0);
});

test("sem período: evento ao vivo que casa os filtros entra no topo, marcado como recente", () => {
  const historico = [evento({ ts: "2026-01-01T00:00:00.000Z", message: "antigo" })];
  const novo = evento({ ts: "2026-01-01T01:00:00.000Z", message: "novo" });
  const resultado = calcularEventosVisiveis(historico, [novo], SEM_FILTRO);
  expect(resultado.eventos).toEqual([novo, ...historico]);
  expect(resultado.recentes.has(chaveEvento(novo))).toBe(true);
});

test("sem período: evento ao vivo que não casa a severidade filtrada não entra", () => {
  const historico = [evento({ ts: "2026-01-01T00:00:00.000Z" })];
  const foraDoFiltro = evento({ ts: "2026-01-01T01:00:00.000Z", severity: "alarm" });
  const filtros: FiltrosEventos = { ...SEM_FILTRO, severity: "warning" };
  const resultado = calcularEventosVisiveis(historico, [foraDoFiltro], filtros);
  expect(resultado.eventos).toEqual(historico);
  expect(resultado.recentes.size).toBe(0);
});

test("sem período: evento ao vivo já presente no histórico não duplica nem vira 'recente'", () => {
  const jaCarregado = evento({ ts: "2026-01-01T00:00:00.000Z", message: "já veio pela REST" });
  const resultado = calcularEventosVisiveis([jaCarregado], [jaCarregado], SEM_FILTRO);
  expect(resultado.eventos).toEqual([jaCarregado]);
  expect(resultado.recentes.size).toBe(0);
});

test("sem período: múltiplos eventos ao vivo entram na ordem ts desc que já chegam (mais novo primeiro)", () => {
  const historico = [evento({ ts: "2026-01-01T00:00:00.000Z", message: "antigo" })];
  const maisNovo = evento({ ts: "2026-01-01T02:00:00.000Z", message: "mais novo" });
  const meioTermo = evento({ ts: "2026-01-01T01:00:00.000Z", message: "meio termo" });
  // aoVivo já chega mais-novo-primeiro (mesma ordem de CanalAoVivo.tsx)
  const resultado = calcularEventosVisiveis(historico, [maisNovo, meioTermo], SEM_FILTRO);
  expect(resultado.eventos).toEqual([maisNovo, meioTermo, ...historico]);
  expect(resultado.recentes).toEqual(new Set([chaveEvento(maisNovo), chaveEvento(meioTermo)]));
});

// -------------------------------------------------------------------------- origensConhecidas

test("origensConhecidas: monta a partir de flows/mpcs/conexões com rótulo amigável", () => {
  const opcoes = origensConhecidas(
    [flow(7, "FlowA")],
    [mpc(7, "FlowA", "mpc1", "Reator")],
    [conexao(3, "PLC-Linha1")],
    [],
  );
  expect(opcoes).toContainEqual({ value: "flow:7", rotulo: "FlowA" });
  expect(opcoes).toContainEqual({ value: "flow:7/block:mpc1", rotulo: "FlowA - Reator" });
  expect(opcoes).toContainEqual({ value: "conn:3", rotulo: "PLC-Linha1" });
});

test("origensConhecidas: origem desconhecida do resultado carregado entra com rótulo = origem crua, sem duplicar a conhecida", () => {
  const opcoes = origensConhecidas(
    [flow(7, "FlowA")],
    [],
    [],
    [evento({ origin: "flow:7" }), evento({ origin: "user:1" })],
  );
  expect(opcoes.filter((o) => o.value === "flow:7")).toEqual([{ value: "flow:7", rotulo: "FlowA" }]);
  expect(opcoes).toContainEqual({ value: "user:1", rotulo: "user:1" });
});

test("origensConhecidas: ordenação alfabética por rótulo (pt-BR)", () => {
  const opcoes = origensConhecidas([flow(2, "Zebra"), flow(1, "Alfa")], [], [], []);
  expect(opcoes.map((o) => o.rotulo)).toEqual(["Alfa", "Zebra"]);
});
