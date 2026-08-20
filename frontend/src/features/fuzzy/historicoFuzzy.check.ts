import { expect, test } from "@playwright/test";

import type { PontoVivo } from "../trend/bordaViva";
import { referenciaPersistidaS } from "../trend/bordaViva";
import {
  mesclarHistoricoFuzzyVivo,
  montarMatrizFuzzy,
  resumirSeriesFuzzy,
} from "./historicoFuzzy";
import type { FuzzyHistoryResponse, FuzzyHistorySeries } from "./types";

/** Base arbitrária: só os deslocamentos em segundos importam. */
const T0 = Date.parse("2026-01-01T12:00:00Z") / 1000;

function carimbo(deslocamentoS: number): string {
  return new Date((T0 + deslocamentoS) * 1000).toISOString();
}

function serie(varId: string, passoS: number, ateS: number, valor: number): FuzzyHistorySeries {
  const t: string[] = [];
  for (let d = 0; d <= ateS; d += passoS) t.push(carimbo(d));
  return { var_id: varId, t, v: t.map(() => valor) };
}

function resposta(
  modo: FuzzyHistoryResponse["mode"],
  series: FuzzyHistorySeries[],
): FuzzyHistoryResponse {
  return { mode: modo, start: carimbo(0), end: carimbo(1800), series };
}

function vivos(
  entradas: Readonly<Record<string, readonly PontoVivo[]>>,
): ReadonlyMap<string, readonly PontoVivo[]> {
  return new Map(Object.entries(entradas));
}

test("raw: amostra viva de uma porta entra no eixo x do trend fuzzy", () => {
  // Histórico até 100 s (poll de 5 s) e um `fuzzy.state` de 104 s vindo pelo WS.
  const resp = resposta("raw", [serie("IN1", 10, 100, 0.4), serie("OUT1", 10, 100, 0.9)]);
  const mesclado = mesclarHistoricoFuzzyVivo(resp, vivos({ IN1: [{ t: T0 + 104, v: 0.7 }] }));
  const [x, entrada, saida] = montarMatrizFuzzy(mesclado, ["IN1", "OUT1"]);

  expect(x[x.length - 1]).toBe(T0 + 104);
  expect(entrada[entrada.length - 1]).toBe(0.7);
  // Porta sem amostra nova: carry-forward legítimo (4 s < teto de 20 s do modo bruto).
  expect(saida[saida.length - 1]).toBe(0.9);
  expect(x[0]).toBe(T0);

  // Legenda lê a mesma resposta mesclada — não pode contradizer o gráfico.
  expect(resumirSeriesFuzzy(mesclado, ["IN1"])[0]).toEqual({
    varId: "IN1",
    valor: 0.7,
    semDado: false,
  });
});

test("amostra viva em carimbo que o histórico já trouxe não duplica", () => {
  const resp = resposta("raw", [serie("IN1", 10, 100, 0.4)]);
  const mesclado = mesclarHistoricoFuzzyVivo(resp, vivos({ IN1: [{ t: T0 + 100, v: 0.7 }] }));

  expect(montarMatrizFuzzy(mesclado, ["IN1"])[0].length).toBe(11);
  expect(mesclado.series[0].v[10]).toBe(0.4);
});

test("1m: a vista agregada do trend fuzzy também recebe a borda viva", () => {
  // Mesma razão do trend de engenharia (`../trend/bordaViva.check.ts`): as três telas de trend
  // têm de se comportar igual, e o trend de operação MPC mescla nos dois modos.
  const resp = resposta("1m", [serie("IN1", 60, 600, 0.4)]);
  const mesclado = mesclarHistoricoFuzzyVivo(resp, vivos({ IN1: [{ t: T0 + 800, v: 0.7 }] }));
  const [x, entrada] = montarMatrizFuzzy(mesclado, ["IN1"], referenciaPersistidaS(resp.series));

  expect(x[x.length - 1]).toBe(T0 + 800);
  expect(entrada[entrada.length - 1]).toBe(0.7);
  // O passado agregado continua desenhado inteiro: a borda viva ACRESCENTA.
  expect(x[0]).toBe(T0);
  expect(x.length).toBe(12); // 0,60,…,600 (11) + 800 — a costura vivo↔persistido não é silêncio
});

test("porta sem amostra persistida na janela desenha só com a borda viva", () => {
  // Bloco fuzzy que acabou de entrar em execução: o router não devolve série nenhuma para a
  // porta, e sem a série sintética a pena ficaria vazia com valor chegando pelo WS.
  const resp = resposta("raw", []);
  const mesclado = mesclarHistoricoFuzzyVivo(resp, vivos({ OUT1: [{ t: T0 + 4, v: 0.62 }] }));
  const [x, saida] = montarMatrizFuzzy(mesclado, ["OUT1"]);

  expect(x).toEqual([T0 + 4]);
  expect(saida).toEqual([0.62]);
});

test("sem borda viva a resposta fuzzy passa inalterada", () => {
  const resp = resposta("raw", [serie("IN1", 10, 100, 0.4)]);

  expect(mesclarHistoricoFuzzyVivo(resp, new Map())).toBe(resp);
});

test("silêncio simultâneo de todas as portas vira gap no eixo, não reta interpolada", () => {
  // Mesma regressão das outras duas telas de trend (ARCH-02): quando todas as portas
  // calam juntas, a união não tem carimbo no silêncio e o uPlot interpola as bordas.
  const resp = resposta("raw", [
    { var_id: "IN1", t: [carimbo(0), carimbo(2), carimbo(52), carimbo(54)], v: [0.4, 0.4, 0.5, 0.5] },
    { var_id: "OUT1", t: [carimbo(0), carimbo(2), carimbo(52), carimbo(54)], v: [0.9, 0.9, 0.8, 0.8] },
  ]);
  const mesclado = mesclarHistoricoFuzzyVivo(resp, new Map());
  const [x, entrada, saida] = montarMatrizFuzzy(mesclado, ["IN1", "OUT1"]);
  const i = x.indexOf(T0 + 37); // marca: meio da zona nula (2 + 20, 52)
  expect(i).toBeGreaterThan(-1);
  expect(entrada[i]).toBeNull();
  expect(saida[i]).toBeNull();
});
