import type uPlot from "uplot";

/**
 * Escala Y por variável — módulo compartilhado pelo trend de engenharia (`TrendPage`) e pelo
 * trend de operação (`TrendOperacao`).
 *
 * O problema: uPlot sem bloco `scales` coloca todas as penas numa escala só, então uma vazão
 * em t/h achata um nível em % contra o eixo. Aqui cada variável ganha uma escala própria
 * (`v<id>`), em modo automático por padrão ou fixada em `[min, max]` pelo operador.
 *
 * Funções puras + duas de armazenamento; nada de React, para o mesmo módulo servir às duas
 * telas e ser testável fora do DOM.
 */

export interface EscalaVar {
  /** `true` = autoscale do uPlot; `false` = faixa fixa `[min, max]`. */
  readonly auto: boolean;
  readonly min: number | null;
  readonly max: number | null;
}

/** Estado inicial de qualquer variável: autoscale, sem faixa digitada. */
export const ESCALA_AUTO: EscalaVar = { auto: true, min: null, max: null };

/**
 * Chave da escala uPlot de uma variável. O prefixo `v` existe porque uPlot reserva `x` para
 * o tempo e trata `y` como a escala default — colidir com qualquer um dos dois faria a
 * variável herdar a escala errada.
 */
export function chaveEscala(varId: string): string {
  return `v${varId}`;
}

export interface VariavelComEscala {
  readonly id: string;
  readonly escala: EscalaVar;
}

export interface EscalasUplot {
  /** Só as escalas Y: quem monta as opções acrescenta a de tempo (`x`). */
  readonly scales: uPlot.Scales;
  readonly scaleKeyPorVar: ReadonlyMap<string, string>;
}

/**
 * Bloco `scales` do uPlot, uma entrada por variável.
 *
 * Faixa manual só é honrada com os dois extremos preenchidos e `min < max`. Meio preenchida
 * (o operador ainda está digitando) ou invertida cai para autoscale — um gráfico que some
 * enquanto se digita ensina o operador a não usar o controle.
 */
export function construirEscalasUplot(vars: readonly VariavelComEscala[]): EscalasUplot {
  const scales: uPlot.Scales = {};
  const scaleKeyPorVar = new Map<string, string>();
  for (const { id, escala } of vars) {
    const chave = chaveEscala(id);
    scaleKeyPorVar.set(id, chave);
    const { min, max } = escala;
    scales[chave] =
      !escala.auto && min !== null && max !== null && min < max
        ? { auto: false, range: [min, max] }
        : { auto: true };
  }
  return { scales, scaleKeyPorVar };
}

function numeroOuNulo(valor: unknown): number | null | undefined {
  if (valor === null) return null;
  if (typeof valor === "number" && Number.isFinite(valor)) return valor;
  return undefined;
}

function normalizar(valor: unknown): EscalaVar | null {
  if (typeof valor !== "object" || valor === null) return null;
  const bruto = valor as { auto?: unknown; min?: unknown; max?: unknown };
  if (typeof bruto.auto !== "boolean") return null;
  const min = numeroOuNulo(bruto.min);
  const max = numeroOuNulo(bruto.max);
  if (min === undefined || max === undefined) return null;
  return { auto: bruto.auto, min, max };
}

/**
 * Escalas persistidas. Preferência de layout não é dado de processo: conteúdo corrompido,
 * de uma versão anterior ou de um storage bloqueado devolve `{}` e a tela nasce em
 * autoscale, nunca com erro na cara do operador. Entradas individuais fora de forma são
 * descartadas uma a uma — uma variável estragada não derruba as outras.
 */
export function lerEscalas(chaveStorage: string): Record<string, EscalaVar> {
  try {
    const cru = localStorage.getItem(chaveStorage);
    if (cru === null) return {};
    const lido: unknown = JSON.parse(cru);
    if (typeof lido !== "object" || lido === null) return {};
    const saida: Record<string, EscalaVar> = {};
    for (const [id, valor] of Object.entries(lido as Record<string, unknown>)) {
      const escala = normalizar(valor);
      if (escala !== null) saida[id] = escala;
    }
    return saida;
  } catch {
    return {};
  }
}

/** Grava as escalas; cota estourada ou storage bloqueado é silencioso pelo mesmo motivo. */
export function gravarEscalas(chaveStorage: string, valor: Record<string, EscalaVar>): void {
  try {
    localStorage.setItem(chaveStorage, JSON.stringify(valor));
  } catch {
    // Preferência de layout não vale derrubar a tela de operação.
  }
}
