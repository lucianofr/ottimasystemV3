import { expect, test } from "@playwright/test";

import type { MpcState, SstoRun } from "../../lib/contracts.gen";
import { ROTULO_STATUS_SSTO, resumoOtimizador } from "./resumoOtimizador";
import type { MpcNodeOut } from "./useMpcs";

/**
 * `resumoOtimizador` — mapper puro do card "Otimizador" (ADR-027 §9 estendido): filtra as
 * variáveis com `objective !== "none"` na ordem MV → CV → Restrição, pareia valor atual
 * (canal ao vivo) com alvo calculado (SSTO), e aplica a precedência WS > cold-start REST.
 */

function mpc(parPartial: Partial<MpcNodeOut["variables"]> = {}): MpcNodeOut {
  return {
    flow_id: 1,
    flow_name: "Flow",
    flow_ts_seconds: 1,
    block_id: "m1",
    name: "MPC",
    multiplier: 1,
    horizons: { ts_mpc: 1, np: 10, nc: 2 },
    variables: {
      mvs: [
        {
          id: "mv_a",
          name: "MV A",
          eu: "%",
          description: "",
          zero: 0,
          span: 100,
          limits: { min: 0, max: 100 },
          max_rate: 5,
          objective: "none",
        },
      ],
      cvs: [
        {
          id: "cv_a",
          name: "CV A",
          eu: "C",
          description: "",
          zero: 0,
          span: 100,
          sp_limits: { min: 0, max: 100 },
          remote_sp: false,
          objective: "none",
        },
      ],
      constraints: [
        {
          id: "co_a",
          name: "Restrição A",
          eu: "bar",
          description: "",
          zero: 0,
          span: 100,
          range: { low: 0, high: 10 },
          objective: "none",
        },
      ],
      dvs: [],
      ...parPartial,
    },
  };
}

function sstoRun(parcial: Partial<SstoRun> = {}): SstoRun {
  return {
    run_id: "run-1",
    config_hash: "a",
    model_hash: "b",
    status: "optimal",
    solver: "highs",
    solve_ms: 1,
    objective: -12.5,
    mv: {},
    cv_ss: {},
    bias: {},
    dv: {},
    costs: {},
    delta_mv: {},
    mv_target: {},
    cv_target: {},
    given_up: [],
    active_constraints: [],
    duals: {},
    ...parcial,
  };
}

function estado(parcial: Partial<MpcState> = {}): MpcState {
  return {
    ts: "2026-08-11T12:00:00.000Z",
    modes: { local_remote: "remote", man_auto: "auto" },
    status: { solver: "ok", overruns: 0, last_solve_ms: 1, armed: true, input_valid: true },
    vars: {},
    cost: 0,
    prediction: { ts: "2026-08-11T12:00:00.000Z", t: [], cv: [], mv: [] },
    ssto: null,
    ...parcial,
  };
}

test("sem variável otimizada: nenhuma linha (o card retorna null com isto)", () => {
  const { linhas } = resumoOtimizador(mpc(), undefined, null);
  expect(linhas).toEqual([]);
});

test("filtra none, ordena MV → CV → Restrição e pareia atual/alvo", () => {
  const definicao = mpc({
    mvs: [
      {
        id: "mv_a",
        name: "MV A",
        eu: "%",
        description: "",
        zero: 0,
        span: 100,
        limits: { min: 0, max: 100 },
        max_rate: 5,
        objective: "maximize",
      },
      {
        id: "mv_b",
        name: "MV B",
        eu: "%",
        description: "",
        zero: 0,
        span: 100,
        limits: { min: 0, max: 100 },
        max_rate: 5,
        objective: "none",
      },
    ],
    cvs: [
      {
        id: "cv_a",
        name: "CV A",
        eu: "C",
        description: "",
        zero: 0,
        span: 100,
        sp_limits: { min: 0, max: 100 },
        remote_sp: false,
        objective: "target",
      },
    ],
    constraints: [
      {
        id: "co_a",
        name: "Restrição A",
        eu: "bar",
        description: "",
        zero: 0,
        span: 100,
        range: { low: 0, high: 10 },
        objective: "minimize",
      },
    ],
  });
  const ao_vivo = estado({
    vars: {
      mv_a: { v: 55, sp: null, status: null },
      cv_a: { v: 70, sp: 60, status: null },
      co_a: { v: 5, sp: null, status: null },
    },
    ssto: sstoRun({ mv_target: { mv_a: 80 }, cv_target: { cv_a: 60, co_a: 2 } }),
  });

  const { linhas, ssto } = resumoOtimizador(definicao, ao_vivo, null);

  expect(linhas.map((l) => l.id)).toEqual(["mv_a", "cv_a", "co_a"]);
  expect(linhas[0]).toMatchObject({ rotuloObjetivo: "Maximizar", atual: 55, alvo: 80 });
  expect(linhas[1]).toMatchObject({ rotuloObjetivo: "Alvo (Target)", atual: 70, alvo: 60 });
  expect(linhas[2]).toMatchObject({ rotuloObjetivo: "Minimizar", atual: 5, alvo: 2 });
  expect(ssto?.status).toBe("optimal");
});

test("null-safe: sem mpcState e sem execução, atual e alvo são null e ssto é null", () => {
  const definicao = mpc({
    cvs: [
      {
        id: "cv_a",
        name: "CV A",
        eu: "C",
        description: "",
        zero: 0,
        span: 100,
        sp_limits: { min: 0, max: 100 },
        remote_sp: false,
        objective: "maximize",
      },
    ],
  });

  const { linhas, ssto } = resumoOtimizador(definicao, undefined, null);

  expect(ssto).toBeNull();
  expect(linhas).toHaveLength(1);
  expect(linhas[0].atual).toBeNull();
  expect(linhas[0].alvo).toBeNull();
});

test("precedência: ssto do canal ao vivo ganha do cold-start REST", () => {
  const definicao = mpc({
    cvs: [
      {
        id: "cv_a",
        name: "CV A",
        eu: "C",
        description: "",
        zero: 0,
        span: 100,
        sp_limits: { min: 0, max: 100 },
        remote_sp: false,
        objective: "maximize",
      },
    ],
  });
  const ws = sstoRun({ run_id: "ws", cv_target: { cv_a: 95 } });
  const rest = sstoRun({ run_id: "rest", cv_target: { cv_a: 90 } });

  expect(resumoOtimizador(definicao, estado({ ssto: ws }), rest).ssto?.run_id).toBe("ws");
  expect(resumoOtimizador(definicao, estado({ ssto: null }), rest).ssto?.run_id).toBe("rest");
});

test("desistências saem rotuladas pelo nome da variável (id como fallback)", () => {
  const definicao = mpc({
    cvs: [
      {
        id: "cv_a",
        name: "CV A",
        eu: "C",
        description: "",
        zero: 0,
        span: 100,
        sp_limits: { min: 0, max: 100 },
        remote_sp: false,
        objective: "maximize",
      },
    ],
  });
  const run = sstoRun({ given_up: ["cv_a", "co_desconhecida"] });

  const { desistencias } = resumoOtimizador(definicao, estado({ ssto: run }), null);

  expect(desistencias).toEqual(["CV A", "co_desconhecida"]);
});

test("ROTULO_STATUS_SSTO cobre os 5 status do contrato (rótulo pt-BR do badge)", () => {
  expect(ROTULO_STATUS_SSTO).toEqual({
    optimal: "Ótimo",
    relaxed: "Relaxado",
    infeasible: "Inviável",
    unbounded: "Ilimitado",
    error: "Erro",
  });
});
