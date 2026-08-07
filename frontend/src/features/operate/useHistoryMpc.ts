import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api, type MpcHistoryResponse } from "../../lib/api";
import { INTERVALO_POLLING_OPERACAO_MS } from "./trendOperacao";

/** `queryKey` do histórico do trend de operação — exportada para o hook e para o teste puro
 *  que prova que trocar de janela muda a chave (§7.4-6, brief 5.1: "troca de janela recarrega"
 *  — o react-query refaz a busca sempre que a `queryKey` muda). */
export function chaveHistoricoOperacao(
  flowId: number,
  blockId: string,
  varIds: readonly string[],
  janelaSegundos: number,
): readonly unknown[] {
  return ["history-mpc", flowId, blockId, varIds.join(","), janelaSegundos];
}

/**
 * Histórico do bloco MPC (`GET /api/history/mpc`, spec F5 §2.4) na janela pedida, com polling
 * de 5 s (brief 5.1). Mesmo padrão de `useHistory.ts` (F2): janela recalculada a cada busca
 * (`end = agora`), fora da `queryKey` — senão cada poll criaria entrada nova de cache e o
 * gráfico piscaria.
 */
export function useHistoryMpc(
  flowId: number,
  blockId: string,
  varIds: readonly string[],
  janelaSegundos: number,
): UseQueryResult<MpcHistoryResponse> {
  return useQuery({
    queryKey: chaveHistoricoOperacao(flowId, blockId, varIds, janelaSegundos),
    queryFn: () => {
      const fim = new Date();
      const inicio = new Date(fim.getTime() - janelaSegundos * 1000);
      const busca = new URLSearchParams({
        flow_id: String(flowId),
        block_id: blockId,
        var_ids: varIds.join(","),
        start: inicio.toISOString(),
        end: fim.toISOString(),
      });
      return api<MpcHistoryResponse>(`/api/history/mpc?${busca.toString()}`);
    },
    enabled: varIds.length > 0,
    refetchInterval: INTERVALO_POLLING_OPERACAO_MS,
  });
}
