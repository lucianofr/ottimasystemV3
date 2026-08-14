import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { FuzzyNodeOut } from "./types";

export type { FuzzyNodeOut } from "./types";

/** `nome do flow · nome do bloco` — mesmo rótulo de `rotuloMpc` (`../operate/useMpcs.ts`),
 *  reaproveitado pelo combobox "Bloco fuzzy" da página. */
export function rotuloFuzzy(no: FuzzyNodeOut): string {
  return `${no.flow_name} · ${no.block_name}`;
}

const CHAVE = ["operate", "fuzzy"] as const;

/**
 * Descoberta dos blocos fuzzy do projeto ativo (ADR-030, espelho de `useMpcs`/RF-701 —
 * `GET /api/operate/fuzzy`). Sem `staleTime`/`refetchOnWindowFocus` explícitos: o default do
 * react-query (`staleTime: 0`) já revalida ao montar e ao focar a aba, mesmo padrão do resto
 * do app.
 */
export function useFuzzyBlocks(): UseQueryResult<FuzzyNodeOut[]> {
  return useQuery({
    queryKey: CHAVE,
    queryFn: () => api<FuzzyNodeOut[]>("/api/operate/fuzzy"),
  });
}
