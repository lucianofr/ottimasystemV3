/**
 * Regra de preservação de zoom no eixo x das tendências, isolada do motor de propósito:
 * `motorTrend.ts` importa o CSS do uPlot e não é carregável pelo runner de unidade (Node puro,
 * sem bundler), então a sutileza que decide se o dado vivo apaga o recorte do usuário fica
 * aqui — mesmo padrão de `trendOperacao.ts` ao lado de `TrendOperacao.tsx`.
 */

/** Faixa do eixo x: extremos em segundos de época. O gráfico produz (faixa visível, quando há
 *  zoom) e o export consome (recorte do CSV) — mora aqui, junto da regra de zoom, para o
 *  `TrendChart` não precisar importar tipo do módulo de CSV. */
export interface FaixaX {
  readonly min: number;
  readonly max: number;
}

/**
 * Há zoom em X aplicado? Compara as escalas da instância com a extensão do próprio dado.
 *
 * `x` é `ArrayLike<number>` porque `uPlot.AlignedData` admite `TypedArray` além de `number[]`,
 * e daqui só se lê `length` e dois índices.
 */
export function estaZoomadoEmX(
  min: number | undefined,
  max: number | undefined,
  x: ArrayLike<number>,
): boolean {
  if (x.length === 0) return false;
  return (min ?? 0) > x[0] || (max ?? 0) < x[x.length - 1];
}
