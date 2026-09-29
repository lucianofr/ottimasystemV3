import { expect, test } from "@playwright/test";

import {
  faixaJanelaX,
  fimAoAvancar,
  fimAoVoltar,
  passoDeslocamento,
  RETENCAO_PADRAO_S,
} from "./useJanelaDeslizante";

/**
 * `useJanelaDeslizante.ts` — lógica pura do pan `<` / `>` dos dois trends. O hook em si é só
 * `useState` em volta destas funções; o que precisa de prova é o passo, o clamp na retenção
 * e a retomada do modo ao vivo.
 */

const AGORA = 1_700_000_000;
const JANELA_30M = 1800;

test("passoDeslocamento é meia janela", () => {
  expect(passoDeslocamento(JANELA_30M)).toBe(900);
});

test("voltar a partir do modo ao vivo ancora em agora menos meia janela", () => {
  expect(fimAoVoltar(null, AGORA, JANELA_30M, RETENCAO_PADRAO_S)).toBe(AGORA - 900);
});

test("voltar acumula meia janela por clique", () => {
  const primeiro = fimAoVoltar(null, AGORA, JANELA_30M, RETENCAO_PADRAO_S);
  expect(fimAoVoltar(primeiro, AGORA, JANELA_30M, RETENCAO_PADRAO_S)).toBe(AGORA - 1800);
});

test("voltar não passa do início da retenção: a janela inteira precisa caber nela", () => {
  const fundo = AGORA - RETENCAO_PADRAO_S;
  const fim = fimAoVoltar(fundo + 10, AGORA, JANELA_30M, RETENCAO_PADRAO_S);
  expect(fim).toBe(fundo + JANELA_30M);
  expect(fim - JANELA_30M).toBeGreaterThanOrEqual(fundo);
});

test("voltar com retenção menor que a janela não joga a vista para o futuro", () => {
  expect(fimAoVoltar(null, AGORA, JANELA_30M, 600)).toBe(AGORA);
});

test("avançar no modo ao vivo continua ao vivo", () => {
  expect(fimAoAvancar(null, AGORA, JANELA_30M)).toBeNull();
});

test("avançar no passado anda meia janela para a frente", () => {
  expect(fimAoAvancar(AGORA - 3600, AGORA, JANELA_30M)).toBe(AGORA - 2700);
});

test("avançar até alcançar o presente retoma o modo ao vivo", () => {
  expect(fimAoAvancar(AGORA - 900, AGORA, JANELA_30M)).toBeNull();
});

test("avançar além do presente retoma o modo ao vivo, nunca aponta para o futuro", () => {
  expect(fimAoAvancar(AGORA - 100, AGORA, JANELA_30M)).toBeNull();
});

test("voltar e avançar o mesmo número de cliques devolve ao modo ao vivo", () => {
  let fim: number | null = null;
  fim = fimAoVoltar(fim, AGORA, JANELA_30M, RETENCAO_PADRAO_S);
  fim = fimAoVoltar(fim, AGORA, JANELA_30M, RETENCAO_PADRAO_S);
  expect(fim).toBe(AGORA - 1800);
  fim = fimAoAvancar(fim, AGORA, JANELA_30M);
  expect(fim).toBe(AGORA - 900);
  fim = fimAoAvancar(fim, AGORA, JANELA_30M);
  expect(fim).toBeNull();
});

test("janela maior desloca mais por clique", () => {
  const janela8h = 28800;
  expect(fimAoVoltar(null, AGORA, janela8h, RETENCAO_PADRAO_S)).toBe(AGORA - 14400);
});

test("faixaJanelaX ao vivo termina em agora e abre a janela inteira para trás", () => {
  expect(faixaJanelaX(null, JANELA_30M, AGORA)).toEqual([AGORA - JANELA_30M, AGORA]);
});

test("faixaJanelaX ao vivo anda com o relógio: o tique de 1 s move as duas bordas", () => {
  const [a0, b0] = faixaJanelaX(null, JANELA_30M, AGORA);
  const [a1, b1] = faixaJanelaX(null, JANELA_30M, AGORA + 1);
  expect([a1 - a0, b1 - b0]).toEqual([1, 1]);
});

test("faixaJanelaX deslizado termina no fim escolhido, sem seguir o relógio", () => {
  const fim = AGORA - 3600;
  expect(faixaJanelaX(fim, JANELA_30M, AGORA)).toEqual([fim - JANELA_30M, fim]);
  expect(faixaJanelaX(fim, JANELA_30M, AGORA + 600)).toEqual([fim - JANELA_30M, fim]);
});

test("faixaJanelaX reserva a janela pedida, não a extensão do dado: largura é sempre a janela", () => {
  // O defeito que a política corrige: `range` automático desenhava só o pedaço com amostra.
  for (const janela of [90, JANELA_30M, 28800]) {
    const [inicio, fim] = faixaJanelaX(null, janela, AGORA);
    expect(fim - inicio).toBe(janela);
  }
});
