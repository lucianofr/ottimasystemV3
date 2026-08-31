import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { LoopDetailOut, LoopNodeOut } from "./types";

export type { LoopNodeOut } from "./types";

/** `nome do flow · rótulo do bloco` — mesmo rótulo de `rotuloFuzzy`
 *  (`../fuzzy/useFuzzyBlocks.ts`), usado pelo combobox da página. */
export function rotuloLoop(no: LoopNodeOut): string {
  return `${no.flow_name} · ${no.label}`;
}

const CHAVE = ["operate", "loop"] as const;

/**
 * Descoberta dos blocos malha do projeto ativo (ADR-039 §4.10 — `GET /api/operate/loop`).
 * Defaults do react-query (`staleTime: 0`), mesmo padrão de `useFuzzyBlocks`.
 */
export function useLoops(): UseQueryResult<LoopNodeOut[]> {
  return useQuery({
    queryKey: CHAVE,
    queryFn: () => api<LoopNodeOut[]>("/api/operate/loop"),
  });
}

/** Config resumida do faceplate (permitted/limites/escala/sintonia) — aba somente leitura. */
export function useLoopConfig(flowId: number, blockId: string): UseQueryResult<LoopDetailOut> {
  return useQuery({
    queryKey: [...CHAVE, "config", flowId, blockId],
    queryFn: () => api<LoopDetailOut>(`/api/operate/loop/${String(flowId)}/${blockId}`),
    enabled: blockId !== "",
  });
}
