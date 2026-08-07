import { expect, test } from "@playwright/test";

import type { MpcHistoryResponse } from "../../lib/api";
import { JANELAS_OPERACAO, JANELA_PADRAO_ID, mesclarSeriesVivas, type AmostraViva } from "./trendOperacao";
import { chaveHistoricoOperacao } from "./useHistoryMpc";

/** Base arbitrária: só os deslocamentos em segundos importam (mesmo padrão de useHistory.check.ts). */
const T0 = Date.parse("2026-01-01T12:00:00Z") / 1000;

function carimbo(deslocamentoS: number): string {
  return new Date((T0 + deslocamentoS) * 1000).toISOString();
}

interface Ponto {
  readonly d: number;
  readonly v: number;
  readonly sp: number | null;
  readonly auto: boolean;
}

function historico(varId: string, pontos: readonly Ponto[]): MpcHistoryResponse {
  return {
    mode: "raw",
    start: carimbo(0),
    end: carimbo(pontos[pontos.length - 1]?.d ?? 0),
    series: [
      {
        var_id: varId,
        t: pontos.map((p) => carimbo(p.d)),
        v: pontos.map((p) => p.v),
        sp: pontos.map((p) => p.sp),
        auto: pontos.map((p) => p.auto),
      },
    ],
  };
}

function amostraViva(d: number, v: number, sp: number | null, auto: boolean): AmostraViva {
  return { ts: carimbo(d), vars: { cv_1: { v, sp } }, auto };
}

test("janelas de operação: 15m/30m/2h/8h, default 30 min", () => {
  expect(JANELAS_OPERACAO.map((j) => j.segundos)).toEqual([900, 1800, 7200, 28800]);
  const padrao = JANELAS_OPERACAO.find((j) => j.id === JANELA_PADRAO_ID);
  expect(padrao?.segundos).toBe(1800);
});

test("borda viva: mpc.state novo faz append na série sem esperar o poll", () => {
  const resp = historico("cv_1", [
    { d: 0, v: 1, sp: 1.5, auto: true },
    { d: 5, v: 1.1, sp: 1.5, auto: true },
  ]);
  const vivas: AmostraViva[] = [amostraViva(10, 1.2, 1.5, true)];
  const [serie] = mesclarSeriesVivas(resp, vivas, ["cv_1"]);

  expect(serie.t).toEqual([0, 5, 10].map((d) => T0 + d));
  expect(serie.v).toEqual([1, 1.1, 1.2]);
  expect(serie.sp).toEqual([1.5, 1.5, 1.5]);
  expect(serie.auto).toEqual([true, true, true]);
});

test("poll re-sincroniza sem duplicar pontos que a borda viva já tinha visto", () => {
  // O poll já trouxe t=10, que a borda viva também capturou ao vivo antes do poll chegar.
  const resp = historico("cv_1", [
    { d: 0, v: 1, sp: 1.5, auto: true },
    { d: 5, v: 1.1, sp: 1.5, auto: true },
    { d: 10, v: 1.2, sp: 1.5, auto: true },
  ]);
  const vivas: AmostraViva[] = [amostraViva(10, 1.2, 1.5, true), amostraViva(15, 1.3, 1.5, true)];
  const [serie] = mesclarSeriesVivas(resp, vivas, ["cv_1"]);

  expect(serie.t).toEqual([0, 5, 10, 15].map((d) => T0 + d));
  expect(serie.v).toEqual([1, 1.1, 1.2, 1.3]);
});

test("montagem de séries é pura: mesma entrada produz a mesma saída, sem mutar o histórico", () => {
  const resp = historico("cv_1", [{ d: 0, v: 1, sp: null, auto: false }]);
  const congelado = JSON.parse(JSON.stringify(resp)) as MpcHistoryResponse;
  mesclarSeriesVivas(resp, [amostraViva(5, 2, null, false)], ["cv_1"]);
  expect(resp).toEqual(congelado);
});

test("var_id sem histórico nem amostra viva devolve série vazia (sempre uma série por id pedido)", () => {
  const resp = historico("cv_1", [{ d: 0, v: 1, sp: null, auto: false }]);
  const [, vazia] = mesclarSeriesVivas(resp, [], ["cv_1", "cv_2"]);
  expect(vazia).toEqual({ id: "cv_2", t: [], v: [], sp: [], auto: [] });
});

test("chave de consulta muda com a janela — react-query recarrega ao trocar de janela", () => {
  const a = chaveHistoricoOperacao(462, "mpc1", ["cv_1"], 1800);
  const b = chaveHistoricoOperacao(462, "mpc1", ["cv_1"], 7200);
  expect(a).not.toEqual(b);
});
