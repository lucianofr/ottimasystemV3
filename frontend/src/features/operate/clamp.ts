/**
 * Clamp client-side — tarefa 4.4 do plano F5b (spec F5 §7.4-5; RF-702/704). Espelho leve dos
 * limites publicados pelo backend (`limits` de MV, `sp_limits` de CV): evita um round-trip
 * óbvio de validação, mas o servidor continua sendo a barreira real — a resposta 202/422 do
 * `POST /sp`|`/mv` é quem decide de fato (RF-704).
 *
 * Funções puras, sem I/O: mesmo padrão de `pendencia.ts` (4.2).
 */

/** Faixa `{min, max}` — mesmo shape do schema `Limits` do backend (`MvOut.limits`,
 *  `CvOut.sp_limits`), consumido sem conversão pelo faceplate. */
export type Faixa = { min: number; max: number };

/** Borda inclusiva nos dois lados: `valor === min` ou `valor === max` está dentro. */
export function dentroDaFaixa(valor: number, faixa: Faixa): boolean {
  return valor >= faixa.min && valor <= faixa.max;
}

export function clampNaFaixa(valor: number, faixa: Faixa): number {
  return Math.min(faixa.max, Math.max(faixa.min, valor));
}
