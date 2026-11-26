import { expect, test } from "@playwright/test";

import {
  agoraLocal,
  alternarEntrada,
  fusoDoNavegador,
  janelaAoVivoDefasada,
  janelaDoConjunto,
  progressoDoJob,
  podeExcluir,
  podeFinalizar,
  podeRefazer,
  resumoPareamento,
  temJobAtivo,
  TETO_ENTRADAS,
} from "./coleta";

/**
 * Funções puras da página "Coleta e treino" (RF-589): sem browser, sem backend. O texto de
 * `resumoPareamento` é o que o engenheiro lê para decidir se o conjunto serve, então fica
 * pinado palavra por palavra.
 */

test("resumoPareamento com descartes", () => {
  expect(
    resumoPareamento({ analyses: 44, dropped_no_process: 3, paired: 41, full_window: 30 }),
  ).toBe(
    "Emparelhadas 41 de 44 · 3 sem dado de processo no instante da coleta · 30 com janela completa",
  );
});

test("resumoPareamento sem análises", () => {
  expect(
    resumoPareamento({ analyses: 0, dropped_no_process: 0, paired: 0, full_window: 0 }),
  ).toBe("Nenhuma análise no período");
});

test("resumoPareamento sem stats (conjunto ainda não montado) não inventa número", () => {
  expect(resumoPareamento({})).toBe("Nenhuma análise no período");
});

test("temJobAtivo só com queued ou running", () => {
  expect(temJobAtivo(undefined)).toBe(false);
  expect(temJobAtivo([])).toBe(false);
  expect(temJobAtivo([{ status: "done" }, { status: "failed" }, { status: "cancelled" }])).toBe(
    false,
  );
  expect(temJobAtivo([{ status: "done" }, { status: "queued" }])).toBe(true);
  expect(temJobAtivo([{ status: "running" }])).toBe(true);
});

test("podeFinalizar só em collecting", () => {
  expect(podeFinalizar({ status: "collecting" })).toBe(true);
  for (const status of ["building", "ready", "failed"]) {
    expect(podeFinalizar({ status }), status).toBe(false);
  }
});

test("podeRefazer só em failed (o retry do backend parte de failed; collecting usa Finalizar)", () => {
  expect(podeRefazer({ status: "failed" })).toBe(true);
  for (const status of ["collecting", "building", "ready"]) {
    expect(podeRefazer({ status }), status).toBe(false);
  }
});

test("podeExcluir em qualquer estado menos building (o DELETE devolve 409 em montagem)", () => {
  for (const status of ["collecting", "ready", "failed"]) {
    expect(podeExcluir({ status }), status).toBe(true);
  }
  expect(podeExcluir({ status: "building" })).toBe(false);
});

test("progressoDoJob lê done/total e devolve null sem progresso", () => {
  expect(progressoDoJob({ progress: { done: 3, total: 10 } })).toEqual({ feito: 3, total: 10 });
  expect(progressoDoJob({ progress: {} })).toBeNull();
  expect(progressoDoJob({ progress: { done: 3 } })).toBeNull();
  expect(progressoDoJob({ progress: { done: "3", total: "10" } })).toBeNull();
  // total 0 não tem fração: o <progress> fica indeterminado em vez de dividir por zero
  expect(progressoDoJob({ progress: { done: 0, total: 0 } })).toBeNull();
});

test("fusoDoNavegador devolve um nome IANA", () => {
  const fuso = fusoDoNavegador();

  expect(fuso.includes("/") || fuso === "UTC").toBe(true);
});

test("alternarEntrada preserva a ordem de marcação e respeita o teto", () => {
  expect(alternarEntrada([], 7)).toEqual([7]);
  expect(alternarEntrada([7], 3)).toEqual([7, 3]);
  // desmarcar não reordena as demais
  expect(alternarEntrada([7, 3, 9], 3)).toEqual([7, 9]);

  const cheia = Array.from({ length: TETO_ENTRADAS }, (_, i) => i + 1);
  expect(TETO_ENTRADAS).toBe(32);
  expect(alternarEntrada(cheia, 999)).toBe(cheia);
  // no teto ainda dá para desmarcar
  expect(alternarEntrada(cheia, 1)).toHaveLength(TETO_ENTRADAS - 1);
});

test("janelaDoConjunto: coletando segue o relógio, com piso de 1 min", () => {
  const agora = Date.parse("2026-11-26T12:00:00Z");

  expect(
    janelaDoConjunto({ start_ts: "2026-11-26T10:00:00Z", end_ts: null }, agora),
  ).toEqual({ janelaSegundos: 7200, fimEpochS: null });
  // início há 10 s: o piso evita janela degenerada (start >= end é 422 no /api/history)
  expect(
    janelaDoConjunto({ start_ts: "2026-11-26T11:59:50Z", end_ts: null }, agora),
  ).toEqual({ janelaSegundos: 60, fimEpochS: null });
});

test("janelaDoConjunto: encerrado fixa [start_ts, end_ts], arredondando a janela para cima ao minuto", () => {
  const agora = Date.parse("2026-11-27T00:00:00Z");

  expect(
    janelaDoConjunto(
      { start_ts: "2026-11-26T10:00:00Z", end_ts: "2026-11-26T10:30:30Z" },
      agora,
    ),
  ).toEqual({ janelaSegundos: 1860, fimEpochS: Date.parse("2026-11-26T10:30:30Z") / 1000 });
});

test("janelaDoConjunto: teto de 31 dias, o que o /api/history aceita", () => {
  const agora = Date.parse("2026-11-26T12:00:00Z");

  expect(
    janelaDoConjunto({ start_ts: "2026-01-01T00:00:00Z", end_ts: null }, agora).janelaSegundos,
  ).toBe(31 * 86400);
});

test("agoraLocal formata a hora LOCAL no padrão do datetime-local, sem segundos", () => {
  // construtor com componentes = hora local, independente do TZ da máquina de teste
  expect(agoraLocal(new Date(2026, 10, 26, 9, 5, 59))).toBe("2026-11-26T09:05");
});

test("janelaAoVivoDefasada: conjunto encerrado nunca refaz (a janela é fixa em [start_ts, end_ts])", () => {
  const encerrado = { start_ts: "2026-11-26T10:00:00Z", end_ts: "2026-11-26T11:00:00Z" };
  const agora = Date.parse("2026-12-30T00:00:00Z");

  expect(janelaAoVivoDefasada(encerrado, 60, agora - 3_600_000, agora)).toBe(false);
});

test("janelaAoVivoDefasada: ao vivo refaz no tique de 5 min", () => {
  const vivo = { start_ts: "2026-11-26T10:00:00Z", end_ts: null };
  const agora = Date.parse("2026-11-26T12:00:00Z"); // decorrido 2 h; janela de 2 h cobre
  const janela = 7200;

  expect(janelaAoVivoDefasada(vivo, janela, agora - 299_000, agora)).toBe(false);
  expect(janelaAoVivoDefasada(vivo, janela, agora - 300_000, agora)).toBe(true);
});

test("janelaAoVivoDefasada: ao vivo refaz antes do tique quando o decorrido passa de 1,5x a janela", () => {
  const agora = Date.parse("2026-11-26T12:00:00Z");
  const recente = agora - 30_000; // recalculada há 30 s: o tique de 5 min ainda não venceu
  // janela de 60 s (coleta recém-iniciada): 80 s decorridos ainda cabem em 1,5x, 100 s não
  expect(
    janelaAoVivoDefasada({ start_ts: "2026-11-26T11:58:40Z", end_ts: null }, 60, recente, agora),
  ).toBe(false);
  expect(
    janelaAoVivoDefasada({ start_ts: "2026-11-26T11:58:20Z", end_ts: null }, 60, recente, agora),
  ).toBe(true);
});

test("janelaAoVivoDefasada: no teto de 31 dias a regra de 1,5x cala (refazer não alargaria nada)", () => {
  const vivo = { start_ts: "2026-01-01T00:00:00Z", end_ts: null };
  const agora = Date.parse("2026-11-26T12:00:00Z");

  expect(janelaAoVivoDefasada(vivo, 31 * 86400, agora - 30_000, agora)).toBe(false);
});
