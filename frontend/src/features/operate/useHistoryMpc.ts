import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api, type MpcHistoryResponse } from "../../lib/api";
import { INTERVALO_POLLING_OPERACAO_MS } from "./trendOperacao";

/** `queryKey` do histórico do trend de operação — exportada para o hook e para o teste puro
 *  que prova que trocar de janela muda a chave (§7.4-6, brief 5.1: "troca de janela recarrega"
 *  — o react-query refaz a busca sempre que a `queryKey` muda). `fimEpochS` entra na chave
 *  pelo mesmo motivo (plano de melhorias, tarefa 2.4): deslizar a janela é outra busca, não
 *  um refresh da mesma — default `null` preserva a chave/assinatura de antes da tarefa. */
export function chaveHistoricoOperacao(
  flowId: number,
  blockId: string,
  varIds: readonly string[],
  janelaSegundos: number,
  fimEpochS: number | null = null,
): readonly unknown[] {
  return ["history-mpc", flowId, blockId, varIds.join(","), janelaSegundos, fimEpochS];
}

/**
 * Histórico do bloco MPC (`GET /api/history/mpc`, spec F5 §2.4) na janela pedida, com polling
 * de 5 s (brief 5.1). Mesmo padrão de `useHistory.ts` (F2): janela recalculada a cada busca
 * (`end = agora`), fora da `queryKey` — senão cada poll criaria entrada nova de cache e o
 * gráfico piscaria.
 *
 * `fimEpochS` (`useJanelaDeslizante`, tarefa 2.4): `null` = ao vivo, comportamento acima
 * inalterado. Fixo, a janela desliza para aquele instante (`end = fim`, `start = fim -
 * janela`) e o polling para — a vista congelada não deve mudar sozinha embaixo do operador.
 */
export function useHistoryMpc(
  flowId: number,
  blockId: string,
  varIds: readonly string[],
  janelaSegundos: number,
  fimEpochS: number | null = null,
): UseQueryResult<MpcHistoryResponse> {
  return useQuery({
    queryKey: chaveHistoricoOperacao(flowId, blockId, varIds, janelaSegundos, fimEpochS),
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
      return api<MpcHistoryResponse>(`/api/history/mpc?${busca.toString()}`);
    },
    enabled: varIds.length > 0,
    refetchInterval: fimEpochS === null ? INTERVALO_POLLING_OPERACAO_MS : false,
  });
}
