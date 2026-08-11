import { expect, test } from "@playwright/test";

import type { MpcState } from "../../lib/contracts.gen";
import { reduzirPendencia } from "./pendencia";

/**
 * `reduzirPendencia` — tarefa 4.2 do plano F5b (spec F5 §7.4-4; F5R-18; Regra do Estado
 * Publicado). Redutor PURO do pendente-até-confirmar: ao comandar, o alvo entra em fantasma
 * até o `mpc.state` publicado seguinte confirmar (materializa) ou a janela `max(3×Ts_mpc, 5s)`
 * vencer (reverte). Sem timers internos, sem estado de módulo, sem I/O — `agora` é o único
 * relógio, injetado pelo chamador (4.3/4.4).
 */

function estadoPublicado(
  parcial: { vars?: MpcState["vars"]; modes?: Partial<MpcState["modes"]> } = {},
): MpcState {
  return {
    ts: "2026-01-01T00:00:05.000Z",
    modes: { local_remote: "remote", man_auto: "auto", ...parcial.modes },
    status: { solver: "ok", overruns: 0, last_solve_ms: 1, armed: true, input_valid: true },
    vars: parcial.vars ?? {},
    cost: 0,
    prediction: { ts: "2026-01-01T00:00:05.000Z", t: [], cv: [], mv: [] },
    ssto: null,
  };
}

const AGORA = 1_000_000;

test("comandar abre pendência com o valor em fantasma e janela 3xTs_mpc", () => {
  const pendencia = reduzirPendencia(null, {
    tipo: "comandar",
    alvo: "vars.MV1.v",
    valor: 42,
    tsMpcSegundos: 2,
    agora: AGORA,
  });
  expect(pendencia).toEqual({ alvo: "vars.MV1.v", valorComandado: 42, expiraEm: AGORA + 6000 });
});

test("estado publicado que confirma o alvo materializa (pendência cai para null)", () => {
  const pendente = reduzirPendencia(null, {
    tipo: "comandar",
    alvo: "vars.MV1.v",
    valor: 42,
    tsMpcSegundos: 2,
    agora: AGORA,
  });
  const confirmado = estadoPublicado({ vars: { MV1: { v: 42, sp: null, status: null } } });
  const resultado = reduzirPendencia(pendente, {
    tipo: "estadoPublicado",
    state: confirmado,
    agora: AGORA + 100,
  });
  expect(resultado).toBeNull();
});

test("estado publicado que NÃO confirma o alvo não materializa nem cancela a pendência", () => {
  const pendente = reduzirPendencia(null, {
    tipo: "comandar",
    alvo: "vars.MV1.v",
    valor: 42,
    tsMpcSegundos: 2,
    agora: AGORA,
  });
  const naoConfirma = estadoPublicado({ vars: { MV1: { v: 41, sp: null, status: null } } });
  const resultado = reduzirPendencia(pendente, {
    tipo: "estadoPublicado",
    state: naoConfirma,
    agora: AGORA + 100,
  });
  expect(resultado).toEqual(pendente);
});

test("expira em 3xTs_mpc revertendo ao publicado (janela ainda maior que 2 ticks do runtime)", () => {
  const pendente = reduzirPendencia(null, {
    tipo: "comandar",
    alvo: "modes.local_remote",
    valor: "remote",
    tsMpcSegundos: 2,
    agora: AGORA,
  });
  expect(reduzirPendencia(pendente, { tipo: "tique", agora: AGORA + 5999 })).toEqual(pendente);
  expect(reduzirPendencia(pendente, { tipo: "tique", agora: AGORA + 6000 })).toBeNull();
});

test("piso de 5s aplicado quando 3xTs_mpc < 5s", () => {
  const pendente = reduzirPendencia(null, {
    tipo: "comandar",
    alvo: "vars.CV1.sp",
    valor: 10,
    tsMpcSegundos: 1,
    agora: AGORA,
  });
  expect(pendente?.expiraEm).toBe(AGORA + 5000);
  expect(reduzirPendencia(pendente, { tipo: "tique", agora: AGORA + 4999 })).toEqual(pendente);
  expect(reduzirPendencia(pendente, { tipo: "tique", agora: AGORA + 5000 })).toBeNull();
});

test("comandar de novo sobre uma pendência já aberta substitui pelo novo alvo/valor/janela", () => {
  const primeira = reduzirPendencia(null, {
    tipo: "comandar",
    alvo: "vars.MV1.v",
    valor: 42,
    tsMpcSegundos: 2,
    agora: AGORA,
  });
  const segunda = reduzirPendencia(primeira, {
    tipo: "comandar",
    alvo: "vars.MV1.v",
    valor: 50,
    tsMpcSegundos: 3,
    agora: AGORA + 500,
  });
  expect(segunda).toEqual({ alvo: "vars.MV1.v", valorComandado: 50, expiraEm: AGORA + 500 + 9000 });
});

test("estadoPublicado aceita um recorte parcial sem cast (§6.6-3: state é unknown, não MpcState)", () => {
  const pendente = reduzirPendencia(null, {
    tipo: "comandar",
    alvo: "vars.MV1.v",
    valor: 42,
    tsMpcSegundos: 2,
    agora: AGORA,
  });
  // Sem double-cast para MpcState: só o recorte que FaceplateVariavel de fato tem (um único
  // `vars.<id>`), sem `ts`/`modes`/`status`/`cost`/`prediction` — exatamente o formato que
  // exigia o cast antes do débito §6.6-3 fechar.
  const recortePublicado = { vars: { MV1: { v: 42, sp: null } } };
  const resultado = reduzirPendencia(pendente, {
    tipo: "estadoPublicado",
    state: recortePublicado,
    agora: AGORA + 100,
  });
  expect(resultado).toBeNull();
});
