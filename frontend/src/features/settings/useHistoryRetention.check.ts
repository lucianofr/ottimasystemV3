import { expect, test } from "@playwright/test";

import {
  MAX_EVENTS_RETENTION_DAYS,
  MAX_RETENTION_DAYS,
  MIN_RETENTION_DAYS,
  retencaoEhValida,
  retencaoEventosEhValida,
} from "./useHistoryRetention";

/**
 * `useHistoryRetention.ts::retencaoEhValida` — mesmo limite do backend (`schemas/
 * history_retention.py::MIN/MAX_RETENTION_DAYS`, ADR-003 revisado). O que precisa de prova:
 * as fronteiras 1 e 120 (inclusive), o que fica fora delas, e que não-inteiro nunca passa
 * (o campo é `type="number"`, mas `Number("1.5")` ainda produz um valor não-inteiro).
 */
test("aceita as fronteiras 1 e 120 dias", () => {
  expect(retencaoEhValida(MIN_RETENTION_DAYS)).toBe(true);
  expect(retencaoEhValida(MAX_RETENTION_DAYS)).toBe(true);
  expect(retencaoEhValida(45)).toBe(true);
});

test("rejeita abaixo de 1 e acima de 120", () => {
  expect(retencaoEhValida(0)).toBe(false);
  expect(retencaoEhValida(-1)).toBe(false);
  expect(retencaoEhValida(121)).toBe(false);
});

test("rejeita não-inteiro, NaN e infinito", () => {
  expect(retencaoEhValida(1.5)).toBe(false);
  expect(retencaoEhValida(Number.NaN)).toBe(false);
  expect(retencaoEhValida(Number.POSITIVE_INFINITY)).toBe(false);
});

/** `retencaoEventosEhValida` — janela de `events` (ADR-020 revisado): fronteira própria 90. */
test("eventos: aceita as fronteiras 1 e 90 dias", () => {
  expect(retencaoEventosEhValida(MIN_RETENTION_DAYS)).toBe(true);
  expect(retencaoEventosEhValida(MAX_EVENTS_RETENTION_DAYS)).toBe(true);
  expect(retencaoEventosEhValida(45)).toBe(true);
});

test("eventos: rejeita 0, 91 e não-inteiro", () => {
  expect(retencaoEventosEhValida(0)).toBe(false);
  expect(retencaoEventosEhValida(91)).toBe(false);
  expect(retencaoEventosEhValida(1.5)).toBe(false);
});
