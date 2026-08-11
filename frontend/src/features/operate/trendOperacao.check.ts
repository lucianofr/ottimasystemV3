import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import type { MpcHistoryResponse } from "../../lib/api";
import type { MpcPrediction } from "../../lib/contracts.gen";
import {
  JANELAS_OPERACAO,
  JANELA_PADRAO_ID,
  OPCOES_DEGRAU_MV,
  TETO_PENAS_OPERACAO,
  TOKENS_PENA_OPERACAO,
  atribuirCoresPenas,
  dividirSpPorAuto,
  mesclarSeriesVivas,
  montarOverlayPrevisao,
  selecionarPenasDefault,
  type AmostraViva,
} from "./trendOperacao";
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
  return { ts: carimbo(d), vars: { cv_1: { v, sp, status: null } }, auto };
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

test("âncora do overlay é prediction.ts, nunca o ts do quadro (§3.5, F5R-01)", () => {
  const previsao: MpcPrediction = {
    ts: carimbo(100), // prediction.ts: fronteira em que o solve foi despachado
    t: [0, 10, 20],
    cv: [[1, 2, 3]],
    mv: [[5, 5.5, 6]],
  };
  const overlay = montarOverlayPrevisao(previsao);

  // A série futura começa em prediction.ts (T0+100), não em algum `ts` de quadro diferente
  // (ex.: T0+105, que seria o `MpcState.ts` proibido pela regra global 2).
  expect(overlay.tAbs).toEqual([100, 110, 120].map((d) => T0 + d));
  expect(overlay.agora).toBe(T0 + 100);
  expect(overlay.cv).toEqual([[1, 2, 3]]);
  expect(overlay.mv).toEqual([[5, 5.5, 6]]);
});

test("quadro com t: [] (fora de AUTO) remove o overlay sem apagar o histórico (§3.4)", () => {
  const resp = historico("cv_1", [
    { d: 0, v: 1, sp: 1.5, auto: true },
    { d: 5, v: 1.1, sp: 1.5, auto: true },
  ]);
  const [serie] = mesclarSeriesVivas(resp, [], ["cv_1"]);
  const overlay = montarOverlayPrevisao({ ts: carimbo(5), t: [], cv: [], mv: [] });

  expect(overlay).toEqual({ tAbs: [], agora: null, cv: [], mv: [] });
  // O histórico não é tocado pela ausência de predição — são funções independentes.
  expect(serie.t).toEqual([0, 5].map((d) => T0 + d));
  expect(serie.v).toEqual([1, 1.1]);
});

test("degrau fantasma da MV usa align: -1 — align: +1 é proibido (§3.3)", () => {
  expect(OPCOES_DEGRAU_MV.align).toBe(-1);
});

test("SP dessaturada exatamente onde auto=false — PV-tracking não é SP comandado (§2.2-1, F5R-21)", () => {
  const sp = [1, 2, 3, 4];
  const auto = [true, true, false, false];
  const divisao = dividirSpPorAuto(sp, auto);

  expect(divisao.comandado).toEqual([1, 2, null, null]);
  expect(divisao.rastreado).toEqual([null, null, 3, 4]);
});

test("SP dessaturada: null original nunca vira valor em nenhum dos dois traços", () => {
  const divisao = dividirSpPorAuto([null, 5], [false, true]);
  expect(divisao.comandado).toEqual([null, 5]);
  expect(divisao.rastreado).toEqual([null, null]);
});

test("defaults: CVs (PV+SP, 2 penas cada) ligam na ordem do config até o teto de 8 penas", () => {
  const cvs = [{ id: "cv_a" }, { id: "cv_b" }, { id: "cv_c" }, { id: "cv_d" }, { id: "cv_e" }];
  const selecao = selecionarPenasDefault(cvs, [], [], []);

  expect(selecao.map((p) => p.id)).toEqual(["cv_a", "cv_b", "cv_c", "cv_d", "cv_e"]);
  expect(selecao.map((p) => p.ligada)).toEqual([true, true, true, true, false]);
  // A 5ª CV custaria 2 penas, mas só sobrava 0 depois das 4 primeiras (4×2 = 8 = teto).
  expect(selecao.map((p) => p.excedente)).toEqual([false, false, false, false, true]);
});

test("defaults: Restrições (banda, 1 pena) preenchem o que sobrou do teto depois das CVs, na ordem do config", () => {
  const cvs = [{ id: "cv_1" }, { id: "cv_2" }, { id: "cv_3" }]; // 3×2 = 6 penas
  const constraints = [{ id: "co_1" }, { id: "co_2" }, { id: "co_3" }]; // sobram 2 penas
  const selecao = selecionarPenasDefault(cvs, constraints, [], []);
  const restricoes = selecao.filter((p) => p.categoria === "constraint");

  expect(restricoes.map((p) => p.id)).toEqual(["co_1", "co_2", "co_3"]);
  expect(restricoes.map((p) => p.ligada)).toEqual([true, true, false]);
  expect(restricoes.map((p) => p.excedente)).toEqual([false, false, true]);
});

test("defaults: MVs e DVs nascem desligadas (opt-in pela legenda), mesmo com o teto livre", () => {
  const selecao = selecionarPenasDefault([], [], [{ id: "mv_1" }], [{ id: "dv_1" }]);

  expect(selecao).toEqual([
    { id: "mv_1", categoria: "mv", ligada: false, excedente: false },
    { id: "dv_1", categoria: "dv", ligada: false, excedente: false },
  ]);
});

test("teto de penas de operação é 8 (distinto do teto de 6 do trend de engenharia)", () => {
  expect(TETO_PENAS_OPERACAO).toBe(8);
});

// -------------------------------------------------------------------- paleta de 8 penas (§6.6-5)

/** Lê o valor cru do token direto de `tokens.css` — a paleta tem fonte única (DESIGN.md
 *  §Do's); duplicar os literais OKLCH aqui criaria um segundo lugar para divergir.
 *  `node:fs` aqui é seguro porque `tsconfig.build.json` exclui `*.check.ts` do build de
 *  produção (a imagem roda `npm ci` sem `@types/node`). */
const TOKENS_CSS = readFileSync(
  fileURLToPath(new URL("../../styles/tokens.css", import.meta.url)),
  "utf-8",
);

function valorToken(nome: string): string {
  const casado = TOKENS_CSS.match(new RegExp(`${nome}:\\s*([^;]+);`));
  if (casado === null) throw new Error(`token ${nome} não encontrado em tokens.css`);
  return casado[1].trim();
}

test("paleta do trend de operação tem 8 tokens, um por posição do teto (§6.6-5)", () => {
  expect(TOKENS_PENA_OPERACAO).toHaveLength(TETO_PENAS_OPERACAO);
});

test("as 8 cores de pena são distintas entre si — comparação por conjunto, não caso a caso (§6.6-5)", () => {
  const coresPenas = TOKENS_PENA_OPERACAO.map(valorToken);
  expect(new Set(coresPenas).size).toBe(TETO_PENAS_OPERACAO);
});

test("nenhuma cor de pena colide com cor reservada de severidade nem com o Azul Único (§6.6-5, DESIGN §Colors)", () => {
  const coresPenas = new Set(TOKENS_PENA_OPERACAO.map(valorToken));
  const coresReservadas = ["--color-alarm", "--color-warn", "--color-success", "--color-accent"].map(
    valorToken,
  );

  for (const reservada of coresReservadas) {
    expect(coresPenas.has(reservada)).toBe(false);
  }
});

test("atribuirCoresPenas — a mesma função que TrendOperacao.tsx usa para colorir cada pena — devolve 8 cores distintas para 8 ids, sem wrap antes do teto (§6.6-5)", () => {
  const ids = ["cv_1", "cv_2", "co_1", "co_2", "co_3", "mv_1", "mv_2", "dv_1"]; // 8 ids
  const coresResolvidas = TOKENS_PENA_OPERACAO.map(valorToken); // valores reais de tokens.css
  const mapa = atribuirCoresPenas(ids, coresResolvidas);

  expect(mapa.size).toBe(8);
  // Comparação por conjunto, não caso a caso: 8 ids distintos ⇒ 8 cores distintas.
  expect(new Set(mapa.values()).size).toBe(8);
});

test("atribuirCoresPenas: id além do teto de 8 recicla por módulo — mesmo comportamento de antes (§6.6-5)", () => {
  const ids = Array.from({ length: 9 }, (_, i) => `v${String(i)}`); // 9º id, 1 além do teto
  const coresResolvidas = TOKENS_PENA_OPERACAO.map(valorToken);
  const mapa = atribuirCoresPenas(ids, coresResolvidas);

  expect(mapa.get("v8")).toBe(mapa.get("v0"));
});
