import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { FuzzyDetailOut } from "./types";

export type { FuzzyDetailOut } from "./types";

/**
 * Introspecção do FLL de um bloco fuzzy (ADR-030 — `GET /api/operate/fuzzy/{flow_id}/{block_id}`):
 * curvas de pertinência amostradas, normas e texto das regras já prontos do servidor — o
 * frontend nunca parseia FLL (ADR-005/ADR-029). Mesmo padrão de detalhe por flow/bloco de
 * `useUltimoSsto.ts` (`../operate`): chave própria por par `flowId`/`blockId`.
 */
export function useFuzzyDetail(flowId: number, blockId: string): UseQueryResult<FuzzyDetailOut> {
  return useQuery({
    queryKey: ["operate", "fuzzy", "detail", flowId, blockId],
    queryFn: () =>
      api<FuzzyDetailOut>(`/api/operate/fuzzy/${String(flowId)}/${encodeURIComponent(blockId)}`),
  });
}
