import type uPlot from "uplot";

import type { HistoryResponse } from "../../lib/api";
import type { FaixaX } from "./plugins";

const SEPARADOR = ";";

export interface ColunaCsv {
  readonly rotulo: string;
  readonly eu: string;
}

/** Carimbo local `YYYY-MM-DD HH:MM:SS.mmm`: o eixo x do gráfico é local, e o arquivo precisa
 *  casar com o que o engenheiro leu na tela. `toISOString` é UTC — daí descontar o offset. */
export function carimboLocal(ms: number): string {
  const local = new Date(ms - new Date(ms).getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 23).replace("T", " ");
}

/**
 * Rótulo de coluna em célula CSV segura.
 *
 * `tags.name`/`tags.eu` são texto livre no servidor (`schemas/tags.py`, só `min_length=1`): um
 * nome com `;`, aspas ou quebra de linha deslocaria TODAS as colunas do arquivo — corrupção
 * silenciosa, que o engenheiro descobre depois de já ter tirado conclusão da planilha errada.
 * Duas regras, as duas fora de discussão porque isto é fronteira de confiança:
 *
 * - quoting RFC 4180: célula com `;`, `"`, CR ou LF vai entre aspas, com `"` interno duplicado;
 * - guarda de injeção de fórmula: nome começando com `=`, `+`, `-` ou `@` é prefixado com `'`,
 *   senão o Excel AVALIA o conteúdo ao abrir (`=1+1`, `=HYPERLINK(...)`) — tag renomeada por
 *   quem tem acesso à engenharia não deve virar execução na estação de operação.
 */
function celulaTexto(bruto: string): string {
  const neutralizado = /^[=+\-@]/.test(bruto) ? `'${bruto}` : bruto;
  return /[;"\r\n]/.test(neutralizado)
    ? `"${neutralizado.replace(/"/g, '""')}"`
    : neutralizado;
}

/**
 * Export tabular da janela que o gráfico está mostrando: uma linha por instante amostrado, uma
 * coluna por pena selecionada, na ordem da seleção.
 *
 * Recebe a MATRIZ do uPlot (`montarMatriz`), não a resposta do histórico, de propósito: o
 * arquivo é o que está na tela, com a mesma semântica já decidida ali — eixo x = união dos
 * carimbos das penas (cada tag amostra por exceção), valor mantido entre amostras (ZOH, o que
 * a variável de fato fez no processo) e célula vazia exatamente onde o gráfico desenha gap
 * (qualidade `q === 2` ou silêncio além do teto de carry-forward). Exportar as amostras cruas
 * em vez da matriz daria uma planilha quase diagonal — as penas raramente compartilham carimbo,
 * o recorder grava cada tag com alguns ms de diferença — e um gráfico do Excel picado em pontos
 * soltos.
 *
 * Linha inteiramente vazia é DESCARTADA, e isso não é cosmética: o eixo do gráfico carrega
 * marcas de silêncio sintéticas (`eixoComMarcasDeSilencio`) — carimbos que o render inventa no
 * meio de um silêncio geral só para cortar o traço. Num arquivo de dados um instante que nunca
 * foi medido é mentira, e como a marca cai sempre além do teto de TODAS as penas, ela é
 * exatamente a linha sem nenhum valor. Descartá-las garante a invariante do export: todo
 * carimbo do arquivo é um instante em que alguma tag amostrou de verdade.
 *
 * Dialeto pt-BR (`;` + decimal vírgula + BOM UTF-8): abre com colunas e números reconhecidos no
 * duplo clique do Excel da estação. Em pandas: `read_csv(..., sep=";", decimal=",")`.
 */
export function montarCsvTrend(dados: uPlot.AlignedData, colunas: readonly ColunaCsv[]): string {
  const [x, ...penas] = dados;
  const cabecalho = [
    "timestamp",
    ...colunas.map((coluna) =>
      celulaTexto(coluna.eu ? `${coluna.rotulo} (${coluna.eu})` : coluna.rotulo),
    ),
  ];
  const corpo: string[] = [];
  x.forEach((segundos, k) => {
    const celulas = penas.map((pena) => {
      const valor = pena[k];
      return valor === null || valor === undefined ? "" : String(valor).replace(".", ",");
    });
    if (celulas.every((celula) => celula === "")) return;
    corpo.push([carimboLocal(segundos * 1000), ...celulas].join(SEPARADOR));
  });
  return `\ufeff${[cabecalho.join(SEPARADOR), ...corpo].join("\r\n")}\r\n`;
}

/**
 * Recorta a matriz na faixa visível do eixo x.
 *
 * O uPlot tem arrasto em X (`pluginZoomX`, desfeito pelo "Reset layout"), então "a janela
 * que está sendo mostrada" nem sempre é a janela BUSCADA: com zoom ativo o arquivo entregaria
 * mais dado do que o engenheiro está vendo. `faixa === null` (sem zoom) devolve a matriz
 * intacta, sem cópia. O eixo é crescente por pré-condição do uPlot, então o recorte é um par de
 * índices — não varredura com filtro por linha.
 */
export function recortarEmX(dados: uPlot.AlignedData, faixa: FaixaX | null): uPlot.AlignedData {
  const [x] = dados;
  if (faixa === null || x.length === 0) return dados;
  let inicio = 0;
  while (inicio < x.length && x[inicio] < faixa.min) inicio++;
  let fim = x.length - 1;
  while (fim >= inicio && x[fim] > faixa.max) fim--;
  if (inicio === 0 && fim === x.length - 1) return dados;
  const tamanho = Math.max(0, fim - inicio + 1);
  const eixo = Array.from({ length: tamanho }, (_, k) => x[inicio + k]);
  const penas = dados
    .slice(1)
    .map((pena) => Array.from({ length: tamanho }, (_, k) => pena[inicio + k] ?? null));
  return [eixo, ...penas];
}

/**
 * Nome do arquivo: carimbo do primeiro instante exportado, do último e o MODO da resposta.
 *
 * O modo entra no nome porque `bruto` e `1m` produzem arquivos de forma idêntica — janela acima
 * de 2 h vem do CAgg de 1 minuto (RF-802), e um relatório que misture amostra com média de
 * bucket sem dizer qual é qual é armadilha. A data do fim só é omitida quando é a mesma do
 * início: a janela chega a 7 dias (`JANELA_MAX_SEGUNDOS`), e `..._17-09-01` num arquivo que
 * termina uma semana depois se lê como "1 minuto de dado".
 */
export function nomeCsvTrend(dados: uPlot.AlignedData, modo: HistoryResponse["mode"]): string {
  const x = dados[0];
  const [inicio, fimCompleto] = [x[0] ?? 0, x[x.length - 1] ?? 0].map((segundos) =>
    carimboLocal(segundos * 1000)
      .slice(0, 19)
      .replace(/[ :]/g, "-"),
  );
  const fim = fimCompleto.slice(0, 10) === inicio.slice(0, 10) ? fimCompleto.slice(11) : fimCompleto;
  return `trend_${inicio}_${fim}_${modo === "1m" ? "1m" : "bruto"}.csv`;
}
