import type { MpcState, SstoRun } from "../../lib/contracts.gen";
import type { MpcNodeOut } from "./useMpcs";

/**
 * Mapper puro do sumário do otimizador (espelho do padrão `gradeVariaveis.ts`): travessia
 * projeção + estado ao vivo → linhas do card, isolada de `ResumoOtimizador.tsx` para ser
 * testada pura (`resumoOtimizador.check.ts`) sem arrastar o DOM.
 */

/** Rótulo de exibição de cada `objective` (mesmo vocabulário do modal de config,
 *  `TabVariables.tsx` — a operação e a engenharia falam a mesma língua). */
export const ROTULO_OBJETIVO: Record<string, string> = {
  none: "Nenhuma",
  maximize: "Maximizar",
  minimize: "Minimizar",
  observe_limit: "Observar limites",
  target: "Alvo (Target)",
  psv: "PSV (valor preferido)",
  equalize: "Equalizar",
};

/** Rótulo do `SstoRun.status` — badge do card. */
export const ROTULO_STATUS_SSTO: Record<SstoRun["status"], string> = {
  optimal: "Ótimo",
  relaxed: "Relaxado",
  infeasible: "Inviável",
  unbounded: "Ilimitado",
  error: "Erro",
};

export interface LinhaOtimizador {
  id: string;
  nome: string;
  eu: string;
  rotuloObjetivo: string;
  atual: number | null;
  alvo: number | null;
}

export interface ResumoOtimizadorDados {
  /** Execução vigente (canal ao vivo ou cold-start REST); `null` = nunca rodou. */
  ssto: SstoRun | null;
  /** Variáveis com `objective !== "none"`, na ordem MV → CV → Restrição. */
  linhas: LinhaOtimizador[];
  /** Nomes legíveis das variáveis em `given_up` (desistência por inviabilidade). */
  desistencias: string[];
}

/**
 * Precedência de dado: o `ssto` do canal ao vivo (carry-forward do `reduzir`) ganha do
 * cold-start REST (`useUltimoSsto`) — o WS é sempre mais fresco que a última linha gravada.
 * Variável otimizada sem valor ao vivo ainda (`mpcState` não chegou) mostra `—`.
 */
export function resumoOtimizador(
  mpc: MpcNodeOut,
  mpcState: MpcState | undefined,
  fallback: SstoRun | null,
): ResumoOtimizadorDados {
  const ssto = mpcState?.ssto ?? fallback;

  const linhas: LinhaOtimizador[] = [];
  const nomes = new Map<string, string>();
  for (const mv of mpc.variables.mvs) nomes.set(mv.id, mv.name);
  for (const cv of mpc.variables.cvs) nomes.set(cv.id, cv.name);
  for (const co of mpc.variables.constraints) nomes.set(co.id, co.name);

  const alvoDe = (id: string, ehMv: boolean): number | null =>
    (ehMv ? ssto?.mv_target[id] : ssto?.cv_target[id]) ?? null;
  const atualDe = (id: string): number | null => mpcState?.vars[id]?.v ?? null;

  for (const mv of mpc.variables.mvs) {
    if (mv.objective === "none") continue;
    linhas.push({
      id: mv.id,
      nome: mv.name,
      eu: mv.eu,
      rotuloObjetivo: ROTULO_OBJETIVO[mv.objective],
      atual: atualDe(mv.id),
      alvo: alvoDe(mv.id, true),
    });
  }
  for (const cv of mpc.variables.cvs) {
    if (cv.objective === "none") continue;
    linhas.push({
      id: cv.id,
      nome: cv.name,
      eu: cv.eu,
      rotuloObjetivo: ROTULO_OBJETIVO[cv.objective],
      atual: atualDe(cv.id),
      alvo: alvoDe(cv.id, false),
    });
  }
  for (const co of mpc.variables.constraints) {
    if (co.objective === "none") continue;
    linhas.push({
      id: co.id,
      nome: co.name,
      eu: co.eu,
      rotuloObjetivo: ROTULO_OBJETIVO[co.objective],
      atual: atualDe(co.id),
      alvo: alvoDe(co.id, false),
    });
  }

  const desistencias = (ssto?.given_up ?? []).map((id) => nomes.get(id) ?? id);

  return { ssto, linhas, desistencias };
}
