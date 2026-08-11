import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { components } from "../../lib/api-types";

/** `GET /api/history/ssto/last` — `null` quando o bloco nunca executou o SSTO. */
export type SstoLastOut = components["schemas"]["SstoLastOut"];

/**
 * Última execução do SSTO do bloco (ADR-027 §11) — cold-start do sumário do otimizador:
 * sem ela o card ficaria vazio até o próximo ciclo do MPC (Ts_mpc pode ser minutos). O
 * canal ao vivo tem precedência assim que o primeiro `ssto` chega (ver `ResumoOtimizador`).
 */
export function useUltimoSsto(
  flowId: number,
  blockId: string,
): UseQueryResult<SstoLastOut | null> {
  return useQuery({
    queryKey: ["history", "ssto", flowId, blockId],
    queryFn: () =>
      api<SstoLastOut | null>(
        `/api/history/ssto/last?flow_id=${String(flowId)}&block_id=${encodeURIComponent(blockId)}`,
      ),
  });
}
