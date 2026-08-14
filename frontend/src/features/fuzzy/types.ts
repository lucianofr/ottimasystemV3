/**
 * Tipos da FUZZY OPERATE (ADR-030) — re-exports dos contratos GERADOS, nunca espelhos manuais:
 * REST de `src/lib/api-types.ts` (openapi-typescript, `npm run generate:api`) e o payload do
 * canal `fuzzy.state.<flow_id>.<block_id>` de `src/lib/contracts.gen.ts`
 * (`ottima_core.contracts_export`). Mesma convenção de `useMpcs.ts`/`api.ts`.
 */

import type { components } from "../../lib/api-types";

export type { FuzzyState, FuzzyTermDegree, FuzzyVarState } from "../../lib/contracts.gen";

export type FuzzyNodeOut = components["schemas"]["FuzzyNodeOut"];
export type FuzzyPortOut = components["schemas"]["FuzzyPortOut"];
export type FuzzyOutputPortOut = components["schemas"]["FuzzyOutputPortOut"];
export type FuzzyDetailOut = components["schemas"]["FuzzyDetailOut"];
export type FuzzyIntrospection = components["schemas"]["FuzzyIntrospection"];
export type FuzzyVariableOut = components["schemas"]["FuzzyVariableOut"];
export type FuzzyTermOut = components["schemas"]["FuzzyTermOut"];
export type FuzzyRuleBlockOut = components["schemas"]["FuzzyRuleBlockOut"];
export type FuzzyHistoryResponse = components["schemas"]["FuzzyHistoryResponse"];
export type FuzzyHistorySeries = components["schemas"]["FuzzyHistorySeries"];
