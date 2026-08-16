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

test("raw: eixo x é a união ordenada dos carimbos de duas penas com grades diferentes", () => {
  // Carry-forward-com-teto em si é coberto uma vez em `alinhamento.check.ts` (ARCH-02) — aqui
  // só a construção do eixo união e a delegação por pena.
  const resp = resposta("raw", [serie(VIVA, 10, 120, 5), serie(MORTA, 10, 20, 7)]);
  const [x, viva, morta] = montarMatriz(resp, [VIVA, MORTA]);

  expect(x.length).toBe(13); // união = 0,10,…,120
  for (let i = 0; i < x.length; i++) expect(viva[i]).toBe(5);
  expect(morta[2]).toBe(7); // t=20 s, última amostra real de MORTA
  expect(morta[x.length - 1]).toBeNull(); // silêncio muito além do teto: delegado ao primitivo

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

test("1m: teto do modo agregado é repassado ao primitivo — pena parada vira SEM DADO na legenda", () => {
  const resp = resposta("1m", [serie(VIVA, 60, 1800, 5), serie(MORTA, 60, 300, 7)]);
  const [, , morta] = montarMatriz(resp, [VIVA, MORTA]);

  expect(morta[morta.length - 1]).toBeNull();
  expect(resumirSeries(resp, [MORTA])[0].semDado).toBe(true);
});
