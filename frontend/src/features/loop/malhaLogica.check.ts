/**
 * Checks puros da lógica da tela MALHA (RF-645, RF-646): seleção da malha, predicado "ao vivo",
 * escala da barra, ids das penas, ponta viva e limpeza de nulos do histórico.
 *
 * Vale um teste porque errar aqui é silencioso: um quadro velho tratado como ao vivo, ou uma
 * amostra nula virando zero no trend, leva o operador a ler uma malha que não está como parece.
 */

import { expect, test } from "@playwright/test";

import { ROTULO_CONEXAO } from "../flows/useFlowStatus";
import {
  malhaAoVivo,
  leiturasVivasMalha,
  motivoSemEstado,
  penasIniciais,
  percentualBarra,
  resolverSelecao,
  semNulos,
  varsMalha,
  type CondicaoMalha,
} from "./malhaLogica";
import type { LoopNodeOut, LoopState } from "./types";

const A: LoopNodeOut = { flow_id: 1, flow_name: "F", block_id: "a", label: "A", type: "pid_loop", n_loops: 1 };
const B: LoopNodeOut = { ...A, flow_id: 2, block_id: "b", label: "B" };
const ESTADO: LoopState = {
  ts: "2026-11-27T12:00:00Z", target: "auto", actual: "auto", permitted: ["oos", "man", "auto"],
  pv: 152.3, pv_ok: true, sp: 150, out: 37.5, u_pct: 37.5, man_out: 0,
  hi_limited: false, lo_limited: false, diag: {}, channel: 0,
};

test("seleção: casa com a URL; sem casar cai na primeira; lista vazia é null", () => {
  expect(resolverSelecao([A, B], "2", "b")).toBe(B);
  expect(resolverSelecao([A, B], null, null)).toBe(A);
  expect(resolverSelecao([A, B], "9", "apagado")).toBe(A); // Review Focus 3
  expect(resolverSelecao([A, B], "1", "b")).toBe(A);       // flow e bloco de malhas diferentes
  expect(resolverSelecao([], "1", "a")).toBeNull();
});

const VIVO: CondicaoMalha = { canal: "aberto", estadoFlow: "running", estado: ESTADO, tsBase: undefined };

test("ao vivo: cada um dos quatro termos derruba sozinho", () => {
  expect(malhaAoVivo(VIVO)).toBe(true);
  expect(malhaAoVivo({ ...VIVO, canal: "reconectando" })).toBe(false); // socket caiu
  expect(malhaAoVivo({ ...VIVO, estadoFlow: "stopped" })).toBe(false);
  expect(malhaAoVivo({ ...VIVO, estadoFlow: undefined })).toBe(false);
  expect(malhaAoVivo({ ...VIVO, estado: undefined })).toBe(false);
});

test("quadro retido de antes da montagem ou da reconexão não é ao vivo; o seguinte é", () => {
  expect(malhaAoVivo({ ...VIVO, tsBase: ESTADO.ts })).toBe(false);
  const novo = { ...ESTADO, ts: "2026-11-27T12:00:01Z" };
  expect(malhaAoVivo({ ...VIVO, estado: novo, tsBase: ESTADO.ts })).toBe(true);
});

test("aviso de sem-estado diz a causa: canal, flow parado, falha ou espera do primeiro quadro", () => {
  expect(motivoSemEstado("reconectando", "running", "running")).toBe(ROTULO_CONEXAO.reconectando);
  expect(motivoSemEstado("conectando", "running", "running")).toBe(ROTULO_CONEXAO.conectando);
  expect(motivoSemEstado("sessao_invalida", "running", "running")).toBe(
    "Sessão inválida ou expirada: entre novamente para ver a malha ao vivo.",
  );
  expect(motivoSemEstado("aberto", "running", "stopped")).toBe("Flow parado — sem estado ao vivo");
  expect(motivoSemEstado("aberto", "stopped", "running")).toBe("Flow parado — sem estado ao vivo");
  expect(motivoSemEstado("aberto", "failed", "running")).toBe("Flow em falha — sem estado ao vivo");
  expect(motivoSemEstado("aberto", "running", "running")).toBe("Aguardando estado ao vivo da malha…");
  expect(motivoSemEstado("aberto", undefined, undefined)).toBe("Aguardando estado ao vivo da malha…");
});

test("barra usa a faixa do bloco, não 0–100", () => {
  expect(percentualBarra(150, 50, 250)).toBe(50);
  expect(percentualBarra(12, 4, 20)).toBe(50);
});

// Review Focus 4
test("barra nunca sai de 0–100 nem vira NaN", () => {
  expect(percentualBarra(300, 50, 250)).toBe(100);
  expect(percentualBarra(-5, 50, 250)).toBe(0);
  expect(percentualBarra(null, 50, 250)).toBe(0);
  expect(percentualBarra(10, 100, 100)).toBe(0);
  expect(percentualBarra(10, 100, 0)).toBe(0);
  expect(percentualBarra(Number.NaN, 0, 100)).toBe(0);
});

test("penas: ids da API por canal e pré-seleção do canal 0", () => {
  expect(varsMalha(1)).toEqual([
    { id: "pv", rotulo: "PV" }, { id: "sp", rotulo: "SP" }, { id: "out", rotulo: "OUT" },
  ]);
  const tres = varsMalha(3);
  expect(tres.map((v) => v.id)).toEqual(["pv", "sp", "out", "pv:1", "sp:1", "out:1", "pv:2", "sp:2", "out:2"]);
  expect(tres[3].rotulo).toBe("PV · canal 2");
  expect(tres[0].rotulo).toBe("PV · canal 1");
  // Review Focus 5: 9 variáveis, teto de 6 penas — só o canal 0 nasce marcado
  expect(penasIniciais(tres)).toEqual(["pv", "sp", "out"]);
});

test("ponta viva: uma leitura por pena e canal; PV nula fica de fora, PV sem qualidade entra", () => {
  const c1 = { ...ESTADO, channel: 1, pv: null, sp: 10, out: 20 };
  const vivas = leiturasVivasMalha([{ ...ESTADO, pv_ok: false }, undefined, c1]);
  expect(vivas.get("pv")).toEqual({ ts: ESTADO.ts, v: 152.3 });
  expect(vivas.get("sp:1")).toEqual({ ts: ESTADO.ts, v: 10 });
  expect(vivas.has("pv:1")).toBe(false);
});

// Review Focus 5
test("histórico: amostra nula some com o seu carimbo, nunca vira zero", () => {
  const limpo = semNulos({
    mode: "raw", start: "2026-11-27T11:00:00Z", end: "2026-11-27T12:00:00Z",
    series: [
      { var_id: "pv", t: ["t1", "t2", "t3"], v: [1, null, 3] },
      { var_id: "sp", t: ["t1"], v: [null] },
    ],
  });
  expect(limpo.series).toEqual([
    { var_id: "pv", t: ["t1", "t3"], v: [1, 3] },
    { var_id: "sp", t: [], v: [] },
  ]);
  expect(limpo.mode).toBe("raw");
});
