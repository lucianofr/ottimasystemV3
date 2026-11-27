import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { LoopHistoryResponse } from "./types";

/** Mesma cadência do trend fuzzy (`useHistoryFuzzy`) e do de operação MPC. */
const INTERVALO_POLLING_LOOP_MS = 5000;

/**
 * Histórico PV/SP/OUT de uma malha (`GET /api/history/loop`, ADR-039 §4.10) — espelho de
 * `useHistoryFuzzy`, com polling de 5 s. `fimEpochS` congela a janela
 * (`useJanelaDeslizante`, `../trend`) e desliga o polling: a vista congelada não muda sozinha
 * embaixo do operador, e deslizar a janela é outra busca (entra na chave). `v` pode vir `null`
 * (PV com qualidade ruim) — quem consome decide o que fazer com a lacuna (`historicoComLacunas`).
 */
export function useHistoryLoop(
  flowId: number,
  blockId: string,
  varIds: readonly string[],
  janelaSegundos: number,
  fimEpochS: number | null = null,
): UseQueryResult<LoopHistoryResponse> {
  return useQuery({
    queryKey: ["history-loop", flowId, blockId, varIds.join(","), janelaSegundos, fimEpochS],
    queryFn: () => {
      const fim = fimEpochS !== null ? new Date(fimEpochS * 1000) : new Date();
      const inicio = new Date(fim.getTime() - janelaSegundos * 1000);
      const busca = new URLSearchParams({
        flow_id: String(flowId),
        block_id: blockId,
        var_ids: varIds.join(","),
        start: inicio.toISOString(),
        end: fim.toISOString(),
      });
      return api<LoopHistoryResponse>(`/api/history/loop?${busca.toString()}`);
    },
    enabled: varIds.length > 0,
    refetchInterval: fimEpochS === null ? INTERVALO_POLLING_LOOP_MS : false,
  });
}
