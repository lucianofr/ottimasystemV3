import { expect, test } from "@playwright/test";

import { ancoraDivisorAgora, calcularRangeXOperacao } from "./secaoFutura";

/**
 * `calcularRangeXOperacao` — plano de melhorias, Fase 2 tarefa 2.2: extremos do eixo x das
 * duas seções (Histórico | Previsão) do trend de operação. Função pura, sem DOM/uPlot — o
 * desenho (sombreamento, rótulos, placeholder) fica no plugin, não testado aqui (regra
 * global 3: asserts leem dados, nunca pixel).
 */

const AGORA = 1_000_000;

test("ao vivo: reserva o horizonte futuro além de agora", () => {
  const [min, max] = calcularRangeXOperacao({
    fimEpochS: null,
    agoraEpochS: AGORA,
    janelaSegundos: 1800,
    horizonteFuturoS: 300,
  });
  expect(min).toBe(AGORA - 1800);
  expect(max).toBe(AGORA + 300);
});

test("ao vivo: a seção futura existe mesmo sem predição (mesmo cálculo, fora de AUTO)", () => {
  const [, max] = calcularRangeXOperacao({
    fimEpochS: null,
    agoraEpochS: AGORA,
    janelaSegundos: 900,
    horizonteFuturoS: 60,
  });
  expect(max).toBeGreaterThan(AGORA);
});

test("pausado: termina exatamente no fim deslizado, sem seção futura", () => {
  const fim = AGORA - 3600;
  const [min, max] = calcularRangeXOperacao({
    fimEpochS: fim,
    agoraEpochS: AGORA,
    janelaSegundos: 1800,
    horizonteFuturoS: 300,
  });
  expect(min).toBe(fim - 1800);
  expect(max).toBe(fim);
});

test("pausado: max nunca ultrapassa o fim deslizado, mesmo com horizonte grande", () => {
  const fim = AGORA - 100;
  const [, max] = calcularRangeXOperacao({
    fimEpochS: fim,
    agoraEpochS: AGORA,
    janelaSegundos: 600,
    horizonteFuturoS: 9999,
  });
  expect(max).toBe(fim);
});

test("horizonte futuro zero: max cai exatamente em agora quando ao vivo", () => {
  const [, max] = calcularRangeXOperacao({
    fimEpochS: null,
    agoraEpochS: AGORA,
    janelaSegundos: 1800,
    horizonteFuturoS: 0,
  });
  expect(max).toBe(AGORA);
});

test("min independe do horizonte futuro — só a janela desloca o início", () => {
  const a = calcularRangeXOperacao({
    fimEpochS: null,
    agoraEpochS: AGORA,
    janelaSegundos: 1800,
    horizonteFuturoS: 0,
  });
  const b = calcularRangeXOperacao({
    fimEpochS: null,
    agoraEpochS: AGORA,
    janelaSegundos: 1800,
    horizonteFuturoS: 5000,
  });
  expect(a[0]).toBe(b[0]);
});

// ------------------------------------------------- âncora do divisor "agora" (linha + sombra)

test("ao vivo e sem recorte: a âncora do divisor é o relógio de parede (B-5)", () => {
  expect(ancoraDivisorAgora(AGORA - 10, true, false, AGORA)).toBe(AGORA);
});

test("zoom manual congela a âncora: o divisor não anda sobre um eixo que não anda", () => {
  const congelada = ancoraDivisorAgora(AGORA, true, true, AGORA + 21);
  expect(congelada).toBe(AGORA);
  // Redesenho seguinte, mais 60 s de relógio: continua onde o operador congelou — sem isso a
  // linha e a sombra "Previsão" saltam para fora do recorte no primeiro quadro novo.
  expect(ancoraDivisorAgora(congelada, true, true, AGORA + 81)).toBe(AGORA);
});

test("soltar o recorte devolve o divisor ao relógio no mesmo quadro", () => {
  expect(ancoraDivisorAgora(AGORA, true, false, AGORA + 21)).toBe(AGORA + 21);
});

test("janela deslizada não tem 'agora' na vista: âncora nula, com ou sem recorte", () => {
  expect(ancoraDivisorAgora(AGORA, false, false, AGORA + 5)).toBeNull();
  expect(ancoraDivisorAgora(AGORA, false, true, AGORA + 5)).toBeNull();
});
