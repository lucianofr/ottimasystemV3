import { expect, test } from "@playwright/test";

import type { HistoryResponse, HistorySeries } from "../../lib/api";
import { montarMatriz, resumirSeries, tetoCarryForwardSegundos } from "./useHistory";

/** Base arbitrária: só os deslocamentos em segundos importam. */
const T0 = Date.parse("2026-01-01T12:00:00Z") / 1000;

function carimbo(deslocamentoS: number): string {
  return new Date((T0 + deslocamentoS) * 1000).toISOString();
}

/** Série sintética boa: uma amostra a cada `passoS`, de 0 até `ateS` inclusive. */
function serie(tagId: number, passoS: number, ateS: number, valor: number): HistorySeries {
  const t: string[] = [];
  for (let d = 0; d <= ateS; d += passoS) t.push(carimbo(d));
  return { tag_id: tagId, t, v: t.map(() => valor), q: t.map(() => 0) };
}

function resposta(modo: HistoryResponse["mode"], series: HistorySeries[]): HistoryResponse {
  return { mode: modo, start: carimbo(0), end: carimbo(1800), series };
}

const VIVA = 1;
const MORTA = 2;

test("teto de carry-forward escala com o modo", () => {
  // 2 × heartbeat de valor (10 s) e 2 × bucket (60 s).
  expect(tetoCarryForwardSegundos("raw")).toBe(20);
  expect(tetoCarryForwardSegundos("1m")).toBe(120);
});

test("raw: pena que parou de reportar vira gap enquanto a outra segue viva", () => {
  // Duas tags a 10 s (a cadência do heartbeat). A morta cala em t=20 s; a viva segue até 120 s
  // e é ela que continua puxando o eixo x — o cenário em que o carry-forward mentiria.
  const resp = resposta("raw", [serie(VIVA, 10, 120, 5), serie(MORTA, 10, 20, 7)]);
  const [x, viva, morta] = montarMatriz(resp, [VIVA, MORTA]);

  expect(x.length).toBe(13); // união = 0,10,…,120
  for (let i = 0; i < x.length; i++) expect(viva[i]).toBe(5);

  // Até o teto (20 s de silêncio) o carry-forward é legítimo: o valor de fato não mudou.
  expect(morta[2]).toBe(7); // t=20 s, amostra real
  expect(morta[3]).toBe(7); // t=30 s, 10 s de silêncio
  expect(morta[4]).toBe(7); // t=40 s, 20 s de silêncio = teto
  // Passado o teto, repetir o valor seria inventar aquisição que não houve.
  for (let i = 5; i < x.length; i++) expect(morta[i]).toBeNull();

  const [resumoViva, resumoMorta] = resumirSeries(resp, [VIVA, MORTA]);
  expect(resumoViva).toEqual({ tagId: VIVA, valor: 5, bad: false, semDado: false });
  // A legenda não pode exibir 7 como se fosse o valor atual.
  expect(resumoMorta).toEqual({ tagId: MORTA, valor: null, bad: false, semDado: true });
});

test("1m: série saudável de bucket de 60 s não vira gap", () => {
  const resp = resposta("1m", [serie(VIVA, 60, 1800, 5), serie(MORTA, 60, 1800, 7)]);
  const [x, viva, morta] = montarMatriz(resp, [VIVA, MORTA]);

  expect(x.length).toBe(31); // 0,60,…,1800
  for (let i = 0; i < x.length; i++) {
    expect(viva[i]).toBe(5);
    // Espaçamento de 60 s entre buckets: com teto de raw (20 s) tudo aqui seria gap.
    expect(morta[i]).toBe(7);
  }
});

test("1m: pena que parou vira gap depois de dois buckets", () => {
  const resp = resposta("1m", [serie(VIVA, 60, 1800, 5), serie(MORTA, 60, 300, 7)]);
  const [, , morta] = montarMatriz(resp, [VIVA, MORTA]);

  expect(morta[5]).toBe(7); // t=300 s, amostra real
  expect(morta[7]).toBe(7); // t=420 s, 120 s de silêncio = teto
  expect(morta[8]).toBeNull(); // t=480 s, 180 s de silêncio
  expect(resumirSeries(resp, [MORTA])[0].semDado).toBe(true);
});
