/**
 * Tipos do sensor virtual (RF-585/586/589) — re-exports dos contratos GERADOS de
 * `src/lib/api-types.ts` (`npm run generate:api`), nunca espelhos manuais. Mesma convenção de
 * `features/fuzzy/types.ts`.
 */

import type { components } from "../../lib/api-types";

export type SoftSensorBlockOut = components["schemas"]["SoftSensorBlockOut"];
export type LabVariableOut = components["schemas"]["LabVariableOut"];
export type LabVariableCreate = components["schemas"]["LabVariableCreate"];
export type LabSampleIn = components["schemas"]["LabSampleIn"];
export type LabSampleOut = components["schemas"]["LabSampleOut"];
export type LabImportOut = components["schemas"]["LabImportOut"];
export type DatasetOut = components["schemas"]["DatasetOut"];
export type DatasetCreate = components["schemas"]["DatasetCreate"];
export type DatasetCreated = components["schemas"]["DatasetCreated"];
export type JobAccepted = components["schemas"]["JobAccepted"];
export type MlJobOut = components["schemas"]["MlJobOut"];
export type SoftSensorModelOut = components["schemas"]["SoftSensorModelOut"];
export type SoftSensorUseOut = components["schemas"]["SoftSensorUseOut"];
export type TrainJobIn = components["schemas"]["TrainJobIn"];
