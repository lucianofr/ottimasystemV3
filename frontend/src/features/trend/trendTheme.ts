import type uPlot from "uplot";

/**
 * Penas na ordem da spec F2 §9.3; o tamanho da lista É o limite de séries do gráfico.
 * Cada entrada casa o token lido em runtime (canvas) com a classe usada na legenda (DOM).
 * Os dois são literais inteiros de propósito: `getPropertyValue` precisa do nome exato e o
 * Tailwind extrai utilitários varrendo o texto-fonte, então `bg-pen-${n}` nunca seria gerado.
 */
const PENAS = [
  { token: "--color-pen-1", classe: "bg-pen-1" },
  { token: "--color-pen-2", classe: "bg-pen-2" },
  { token: "--color-pen-3", classe: "bg-pen-3" },
  { token: "--color-pen-4", classe: "bg-pen-4" },
  { token: "--color-pen-5", classe: "bg-pen-5" },
  { token: "--color-pen-6", classe: "bg-pen-6" },
] as const;

/** Limite de penas ⇔ limite de 6 tags do `/api/history` (spec F2 §8). */
export const LIMITE_PENAS = PENAS.length;

/** Faixa de cor de cada pena na legenda, na mesma ordem das penas do gráfico. */
export const CLASSES_PENA: readonly string[] = PENAS.map((pena) => pena.classe);

/** A Regra do Número Tabular (DESIGN.md §Typography): valor sempre em pt-BR, sem notação científica. */
export const FORMATO_VALOR = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });

const SEGUNDOS_2H = 7200;
const SEGUNDOS_24H = 86400;
const ALTURA_TEXTO_EIXO = 11;

export interface TemaTrend {
  /** Cores das penas, na ordem dos tokens. */
  readonly penas: readonly string[];
  /** Grade, ticks e bordas dos eixos (token Linha). */
  readonly linha: string;
  /** Texto de eixo (Texto Secundário). */
  readonly texto: string;
  /** Pilha de fontes mono, para compor o shorthand do canvas. */
  readonly mono: string;
  /** Azul Industrial (DESIGN §Primary) — pena de SP comandado no trend de operação
   *  (`TrendOperacao.tsx`, spec F5 §7.4-6). */
  readonly accent: string;
  /** Fundo Poço — sombreamento da banda low/high de Restrição no trend de operação. */
  readonly poco: string;
}

/**
 * Lê os tokens do `tokens.css` em runtime. A paleta tem uma fonte só: duplicar os literais
 * OKLCH aqui criaria um segundo lugar para mudá-los (DESIGN.md §Do's).
 */
export function lerTemaTrend(): TemaTrend {
  const estilo = getComputedStyle(document.documentElement);
  return {
    penas: PENAS.map((pena) => estilo.getPropertyValue(pena.token).trim()),
    linha: estilo.getPropertyValue("--color-hairline").trim(),
    texto: estilo.getPropertyValue("--color-fg-muted").trim(),
    mono: estilo.getPropertyValue("--font-mono").trim(),
    accent: estilo.getPropertyValue("--color-accent").trim(),
    poco: estilo.getPropertyValue("--color-well").trim(),
  };
}

export interface OpcoesTrend {
  readonly tema: TemaTrend;
  /** Um rótulo por pena, na ordem da seleção. */
  readonly rotulos: readonly string[];
  /** Duração da janela em segundos: define a granularidade do eixo de tempo. */
  readonly janelaSegundos: number;
  readonly largura: number;
  readonly altura: number;
}

/**
 * uPlot re-vestido (DESIGN.md §Don'ts: nada com cara default). Fundo Poço fica no
 * contêiner via classe; aqui vão só as cores que o canvas desenha.
 */
export function construirOpcoes(opcoes: OpcoesTrend): uPlot.Options {
  const { tema, rotulos, janelaSegundos, largura, altura } = opcoes;
  const fonte = `${String(ALTURA_TEXTO_EIXO)}px ${tema.mono}`;
  const grade = { stroke: tema.linha, width: 1 };

  // Janela curta pede segundos; janela longa pede a data, senão os ticks viram ambíguos.
  const formatoTempo = new Intl.DateTimeFormat("pt-BR", {
    ...(janelaSegundos > SEGUNDOS_24H ? { day: "2-digit" as const, month: "2-digit" as const } : {}),
    hour: "2-digit",
    minute: "2-digit",
    ...(janelaSegundos <= SEGUNDOS_2H ? { second: "2-digit" as const } : {}),
  });

  return {
    width: largura,
    height: altura,
    legend: { show: false },
    cursor: { y: false, points: { show: false } },
    axes: [
      {
        stroke: tema.texto,
        font: fonte,
        grid: grade,
        ticks: grade,
        border: grade,
        space: 90,
        values: (_u, marcas) => marcas.map((s) => formatoTempo.format(new Date(s * 1000))),
      },
      {
        stroke: tema.texto,
        font: fonte,
        grid: grade,
        ticks: grade,
        border: grade,
        size: 64,
        values: (_u, marcas) => marcas.map((v) => FORMATO_VALOR.format(v)),
      },
    ],
    series: [
      { label: "Tempo" },
      ...rotulos.map((label, indice) => ({
        label,
        stroke: tema.penas[indice % tema.penas.length],
        width: 1.5,
        // Qualidade ruim vira null e precisa aparecer como buraco na pena, não como reta.
        spanGaps: false,
        points: { show: false },
      })),
    ],
  };
}
