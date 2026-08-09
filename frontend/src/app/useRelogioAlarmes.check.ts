import { expect, test } from "@playwright/test";

import { criarRelogioAlarmes, INTERVALO_TIQUE_ALARMES_MS, type AmbienteRelogio } from "./useRelogioAlarmes";

/** Duble de `AmbienteRelogio`: o intervalo NUNCA dispara sozinho - quem decide quando
 *  e o teste, chamando `avancar(ms)`. Replica o duble de `canalAoVivo.check.ts` para
 *  nao criar import circular entre arquivos de teste. */
function relogioFalso(inicio = new Date("2026-01-01T00:00:00.000Z")) {
  let agoraAtual = inicio;
  let capturado: { acao: () => void; intervaloMs: number } | null = null;
  let proximoId = 1;
  const cancelados: number[] = [];

  const ambiente: AmbienteRelogio = {
    agora: () => agoraAtual,
    agendar(acao, intervaloMs) {
      const id = proximoId++;
      capturado = { acao, intervaloMs };
      return id;
    },
    cancelar(id) {
      cancelados.push(id);
      capturado = null;
    },
  };

  return {
    ambiente,
    cancelados,
    intervaloRegistradoMs() {
      return capturado?.intervaloMs;
    },
    avancar(ms: number): void {
      agoraAtual = new Date(agoraAtual.getTime() + ms);
      capturado?.acao();
    },
  };
}

test("relogio: o intervalo agendado e a constante nomeada de 5 s (spec section 6.6-1), nao um literal solto", () => {
  const f = relogioFalso();
  criarRelogioAlarmes(() => {}, f.ambiente);

  expect(INTERVALO_TIQUE_ALARMES_MS).toBe(5_000);
  expect(f.intervaloRegistradoMs()).toBe(INTERVALO_TIQUE_ALARMES_MS);
});

test("relogio: cada tique entrega um instante mais novo que o anterior, sem depender de mensagem nenhuma", () => {
  const f = relogioFalso();
  const instantes: Date[] = [];
  criarRelogioAlarmes((agora) => instantes.push(agora), f.ambiente);

  f.avancar(INTERVALO_TIQUE_ALARMES_MS);
  f.avancar(INTERVALO_TIQUE_ALARMES_MS);
  f.avancar(INTERVALO_TIQUE_ALARMES_MS);

  expect(instantes).toHaveLength(3);
  expect(instantes[1].getTime()).toBeGreaterThan(instantes[0].getTime());
  expect(instantes[2].getTime()).toBeGreaterThan(instantes[1].getTime());
});

test("relogio: desmontar cancela exatamente o intervalo agendado - sem vazamento entre montagens", () => {
  const f = relogioFalso();
  const ciclo = criarRelogioAlarmes(() => {}, f.ambiente);

  ciclo.desmontar();

  expect(f.cancelados).toEqual([1]);
});
