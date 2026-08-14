/**
 * Lógica pura da FUZZY OPERATE (ADR-030): normas de implicação/agregação para a silhueta
 * agregada client-side de saída (o servidor só manda `FuzzyIntrospection` + `FuzzyState` —
 * ele NUNCA calcula a silhueta, só o grau por termo já pós-implicação), geometria de escala
 * do SVG (`PainelVariavelFuzzy.tsx`) e montagem dos rodapés `μ(x)`/`ŷ`. Sem I/O, sem DOM —
 * mesmo padrão de `clamp.ts`/`pendencia.ts` (`../operate`); testado em `fuzzyMath.check.ts`.
 */

// ----------------------------------------------------------------------------------------
// Normas de implicação/agregação
// ----------------------------------------------------------------------------------------

const IMPLICACOES_SUPORTADAS: Record<string, true> = { Minimum: true, AlgebraicProduct: true };
const AGREGACOES_SUPORTADAS: Record<string, true> = {
  Maximum: true,
  AlgebraicSum: true,
  BoundedSum: true,
  UnboundedSum: true,
};

export function normaImplicacaoSuportada(norma: string | null): boolean {
  return norma !== null && IMPLICACOES_SUPORTADAS[norma] === true;
}

export function normaAgregacaoSuportada(norma: string | null): boolean {
  return norma !== null && AGREGACOES_SUPORTADAS[norma] === true;
}

/** Recorta (Minimum, clip) ou escala (AlgebraicProduct) um ponto da curva do termo pelo grau
 *  de ativação da regra — chamador garante `norma` suportada (`normaImplicacaoSuportada`). */
export function implicar(norma: string, grau: number, y: number): number {
  return norma === "Minimum" ? Math.min(grau, y) : grau * y; // AlgebraicProduct
}

/** Combina pontos já recortados de termos diferentes da mesma saída, ponto a ponto — chamador
 *  garante `norma` suportada (`normaAgregacaoSuportada`). */
export function agregar(norma: string, a: number, b: number): number {
  switch (norma) {
    case "Maximum":
      return Math.max(a, b);
    case "AlgebraicSum":
      return a + b - a * b;
    case "BoundedSum":
      return Math.min(1, a + b);
    default: // UnboundedSum
      return a + b;
  }
}

export interface TermoComGrau {
  readonly y: readonly number[];
  readonly grau: number;
}

/**
 * Silhueta agregada de uma saída: implicação recorta cada termo pelo grau já resolvido no
 * servidor (`FuzzyVarState.terms[].degree`, pós-ativação da regra), agregação combina os
 * termos ponto a ponto na grade `x` comum da variável. `null` quando a norma de implicação ou
 * de agregação declarada no FLL não é uma das suportadas aqui (`aggregation: none` inclusive,
 * que nunca casa com `AGREGACOES_SUPORTADAS`) — a UI cai para sombrear cada termo por
 * opacidade, nunca finge uma norma que não sabe desenhar.
 */
export function silhuetaAgregada(
  termos: readonly TermoComGrau[],
  implicacao: string | null,
  agregacao: string | null,
  nPontos: number,
): readonly number[] | null {
  if (!normaImplicacaoSuportada(implicacao) || !normaAgregacaoSuportada(agregacao)) return null;
  const normaImplicacao = implicacao as string;
  const normaAgregacao = agregacao as string;
  const silhueta = new Array<number>(nPontos).fill(0);
  for (const termo of termos) {
    for (let i = 0; i < nPontos; i++) {
      const recortado = implicar(normaImplicacao, termo.grau, termo.y[i] ?? 0);
      silhueta[i] = agregar(normaAgregacao, silhueta[i], recortado);
    }
  }
  return silhueta;
}

// ----------------------------------------------------------------------------------------
// Geometria de escala do SVG (domínio da variável → viewBox do painel)
// ----------------------------------------------------------------------------------------

/** viewBox padrão dos painéis de variável (`PainelVariavelFuzzy.tsx`) — um viewBox fixo por
 *  painel, a curva nunca precisa saber o tamanho renderizado em CSS. */
export const LARGURA_VIEWBOX = 300;
export const ALTURA_VIEWBOX = 120;

/** Posição X no viewBox de um valor do domínio `[minimo, maximo]`. Domínio degenerado
 *  (`maximo <= minimo`, variável mal configurada) cai no início — nunca divide por zero. */
export function xParaSvg(valor: number, minimo: number, maximo: number, largura: number): number {
  const faixa = maximo - minimo;
  if (faixa <= 0) return 0;
  return ((valor - minimo) / faixa) * largura;
}

/** Posição Y no viewBox de um grau de pertinência `mu` (0..1, clampado) — SVG cresce pra
 *  baixo, o topo do painel é `mu = 1`. */
export function yParaSvg(mu: number, altura: number): number {
  return altura - Math.min(1, Math.max(0, mu)) * altura;
}

/** `points` de um `<polyline>` — a curva de um termo (ou a silhueta agregada) na grade `x[]`
 *  comum da variável. */
export function pontosPolilinha(
  x: readonly number[],
  y: readonly number[],
  minimo: number,
  maximo: number,
  largura: number,
  altura: number,
): string {
  return x
    .map(
      (valor, i) =>
        `${String(xParaSvg(valor, minimo, maximo, largura))},${String(yParaSvg(y[i] ?? 0, altura))}`,
    )
    .join(" ");
}

/** `points` de um `<polygon>` fechado na base (`mu = 0`) — preenchimento translúcido de um
 *  termo ou da silhueta agregada. Grade vazia (variável sem amostra) devolve string vazia. */
export function pontosArea(
  x: readonly number[],
  y: readonly number[],
  minimo: number,
  maximo: number,
  largura: number,
  altura: number,
): string {
  if (x.length === 0) return "";
  const base = yParaSvg(0, altura);
  const xInicio = xParaSvg(x[0], minimo, maximo, largura);
  const xFim = xParaSvg(x[x.length - 1], minimo, maximo, largura);
  const topo = pontosPolilinha(x, y, minimo, maximo, largura, altura);
  return `${String(xInicio)},${String(base)} ${topo} ${String(xFim)},${String(base)}`;
}

/** Posição X no viewBox do valor crisp/defuzzificado, clampado ao domínio da variável — o
 *  marcador nunca sai do painel mesmo com um valor fora de faixa (mesmo espírito de
 *  `percentualNaBarra`, `../operate/FaceplateVariavel.tsx`). */
export function xDoMarcador(valor: number, minimo: number, maximo: number, largura: number): number {
  return xParaSvg(Math.min(maximo, Math.max(minimo, valor)), minimo, maximo, largura);
}

// ----------------------------------------------------------------------------------------
// Rodapés μ(x) / ŷ (notação FuzzyLite — degrau/termo, ponto decimal técnico da fórmula)
// ----------------------------------------------------------------------------------------

export interface GrauDeTermo {
  readonly term: string;
  readonly degree: number;
}

/** `μ(x) = 0.924/MEDIUM + 0.113/HIGH` — só termos com grau > 0 entram na soma (grau 0 não
 *  pertence ao conjunto ativo); nenhum termo ativo devolve `"μ(x) = 0"`. */
export function rodapeMuDeX(termos: readonly GrauDeTermo[]): string {
  const ativos = termos.filter((termo) => termo.degree > 0);
  if (ativos.length === 0) return "μ(x) = 0";
  return `μ(x) = ${ativos.map((termo) => `${termo.degree.toFixed(3)}/${termo.term}`).join(" + ")}`;
}

/** `ŷ = 23.456 °C` — valor crisp ausente (`v === null`: cold-start ou saída sem regra
 *  disparada e sem `default_value`) cai no travessão, nunca finge um número. */
export function rodapeYChapeu(v: number | null, eu: string | null): string {
  if (v === null) return "ŷ = —";
  return eu !== null && eu !== "" ? `ŷ = ${v.toFixed(3)} ${eu}` : `ŷ = ${v.toFixed(3)}`;
}
