/**
 * Tipos da malha PID (ADR-039 §4.10) — re-exports dos contratos GERADOS, nunca espelhos
 * manuais: REST de `src/lib/api-types.ts` e o payload do canal
 * `loop.state.<flow_id>.<block_id>` de `src/lib/contracts.gen.ts`. Mesmo padrão de
 * `features/fuzzy/types.ts`.
 */

import type { components } from "../../lib/api-types";

export type { LoopState } from "../../lib/contracts.gen";

export type LoopNodeOut = components["schemas"]["LoopNodeOut"];
export type LoopDetailOut = components["schemas"]["LoopDetailOut"];
export type LoopTuningOut = components["schemas"]["LoopTuningOut"];
export type FuzzyLoopTuningOut = components["schemas"]["FuzzyLoopTuningOut"];
export type LoopSurfaceOut = components["schemas"]["LoopSurfaceOut"];
