import { expect, test } from "@playwright/test";

import { alinharNoEixo, eixoComMarcasDeSilencio, montarEixoUniao } from "./alinhamento";

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

// ----------------------------------------------------------------------------------------
// eixoComMarcasDeSilencio: marcas de silêncio no eixo compartilhado
// ----------------------------------------------------------------------------------------

test("silêncio simultâneo de todas as penas ganha marca no eixo e alinharNoEixo abre gap", () => {
  // Regressão (tela de operação, 2026-08-20): quando TODAS as penas calam juntas (flow
  // parado, conexão fora), a união não tem carimbo no silêncio e o uPlot desenha reta
  // contínua entre as duas bordas — a interpolação que a Regra do Canal Redundante
  // (DESIGN.md) proíbe. A marca dá a `alinharNoEixo` um carimbo em que nenhuma pena
  // amostrou ⇒ `null`, e o traço corta como corta quando só uma pena cala.
  const penas = [
    [T0, T0 + 2, T0 + 52, T0 + 54],
    [T0 + 1, T0 + 3, T0 + 53, T0 + 55],
  ];
  const eixo = eixoComMarcasDeSilencio(montarEixoUniao(penas), 20);

  // Sem a marca a união seria [0,1,2,3,52,53,54,55] — reta de 3→52 no uPlot. A marca cai
  // no meio da zona nula (a + tetoS, b): (3 + 20 + 52) / 2 = 37,5.
  expect(eixo).toContain(T0 + 37.5);
  expect(alinharNoEixo(eixo, penas[0], [1, 1, 2, 2], 20)[eixo.indexOf(T0 + 37.5)]).toBeNull();
});

test("silêncio de uma pena só, com eixo puxado por outra: marca corta a pena que calou", () => {
  const penas = [
    [T0, T0 + 2, T0 + 52, T0 + 54],
    [T0, T0 + 54], // pena viva só nas bordas: o eixo continua sem carimbo no silêncio
  ];
  const eixo = eixoComMarcasDeSilencio(montarEixoUniao(penas), 20);

  expect(eixo).toContain(T0 + 37);
  expect(alinharNoEixo(eixo, penas[0], [1, 1, 2, 2], 20)[eixo.indexOf(T0 + 37)]).toBeNull();
});

test("silêncio menor ou igual ao teto não ganha marca: sem gap falso", () => {
  const penas = [[T0, T0 + 2, T0 + 12, T0 + 14]];

  expect(eixoComMarcasDeSilencio(montarEixoUniao(penas), 20)).toEqual([
    T0,
    T0 + 2,
    T0 + 12,
    T0 + 14,
  ]);
});

test("marca não atravessa a fronteira do passado: seção futura é da predição", () => {
  // Gap de 58 s (teto 20): a marca cai em (2 + 20 + 60) / 2 = 41. Com fronteira em 60 ela
  // sobrevive; em 40 é descartada — o futuro pertence à predição (`spanGaps: true`), e
  // medição marcada ali mentiria nela.
  const penas = [[T0, T0 + 2, T0 + 60]];

  expect(eixoComMarcasDeSilencio(montarEixoUniao(penas), 20, T0 + 60)).toEqual([
    T0,
    T0 + 2,
    T0 + 41,
    T0 + 60,
  ]);
  expect(eixoComMarcasDeSilencio(montarEixoUniao(penas), 20, T0 + 40)).toEqual([
    T0,
    T0 + 2,
    T0 + 60,
  ]);
});

test("silêncio entre o teto e o dobro do teto também ganha marca: uma marca por gap basta", () => {
  // Faixa que a primeira versão do primitivo deixava passar: gap de 28 s com teto 20 —
  // a zona nula (22, 30) existe, mas nenhuma grade de múltiplos do teto caía dentro dela.
  // `spanGaps: false` corta o traço com um único `null`.
  const penas = [[T0, T0 + 2, T0 + 30, T0 + 32]];
  const eixo = eixoComMarcasDeSilencio(montarEixoUniao(penas), 20);

  expect(eixo).toContain(T0 + 26); // (2 + 20 + 30) / 2
  expect(alinharNoEixo(eixo, penas[0], [1, 1, 2, 2], 20)[eixo.indexOf(T0 + 26)]).toBeNull();
});
