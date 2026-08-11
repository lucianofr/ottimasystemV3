import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api, type HistoryRetentionOut } from "../../lib/api";

export const MIN_RETENTION_DAYS = 1;
export const MAX_RETENTION_DAYS = 120;

/** Mesmo limite do backend (`MIN/MAX_RETENTION_DAYS`, `schemas/history_retention.py`):
 *  inteiro entre 1 e 120 dias. Extraída para ser testável sem montar o componente. */
export function retencaoEhValida(dias: number): boolean {
  return Number.isInteger(dias) && dias >= MIN_RETENTION_DAYS && dias <= MAX_RETENTION_DAYS;
}

const CHAVE_RETENCAO = ["history-retention"] as const;

/**
 * Janela de retenção do histórico de variáveis (samples/mpc_samples e seus continuous
 * aggregates de 1 min; `events` fica fora — ADR-020, log de alarmes). `GET` é
 * `require_operator` (`history_retention.py`): visível a todos, sempre habilitada — só o
 * `PUT` é `require_admin` (`useCanMutate()` no chamador decide o modo de edição).
 */
export function useHistoryRetention(): UseQueryResult<HistoryRetentionOut> {
  return useQuery({
    queryKey: CHAVE_RETENCAO,
    queryFn: () => api<HistoryRetentionOut>("/api/history-retention"),
  });
}

/**
 * Reprograma as 4 estruturas de variável no Timescale e libera espaço já via `drop_chunks`
 * (não espera o próximo ciclo agendado do job) — spec do pedido: "liberando espaço no banco".
 */
export function useUpdateHistoryRetention() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (retentionDays: number) =>
      api<HistoryRetentionOut>("/api/history-retention", {
        method: "PUT",
        body: JSON.stringify({ retention_days: retentionDays }),
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: CHAVE_RETENCAO }),
  });
}
