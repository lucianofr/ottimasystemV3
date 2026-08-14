import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api, type HistoryRetentionOut } from "../../lib/api";

export const MIN_RETENTION_DAYS = 1;
export const MAX_RETENTION_DAYS = 120;
export const MAX_EVENTS_RETENTION_DAYS = 90;

/** Mesmo limite do backend (`MIN/MAX_RETENTION_DAYS`, `schemas/history_retention.py`):
 *  inteiro entre 1 e 120 dias. Extraída para ser testável sem montar o componente. */
export function retencaoEhValida(dias: number): boolean {
  return Number.isInteger(dias) && dias >= MIN_RETENTION_DAYS && dias <= MAX_RETENTION_DAYS;
}

/** Janela de `events` (ADR-020 revisado): inteiro entre 1 e 90 dias. */
export function retencaoEventosEhValida(dias: number): boolean {
  return (
    Number.isInteger(dias) && dias >= MIN_RETENTION_DAYS && dias <= MAX_EVENTS_RETENTION_DAYS
  );
}

const CHAVE_RETENCAO = ["history-retention"] as const;

/**
 * Janelas de retenção: variáveis de processo (samples/mpc_samples e seus continuous
 * aggregates de 1 min) e do log de eventos (`events`). `GET` é `require_operator`
 * (`history_retention.py`); o `PUT` é `require_admin` — a página `/configuracoes` já é
 * admin-only, então aqui não há modo somente-leitura.
 */
export function useHistoryRetention(): UseQueryResult<HistoryRetentionOut> {
  return useQuery({
    queryKey: CHAVE_RETENCAO,
    queryFn: () => api<HistoryRetentionOut>("/api/history-retention"),
  });
}

/**
 * Reprograma as retention policies do Timescale e libera espaço já via `drop_chunks` (não
 * espera o próximo ciclo agendado do job). Campo ausente mantém o valor gravado — as duas
 * seções da página salvam independentemente.
 */
export function useUpdateHistoryRetention() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { retention_days?: number; events_retention_days?: number }) =>
      api<HistoryRetentionOut>("/api/history-retention", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: CHAVE_RETENCAO }),
  });
}
