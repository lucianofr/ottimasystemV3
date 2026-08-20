/**
 * Alinhamento de pena num eixo x compartilhado (carry-forward-com-teto). Três telas de trend
 * — engenharia (`montarMatriz`, `useHistory.ts`), fuzzy (`montarMatrizFuzzy`,
 * `../fuzzy/historicoFuzzy.ts`) e operação (`montarColunas`/`TrendOperacao.tsx`, via
 * `../operate/trendOperacao.ts`) — uniam carimbos de várias penas num eixo x e repetiam o
 * último valor conhecido até um teto, cada uma com sua própria variante (cursor multi-série vs
 * Map por coluna). Este módulo é a fonte única do primitivo (ARCH-02,
 * `docs/reports/arch/arch-review-20260815.md`): as três telas montam o eixo união e chamam
 * `alinharNoEixo` por pena. Funções puras, sem I/O.
 */

/** Eixo x compartilhado do uPlot: união ordenada e sem repetição dos carimbos de todas as
 *  penas — cada tag/variável amostra por exceção, no seu próprio ritmo, e o gráfico precisa de
 *  um eixo x só. */
export function montarEixoUniao(tempos: readonly (readonly number[])[]): number[] {
  const uniao = new Set<number>();
  for (const t of tempos) for (const instante of t) uniao.add(instante);
  return [...uniao].sort((a, b) => a - b);
}

/**
 * Coluna de uma pena no eixo x compartilhado (união dos carimbos de todas as penas do
 * gráfico, `montarEixoUniao`).
 *
 * Cada pena tem carimbos próprios — amostragem por exceção, ou (no trend de operação) tags OPC
 * adensando numa taxa que as sem tag não têm. Nos instantes em que a pena não amostrou ela
 * repete o último valor conhecido, que é o que o valor fez de fato no processo: sem isso a pena
 * mais esparsa fica com um `null` entre cada par de carimbos alheios, vira trecho de 1 ponto e
 * não desenha nada (`spanGaps: false`, sem marcador). Três coisas cortam a repetição e as três
 * viram gap: `null` amostrado na própria série (qualidade ruim, SP dividido por `auto`, ponto
 * sem valor — o `null` é conhecido, não silêncio, então o traço fica cortado até a próxima
 * amostra com valor, sem voltar ao valor anterior ao gap), silêncio além de `tetoS` (não chegou
 * amostra nenhuma — recorder fora do ar, worker morto, flow parado) e carimbo além de `limiteS`
 * — fronteira opcional (só o trend de operação usa: a seção futura da predição não pode receber
 * medição repetida, `TrendOperacao.tsx`). `tetoS = 0` desliga a repetição por inteiro, que é
 * como a própria predição entra (só nos seus carimbos).
 *
 * `eixoX` crescente é pré-condição (uPlot já exige x monotônico): num salto para trás a
 * diferença fica negativa e o teto nunca dispararia.
 */
export function alinharNoEixo(
  eixoX: readonly number[],
  t: readonly number[],
  valores: readonly (number | null | undefined)[],
  tetoS: number,
  limiteS = Number.POSITIVE_INFINITY,
): (number | null)[] {
  const porT = new Map(t.map((ts, i) => [ts, valores[i] ?? null]));
  let atual: number | null = null;
  let ultimaAmostra = Number.NEGATIVE_INFINITY;
  return eixoX.map((ts) => {
    const amostra = porT.get(ts);
    if (amostra !== undefined) {
      atual = amostra;
      ultimaAmostra = ts;
    }
    if (ts > limiteS) return null;
    return ts - ultimaAmostra > tetoS ? null : atual;
  });
}

/**
 * Eixo x com marcas de silêncio (carry-forward-com-teto, parte 2). `alinharNoEixo` só
 * produz `null` nos carimbos que EXISTEM no eixo compartilhado — mas a união
 * (`montarEixoUniao`) não tem carimbo nenhum num silêncio em que TODAS as penas calam
 * juntas (flow parado, conexão fora do ar, recorder morto), e o uPlot então liga as duas
 * bordas do silêncio com reta contínua: a interpolação que a Regra do Canal Redundante
 * (DESIGN.md) proíbe. Plantar uma marca dentro de cada gap maior que `tetoS` dá a
 * `alinharNoEixo` um carimbo em que nenhuma pena amostrou ⇒ `null`, e o traço corta
 * exatamente como corta quando só uma pena cala (`spanGaps: false`: um único `null` já
 * parte o segmento).
 *
 * A marca cai no MEIO da zona nula `(a + tetoS, b)`: em `a + tetoS` exato o carry ainda
 * vale (`alinharNoEixo` testa `> tetoS`, estrito — marcar ali não abriria gap nenhum), e
 * qualquer ponto estritamente depois já é `null` por teto. Uma marca por gap basta — a
 * zona é contínua, e grade de múltiplos carimbos só acrescentaria `null` onde o traço já
 * está cortado. Silêncio de exatamente `tetoS` não ganha marca: é a própria fronteira do
 * carry, comportamento anterior. Marcas além de `limiteS` são descartadas: a seção futura
 * pertence à predição (`spanGaps: true`), e medição marcada ali mentiria nela. Todo
 * carimbo da união tem pelo menos uma amostra, então o silêncio é derivável só do eixo —
 * `tempos` não entra aqui.
 */
export function eixoComMarcasDeSilencio(
  eixoX: readonly number[],
  tetoS: number,
  limiteS = Number.POSITIVE_INFINITY,
): number[] {
  if (eixoX.length === 0 || tetoS <= 0) return [...eixoX];
  const marcas: number[] = [];
  for (let i = 1; i < eixoX.length; i++) {
    const anterior = eixoX[i - 1];
    if (eixoX[i] - anterior <= tetoS) continue;
    const marca = (anterior + tetoS + eixoX[i]) / 2;
    if (marca <= limiteS) marcas.push(marca);
  }
  if (marcas.length === 0) return [...eixoX];
  return [...eixoX, ...marcas].sort((a, b) => a - b);
}
