import { expect, test } from "@playwright/test";

import {
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
