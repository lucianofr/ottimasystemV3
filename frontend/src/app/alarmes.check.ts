import { expect, test } from "@playwright/test";

import type { FlowStatus } from "../features/flows/useFlowStatus";
import type { MpcState } from "../lib/contracts.gen";
import { resolverAlarmes } from "./alarmes";
import type { EventMessage } from "./CanalAoVivo";

/**
 * `resolverAlarmes` (tarefa 2.1, spec F5 §7.2-1; decisão A-4; RF-705; ADR-020) — as 4
 * famílias que espelham o latch dos produtores: par de eventos, estado publicado, contador
 * publicado, TTL. Casos de §9.1: par por origem (2 origens independentes); estado publicado
 * cessa/não cessa; contador com `overruns` inalterado ×2 (e NÃO cessa com 1); TTL
 * expira/renova; sem estado da origem ⇒ ativa.
 */

function evento(
  kind: string,
  origin: string,
  parcial: {
    ts?: string;
    severity?: "info" | "warning" | "alarm";
    payload?: Record<string, unknown>;
  } = {},
): EventMessage {
  return {
    ts: parcial.ts ?? "2026-01-01T00:00:00.000Z",
    severity: parcial.severity ?? "alarm",
    origin,
    message: `mensagem de ${kind}`,
    payload: { kind, ...(parcial.payload ?? {}) },
  };
}

function flowStatus(overruns: number, ts: string): FlowStatus {
  return { state: "running", scan_ms: 10, overruns, ts, ports: {} };
}

function mpcState(parcial: Partial<MpcState["status"]> = {}): MpcState {
  return {
    ts: "2026-01-01T00:00:05.000Z",
    modes: { local_remote: "remote", man_auto: "auto" },
    status: {
      solver: "ok",
      overruns: 0,
      last_solve_ms: 1,
      armed: true,
      input_valid: true,
      ...parcial,
    },
    vars: {},
    cost: 0,
    prediction: { ts: "2026-01-01T00:00:05.000Z", t: [], cv: [], mv: [] },
    // Quadro sem SSTO (ADR-026): a camada de alvos não roda em todo ciclo, e o wire sempre
    // carrega o campo — nulo quando não houve execução.
    ssto: null,
  };
}

const SEM_FLOW_STATUS: ReadonlyMap<number, FlowStatus> = new Map();
const SEM_MPC_STATES: ReadonlyMap<string, MpcState> = new Map();
const AGORA = new Date("2026-01-01T01:00:00.000Z");

test("sem eventos: nenhuma condição ativa", () => {
  expect(resolverAlarmes([], SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toEqual([]);
});

// ----------------------------------------------------------------------------------------
// Família 1 — par de eventos
// ----------------------------------------------------------------------------------------

test("par de eventos: origem sem o par fica ativa, origem com o par cessa (2 origens independentes)", () => {
  const eventos = [
    // mais novo primeiro
    evento("comm_restored", "conn:2", { ts: "2026-01-01T00:00:10.000Z" }),
    evento("comm_failure", "conn:2", { ts: "2026-01-01T00:00:05.000Z" }),
    evento("comm_failure", "conn:1", { ts: "2026-01-01T00:00:01.000Z" }),
  ];

  expect(resolverAlarmes(eventos, SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toEqual([
    {
      familia: "par",
      kind: "comm_failure",
      origin: "conn:1",
      desde: "2026-01-01T00:00:01.000Z",
      severity: "alarm",
      message: "mensagem de comm_failure",
    },
  ]);
});

test("par de eventos: flow_failed fecha com flow_deployed da mesma origin (flow:<id> exato)", () => {
  const eventos = [
    evento("flow_deployed", "flow:4", { ts: "2026-01-01T00:00:10.000Z" }),
    evento("flow_failed", "flow:4", { ts: "2026-01-01T00:00:05.000Z" }),
  ];

  expect(resolverAlarmes(eventos, SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toEqual([]);
});

test("par de eventos: script_timeout e script_error fecham com script_recovered da mesma origin", () => {
  const eventos = [
    // origem b: fechada
    evento("script_recovered", "flow:1/block:b", { ts: "2026-01-01T00:00:10.000Z" }),
    evento("script_error", "flow:1/block:b", { ts: "2026-01-01T00:00:05.000Z" }),
    // origem a: ainda aberta
    evento("script_timeout", "flow:1/block:a", { ts: "2026-01-01T00:00:01.000Z" }),
  ];

  expect(resolverAlarmes(eventos, SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toEqual([
    {
      familia: "par",
      kind: "script_timeout",
      origin: "flow:1/block:a",
      desde: "2026-01-01T00:00:01.000Z",
      severity: "alarm",
      message: "mensagem de script_timeout",
    },
  ]);
});

// ----------------------------------------------------------------------------------------
// Família 2 — estado publicado
// ----------------------------------------------------------------------------------------

test("estado publicado: mpc_solver_error ativo sem estado (nunca silenciosa), ativo enquanto solver='error', cessa quando muda", () => {
  const evt = evento("mpc_solver_error", "flow:1/block:mpc", { ts: "2026-01-01T00:00:01.000Z" });

  // sem estado publicado da origem: nunca silenciosa
  expect(resolverAlarmes([evt], SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toEqual([
    {
      familia: "estado",
      kind: "mpc_solver_error",
      origin: "flow:1/block:mpc",
      desde: "2026-01-01T00:00:01.000Z",
      severity: "alarm",
      message: "mensagem de mpc_solver_error",
    },
  ]);

  // estado publicado ainda em erro: continua ativa
  const aindaErro = new Map([["1/mpc", mpcState({ solver: "error" })]]);
  expect(resolverAlarmes([evt], SEM_FLOW_STATUS, aindaErro, AGORA)).toHaveLength(1);

  // estado publicado recuperado: cessa
  const recuperado = new Map([["1/mpc", mpcState({ solver: "ok" })]]);
  expect(resolverAlarmes([evt], SEM_FLOW_STATUS, recuperado, AGORA)).toEqual([]);
});

test("estado publicado: mpc_input_invalid cessa quando input_valid=true; mpc_shed cessa quando armed=true", () => {
  const invalido = evento("mpc_input_invalid", "flow:2/block:mpc", {
    ts: "2026-01-01T00:00:01.000Z",
    severity: "warning",
  });
  const shed = evento("mpc_shed", "flow:3/block:mpc", { ts: "2026-01-01T00:00:01.000Z" });

  const estados = new Map([
    ["2/mpc", mpcState({ input_valid: true })], // cessou
    ["3/mpc", mpcState({ armed: false })], // ainda ativa
  ]);

  expect(resolverAlarmes([invalido, shed], SEM_FLOW_STATUS, estados, AGORA)).toEqual([
    {
      familia: "estado",
      kind: "mpc_shed",
      origin: "flow:3/block:mpc",
      desde: "2026-01-01T00:00:01.000Z",
      severity: "alarm",
      message: "mensagem de mpc_shed",
    },
  ]);
});

test("estado publicado: estado obsoleto (mais antigo que a REOCORRÊNCIA) não silencia o alarme reincidente (fix round 1, achado crítico)", () => {
  const primeiraOcorrencia = evento("mpc_solver_error", "flow:1/block:mpc", { ts: "2026-01-01T00:00:01.000Z" });
  // Estado "recuperado" é mais novo que a 1a ocorrência: cessa normalmente.
  const recuperado = new Map([["1/mpc", mpcState({ solver: "ok" })]]); // ts padrão 00:00:05
  expect(resolverAlarmes([primeiraOcorrencia], SEM_FLOW_STATUS, recuperado, AGORA)).toEqual([]);

  // Reocorrência: novo evento, mais recente que o ÚLTIMO estado conhecido (o mesmo mapa
  // `recuperado` de cima — nada publicou de novo, `reduzir()` nunca apaga entrada nenhuma).
  // Sem checar frescor, esse estado obsoleto silenciaria a reincidência (viola A-4).
  const reocorrencia = evento("mpc_solver_error", "flow:1/block:mpc", { ts: "2026-01-01T00:00:10.000Z" });
  expect(resolverAlarmes([reocorrencia], SEM_FLOW_STATUS, recuperado, AGORA)).toEqual([
    {
      familia: "estado",
      kind: "mpc_solver_error",
      origin: "flow:1/block:mpc",
      desde: "2026-01-01T00:00:10.000Z",
      severity: "alarm",
      message: "mensagem de mpc_solver_error",
    },
  ]);
});

// ----------------------------------------------------------------------------------------
// Família 3 — contador publicado
// ----------------------------------------------------------------------------------------

test("contador publicado (flow_overrun): sem estado é ativa; overruns inalterado numa leitura só NÃO cessa; cessa só na leitura seguinte", () => {
  const evt = evento("flow_overrun", "flow:7", {
    ts: "2026-01-01T00:00:10.000Z",
    severity: "warning",
    payload: { overruns: 3 },
  });

  // sem flow.status publicado: ativa (nunca silenciosa)
  expect(resolverAlarmes([evt], SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toHaveLength(1);

  // leitura concorrente à própria varredura do evento (mesmo instante): ainda não são
  // "duas publicações consecutivas" — continua ativa
  const leituraConcorrente = new Map([[7, flowStatus(3, "2026-01-01T00:00:10.000Z")]]);
  expect(resolverAlarmes([evt], leituraConcorrente, SEM_MPC_STATES, AGORA)).toHaveLength(1);

  // varredura seguinte no orçamento, overruns ainda 3: rearme (scheduler.py:232-238) — cessa
  const leituraSeguinte = new Map([[7, flowStatus(3, "2026-01-01T00:00:15.000Z")]]);
  expect(resolverAlarmes([evt], leituraSeguinte, SEM_MPC_STATES, AGORA)).toEqual([]);

  // continuou estourando (overruns subiu) mesmo numa leitura posterior: ainda ativa
  const aindaEstourando = new Map([[7, flowStatus(4, "2026-01-01T00:00:15.000Z")]]);
  expect(resolverAlarmes([evt], aindaEstourando, SEM_MPC_STATES, AGORA)).toHaveLength(1);
});

test("contador publicado (mpc_overrun): sem estado é ativa; ativa com solver='overrun'; cessa quando o solver sai de 'overrun' (mesmo instante do rearme, blocks/mpc.py:313)", () => {
  const evt = evento("mpc_overrun", "flow:9/block:mpc", {
    ts: "2026-01-01T00:00:01.000Z",
    severity: "warning",
  });

  // payload de mpc_overrun não carrega `overruns` (blocks/mpc.py `_report_overrun`, `{}`) —
  // sem estado publicado, a regra normativa A-4 ainda vale: ativa.
  expect(resolverAlarmes([evt], SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toHaveLength(1);

  const estourando = new Map([["9/mpc", mpcState({ solver: "overrun" })]]);
  expect(resolverAlarmes([evt], SEM_FLOW_STATUS, estourando, AGORA)).toHaveLength(1);

  const rearmado = new Map([["9/mpc", mpcState({ solver: "ok" })]]);
  expect(resolverAlarmes([evt], SEM_FLOW_STATUS, rearmado, AGORA)).toEqual([]);
});

test("contador publicado (mpc_overrun): estado obsoleto (mais antigo que a REOCORRÊNCIA) não silencia o alarme reincidente (fix round 1, achado crítico)", () => {
  const primeiraOcorrencia = evento("mpc_overrun", "flow:9/block:mpc", {
    ts: "2026-01-01T00:00:01.000Z",
    severity: "warning",
  });
  const rearmado = new Map([["9/mpc", mpcState({ solver: "ok" })]]); // ts padrão 00:00:05
  expect(resolverAlarmes([primeiraOcorrencia], SEM_FLOW_STATUS, rearmado, AGORA)).toEqual([]);

  // Reocorrência mais recente que o mesmo estado "rearmado" retido — sem checar frescor,
  // ficaria silenciosamente cessada para sempre.
  const reocorrencia = evento("mpc_overrun", "flow:9/block:mpc", {
    ts: "2026-01-01T00:00:10.000Z",
    severity: "warning",
  });
  expect(resolverAlarmes([reocorrencia], SEM_FLOW_STATUS, rearmado, AGORA)).toHaveLength(1);
});

// ----------------------------------------------------------------------------------------
// Família 4 — TTL (só mpc_arm_failed)
// ----------------------------------------------------------------------------------------

test("TTL: mpc_arm_failed ativa dentro de 60s, expira depois, e a ocorrência mais recente renova a janela", () => {
  const recente = evento("mpc_arm_failed", "flow:5/block:mpc", {
    ts: "2026-01-01T00:59:01.000Z", // 59 s antes de AGORA
    severity: "warning",
  });
  expect(resolverAlarmes([recente], SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toHaveLength(1);

  const expirado = evento("mpc_arm_failed", "flow:6/block:mpc", {
    ts: "2026-01-01T00:00:00.000Z", // 3600 s antes de AGORA
    severity: "warning",
  });
  expect(resolverAlarmes([expirado], SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toEqual([]);

  // duas ocorrências da mesma origem: só a mais recente conta (renova a janela)
  const renovado = [
    evento("mpc_arm_failed", "flow:8/block:mpc", {
      ts: "2026-01-01T00:59:50.000Z", // 10 s antes: dentro do TTL
      severity: "warning",
    }),
    evento("mpc_arm_failed", "flow:8/block:mpc", {
      ts: "2026-01-01T00:00:00.000Z", // isolada, já teria expirado
      severity: "warning",
    }),
  ];
  expect(resolverAlarmes(renovado, SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toEqual([
    {
      familia: "ttl",
      kind: "mpc_arm_failed",
      origin: "flow:8/block:mpc",
      desde: "2026-01-01T00:59:50.000Z",
      severity: "warning",
      message: "mensagem de mpc_arm_failed",
    },
  ]);
});

// ----------------------------------------------------------------------------------------
// Robustez e agregação
// ----------------------------------------------------------------------------------------

test("evento sem `kind` no payload é ignorado, não gera condição nem quebra a função", () => {
  const malformado: EventMessage = {
    ts: "2026-01-01T00:00:01.000Z",
    severity: "alarm",
    origin: "conn:1",
    message: "evento sem kind",
    payload: {},
  };

  expect(resolverAlarmes([malformado], SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toEqual([]);
});

test("severity inesperada ('info') num kind de alarme normaliza para 'warning', nunca fica silenciosa nem quebra (fix round 1, achado 1)", () => {
  const evt = evento("comm_failure", "conn:99", {
    ts: "2026-01-01T00:00:01.000Z",
    severity: "info",
  });

  expect(resolverAlarmes([evt], SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toEqual([
    {
      familia: "par",
      kind: "comm_failure",
      origin: "conn:99",
      desde: "2026-01-01T00:00:01.000Z",
      severity: "warning",
      message: "mensagem de comm_failure",
    },
  ]);
});

test("agrega condições de famílias e origens diferentes sem se misturarem", () => {
  const eventos = [
    evento("mpc_arm_failed", "flow:1/block:mpc", {
      ts: "2026-01-01T00:59:30.000Z",
      severity: "warning",
    }),
    evento("comm_failure", "conn:9", { ts: "2026-01-01T00:00:00.000Z" }),
  ];

  expect(resolverAlarmes(eventos, SEM_FLOW_STATUS, SEM_MPC_STATES, AGORA)).toEqual([
    {
      familia: "par",
      kind: "comm_failure",
      origin: "conn:9",
      desde: "2026-01-01T00:00:00.000Z",
      severity: "alarm",
      message: "mensagem de comm_failure",
    },
    {
      familia: "ttl",
      kind: "mpc_arm_failed",
      origin: "flow:1/block:mpc",
      desde: "2026-01-01T00:59:30.000Z",
      severity: "warning",
      message: "mensagem de mpc_arm_failed",
    },
  ]);
});
