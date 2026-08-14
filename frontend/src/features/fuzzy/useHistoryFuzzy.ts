import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { FuzzyHistoryResponse } from "./types";

/** Polling do histórico do trend fuzzy — mesma cadência do trend de operação MPC
 *  (`INTERVALO_POLLING_OPERACAO_MS`, `../operate/trendOperacao.ts`); constante própria para
 *  não acoplar a feature fuzzy ao módulo de operação MPC. */
export const INTERVALO_POLLING_FUZZY_MS = 5000;

/** `queryKey` do histórico fuzzy — exportada pelo mesmo motivo de `chaveHistoricoOperacao`
 *  (`../operate/useHistoryMpc.ts`): trocar de janela muda a chave, o react-query refaz a
 *  busca. `fimEpochS` entra na chave: deslizar a janela é outra busca, não um refresh da
 *  mesma — default `null` preserva a chave de antes da janela deslizante. */
export function chaveHistoricoFuzzy(
  flowId: number,
  blockId: string,
  varIds: readonly string[],
  janelaSegundos: number,
  fimEpochS: number | null = null,
): readonly unknown[] {
  return ["history-fuzzy", flowId, blockId, varIds.join(","), janelaSegundos, fimEpochS];
}

/**
 * Histórico das variáveis IN/OUT de um bloco fuzzy (`GET /api/history/fuzzy`, ADR-030 —
 * espelho exato de `useHistoryMpc`), com polling de 5 s. `fimEpochS` congela a janela
 * (`useJanelaDeslizante`, `../trend`, compartilhada pelas três telas de trend do app) e
 * desliga o polling — a vista congelada não deve mudar sozinha embaixo do operador.
 */
export function useHistoryFuzzy(
  flowId: number,
  blockId: string,
  varIds: readonly string[],
  janelaSegundos: number,
  fimEpochS: number | null = null,
): UseQueryResult<FuzzyHistoryResponse> {
  return useQuery({
    queryKey: chaveHistoricoFuzzy(flowId, blockId, varIds, janelaSegundos, fimEpochS),
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
      return api<FuzzyHistoryResponse>(`/api/history/fuzzy?${busca.toString()}`);
    },
    enabled: varIds.length > 0,
    refetchInterval: fimEpochS === null ? INTERVALO_POLLING_FUZZY_MS : false,
  });
}
