import { expect, test } from "@playwright/test";

import { alinharNoEixo, montarEixoUniao } from "./alinhamento";

/** Base arbitrária: só os deslocamentos em segundos importam (mesmo padrão de useHistory.check.ts). */
const T0 = Date.parse("2026-01-01T12:00:00Z") / 1000;

// ----------------------------------------------------------------------------------------
// Eixo x compartilhado: união dos carimbos de várias penas
// ----------------------------------------------------------------------------------------

test("montarEixoUniao: ordena e deduplica os carimbos de várias penas", () => {
  const eixo = montarEixoUniao([
    [T0, T0 + 10, T0 + 30],
    [T0 + 10, T0 + 20],
  ]);

  expect(eixo).toEqual([T0, T0 + 10, T0 + 20, T0 + 30]);
});

test("montarEixoUniao: nenhuma pena com carimbo devolve eixo vazio", () => {
  expect(montarEixoUniao([[], []])).toEqual([]);
});

// ----------------------------------------------------------------------------------------
// alinharNoEixo: carry-forward-com-teto (ARCH-02 — fonte única do primitivo)
// ----------------------------------------------------------------------------------------

test("eixo compartilhado: pena sem tag OPC repete o último valor nos carimbos das penas adensadas", () => {
  // Regressão: uma CV alimentada por script (sem tag OPC) só tem carimbo na cadência do MPC,
  // enquanto as penas com tag adensam a 4 Hz. Com `null` nos carimbos alheios, cada ponto da
  // pena sem tag virava um trecho de 1 ponto — invisível com `spanGaps: false` e sem marcador.
  const eixoX = [T0, T0 + 0.25, T0 + 0.5, T0 + 0.75, T0 + 1];
  const alinhada = alinharNoEixo(eixoX, [T0, T0 + 1], [33.3, 33.4], 2);

  expect(alinhada).toEqual([33.3, 33.3, 33.3, 33.3, 33.4]);
});

test("carimbo alheio antes da primeira amostra da pena fica vazio: carry-forward não anda para trás", () => {
  const alinhada = alinharNoEixo([T0 - 1, T0, T0 + 1], [T0, T0 + 1], [1, 2], 10);

  expect(alinhada).toEqual([null, 1, 2]);
});

test("carry-forward para no teto: silêncio de mais de 2 cadências vira gap, não reta contínua", () => {
  const eixoX = [T0, T0 + 1, T0 + 2, T0 + 3, T0 + 4, T0 + 5];
  const alinhada = alinharNoEixo(eixoX, [T0, T0 + 5], [1, 2], 2);

  expect(alinhada).toEqual([1, 1, 1, null, null, 2]);
});

test("null da própria série (SP rastreado, qualidade) é o que se repete adiante: continua gap", () => {
  // A repetição carrega o último valor conhecido, e um `null` amostrado é conhecido: o traço
  // fica cortado até a próxima amostra com valor, em vez de voltar ao valor anterior ao gap.
  const eixoX = [T0, T0 + 0.5, T0 + 1, T0 + 1.5, T0 + 2];
  const alinhada = alinharNoEixo(eixoX, [T0, T0 + 1, T0 + 2], [1, null, 3], 2);

  expect(alinhada).toEqual([1, 1, null, null, 3]);
});

test("carry-forward para na fronteira do passado (limiteS): carimbo além dela nunca recebe medição repetida", () => {
  // eixoX = 3 carimbos "de histórico" (0, 5, 10) + 2 carimbos além de `limiteS` (15, 20). A
  // pena amostrou em 0 e 10; 15 e 20 estão dentro do teto de 10 s, então sem o limite o
  // carry-forward desenharia a medição de 10 além da fronteira — só o trend de operação usa
  // este parâmetro (a seção futura da predição, `TrendOperacao.tsx`).
  const eixoX = [0, 5, 10, 15, 20].map((d) => T0 + d);
  const coluna = alinharNoEixo(eixoX, [T0, T0 + 10], [1, 2], 10, T0 + 10);

  expect(coluna).toEqual([1, 1, 2, null, null]);
});

test("limiteS = 0 desliga a repetição por inteiro: pena entra só nos seus próprios carimbos", () => {
  // T0+2 é carimbo alheio (de outra pena) entre dois pontos desta: repetir o valor ali viraria
  // degrau numa pena que deveria ser reta entre pontos (ex.: predição de CV, §3.3).
  const eixoX = [T0, T0 + 2, T0 + 5, T0 + 10];

  expect(alinharNoEixo(eixoX, [T0, T0 + 5, T0 + 10], [10, 20, 30], 0)).toEqual([10, null, 20, 30]);
});
