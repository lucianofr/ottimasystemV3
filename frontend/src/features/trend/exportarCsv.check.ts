import { expect, test } from "@playwright/test";
import type uPlot from "uplot";

import type { HistoryResponse, HistorySeries } from "../../lib/api";
import { carimboLocal, montarCsvTrend, nomeCsvTrend, recortarEmX } from "./exportarCsv";
import { montarMatriz } from "./useHistory";

/**
 * `exportarCsv.ts` — export do que o gráfico do trend está mostrando. O que precisa de prova:
 * uma linha por instante do eixo x na ordem cronológica, colunas na ordem da SELEÇÃO (não a da
 * resposta do servidor), célula vazia onde o gráfico desenha gap, e o dialeto pt-BR que faz o
 * arquivo abrir no duplo clique do Excel (BOM + `;` + decimal vírgula).
 */

const T0 = Date.parse("2026-01-01T12:00:00Z");

function carimbo(deslocamentoS: number): string {
  return new Date(T0 + deslocamentoS * 1000).toISOString();
}

function linhas(csv: string): string[] {
  return csv.replace("\ufeff", "").trimEnd().split("\r\n");
}

test("uma linha por instante do eixo x, colunas na ordem passada", () => {
  const csv = montarCsvTrend(
    [
      [T0 / 1000, T0 / 1000 + 10],
      [1.5, 2.5],
      [null, 9],
    ],
    [
      { rotulo: "FT-204", eu: "m3/h" },
      { rotulo: "LT-201", eu: "%" },
    ],
  );

  expect(linhas(csv)).toEqual([
    "timestamp;FT-204 (m3/h);LT-201 (%)",
    `${carimboLocal(T0)};1,5;`,
    `${carimboLocal(T0 + 10_000)};2,5;9`,
  ]);
});

test("tag sem unidade de engenharia não ganha parênteses vazios", () => {
  const csv = montarCsvTrend([[T0 / 1000], [1]], [{ rotulo: "CALC_1", eu: "" }]);
  expect(linhas(csv)[0]).toBe("timestamp;CALC_1");
});

test("BOM UTF-8 e CRLF: abre no Excel pt-BR sem passo de importação", () => {
  const csv = montarCsvTrend([[T0 / 1000], [1]], [{ rotulo: "FT-204", eu: "m3/h" }]);
  expect(csv.startsWith("\ufeff")).toBe(true);
  expect(csv.endsWith("\r\n")).toBe(true);
});

test("nome do arquivo carrega a janela exportada e o modo", () => {
  const inicio = carimboLocal(T0).slice(0, 19).replace(/[ :]/g, "-");
  const fim = carimboLocal(T0 + 1_800_000)
    .slice(11, 19)
    .replace(/:/g, "-");
  const matriz: uPlot.AlignedData = [[T0 / 1000, T0 / 1000 + 1800], [1, 2]];
  expect(nomeCsvTrend(matriz, "raw")).toBe(`trend_${inicio}_${fim}_bruto.csv`);
  // Agregado de 1 min (janela > 2 h) não pode sair com nome de amostra bruta.
  expect(nomeCsvTrend(matriz, "1m")).toBe(`trend_${inicio}_${fim}_1m.csv`);
});

test("janela que cruza o dia leva a data do fim no nome", () => {
  const doisDias = 2 * 86_400;
  const matriz: uPlot.AlignedData = [[T0 / 1000, T0 / 1000 + doisDias], [1, 2]];
  const inicio = carimboLocal(T0).slice(0, 19).replace(/[ :]/g, "-");
  const fim = carimboLocal(T0 + doisDias * 1000)
    .slice(0, 19)
    .replace(/[ :]/g, "-");
  expect(nomeCsvTrend(matriz, "1m")).toBe(`trend_${inicio}_${fim}_1m.csv`);
});

/**
 * Fronteira de confiança: `tags.name`/`tags.eu` são texto livre no servidor. Sem quoting, um
 * nome com `;` desloca todas as colunas do arquivo; sem a guarda de `=`, o Excel AVALIA o
 * cabeçalho ao abrir.
 */
test("rótulo com separador, aspas ou quebra de linha é aspeado (RFC 4180)", () => {
  const csv = montarCsvTrend(
    [[T0 / 1000], [1], [2], [3]],
    [
      { rotulo: "FT;204", eu: "m3/h" },
      { rotulo: 'FT"204', eu: "" },
      { rotulo: "FT\r\n204", eu: "" },
    ],
  ).replace("\ufeff", "");
  // O cabeçalho não pode ser lido por `split("\r\n")`: o CRLF do terceiro rótulo está DENTRO
  // das aspas, que é justamente o que o quoting garante ser dado e não fim de linha.
  expect(csv.startsWith('timestamp;"FT;204 (m3/h)";"FT""204";"FT\r\n204"\r\n')).toBe(true);
});

test("rótulo começando com =, +, - ou @ é neutralizado contra injeção de fórmula", () => {
  const csv = montarCsvTrend(
    [[T0 / 1000], [1], [2], [3]],
    [
      { rotulo: '=HYPERLINK("http://x")', eu: "" },
      { rotulo: "-FT204", eu: "%" },
      { rotulo: "@soma", eu: "" },
    ],
  );
  // O primeiro também ganha aspas — tem `"` no meio; a guarda é o `'` antes do `=`.
  expect(linhas(csv)[0]).toBe(`timestamp;"'=HYPERLINK(""http://x"")";'-FT204 (%);'@soma`);
});

/**
 * Zoom em X (arrasto do uPlot): "a janela que está sendo mostrada" passa a ser o recorte, não a
 * janela buscada. Sem o recorte o arquivo entregaria mais dado do que está na tela — e o nome
 * do arquivo mentiria junto, porque deriva dos extremos da matriz exportada.
 */
test("recorte em X fica na faixa visível; sem zoom devolve a matriz intacta", () => {
  const matriz: uPlot.AlignedData = [
    [100, 200, 300, 400],
    [1, 2, 3, 4],
    [10, null, 30, 40],
  ];
  expect(recortarEmX(matriz, null)).toBe(matriz);
  expect(recortarEmX(matriz, { min: 150, max: 350 })).toEqual([
    [200, 300],
    [2, 3],
    [null, 30],
  ]);
  // Faixa cobrindo tudo não copia: é o caso do "zoom" que não recorta nada.
  expect(recortarEmX(matriz, { min: 50, max: 450 })).toBe(matriz);
});

test("nome do arquivo segue o recorte do zoom, não a janela buscada", () => {
  const matriz: uPlot.AlignedData = [[T0 / 1000, T0 / 1000 + 600, T0 / 1000 + 1800], [1, 2, 3]];
  const recortada = recortarEmX(matriz, { min: T0 / 1000 + 300, max: T0 / 1000 + 1200 });
  const carimboMeio = carimboLocal(T0 + 600_000).slice(0, 19).replace(/[ :]/g, "-");
  expect(nomeCsvTrend(recortada, "raw")).toBe(
    `trend_${carimboMeio}_${carimboMeio.slice(11)}_bruto.csv`,
  );
});

/**
 * Paridade com o gráfico: o CSV sai da mesma matriz do uPlot, então gap de qualidade `q === 2`
 * e carry-forward entre carimbos chegam ao arquivo exatamente como a pena os desenha. Este é o
 * contrato que o export promete — a prova roda o `montarMatriz` de verdade, não uma matriz
 * escrita à mão.
 */
test("paridade com o gráfico: gap de qualidade bad vazio, carry-forward preenchido", () => {
  const series: HistorySeries[] = [
    // FT amostra em 0 e 10; o ponto de 10 é bad ⇒ gap.
    { tag_id: 1, t: [carimbo(0), carimbo(10)], v: [1, 2], q: [0, 2] },
    // LT amostra só em 10: em 0 não tem valor (nada antes), em 10 entra o dela.
    { tag_id: 2, t: [carimbo(10)], v: [9], q: [0] },
  ];
  const resposta: HistoryResponse = {
    mode: "raw",
    start: carimbo(0),
    end: carimbo(10),
    series,
  };
  const csv = montarCsvTrend(montarMatriz(resposta, [1, 2]), [
    { rotulo: "FT-204", eu: "m3/h" },
    { rotulo: "LT-201", eu: "%" },
  ]);

  expect(linhas(csv)).toEqual([
    "timestamp;FT-204 (m3/h);LT-201 (%)",
    `${carimboLocal(T0)};1;`,
    `${carimboLocal(T0 + 10_000)};;9`,
  ]);
});

/**
 * Invariante do export: todo carimbo do arquivo é instante em que alguma tag amostrou. O eixo
 * do gráfico carrega marca de silêncio sintética (`eixoComMarcasDeSilencio`) no meio de um
 * silêncio geral — carimbo que o render inventa. Num arquivo de dados isso seria mentira.
 */
test("marca de silêncio sintética do gráfico não vira linha do arquivo", () => {
  // Silêncio de 60 s no modo raw (teto = 20 s) ⇒ o eixo ganha uma marca entre as duas amostras.
  const resposta: HistoryResponse = {
    mode: "raw",
    start: carimbo(0),
    end: carimbo(60),
    series: [{ tag_id: 1, t: [carimbo(0), carimbo(60)], v: [1, 2], q: [0, 0] }],
  };
  const matriz = montarMatriz(resposta, [1]);
  expect(matriz[0]).toHaveLength(3); // 2 amostras + 1 marca sintética

  const corpo = linhas(montarCsvTrend(matriz, [{ rotulo: "FT-204", eu: "m3/h" }])).slice(1);
  expect(corpo).toEqual([`${carimboLocal(T0)};1`, `${carimboLocal(T0 + 60_000)};2`]);
});