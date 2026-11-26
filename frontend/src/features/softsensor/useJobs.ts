import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { temJobAtivo } from "./coleta";
import type { MlJobOut } from "./types";

export const CHAVE_JOBS = ["softsensor", "jobs"] as const;

/**
 * Fila `ml_jobs` do projeto ativo, mais novos primeiro. `ativo` pede só `queued`/`running`
 * (`?active=true`); `false` traz também o histórico — é de onde a tela tira o erro de um
 * job que falhou. Atualiza a cada 2 s enquanto houver job ativo na resposta (molde de
 * `useServerCertificateInfo`).
 */
export function useJobs(ativo: boolean): UseQueryResult<MlJobOut[]> {
  return useQuery({
    queryKey: [...CHAVE_JOBS, ativo],
    queryFn: () => api<MlJobOut[]>(`/api/softsensor/jobs${ativo ? "?active=true" : ""}`),
    refetchInterval: (query) => (temJobAtivo(query.state.data) ? 2000 : false),
  });
}

/** Admin. 202 sem corpo: `queued` vira `cancelled` na hora; `running` só recebe o pedido e o
 *  ml-worker o honra, então o estado final chega pelo polling. */
export function useCancelJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/api/softsensor/jobs/${String(id)}/cancel`, { method: "POST" }),
    // Prefixo inteiro: cancelar também move o conjunto (`building` -> `failed`), e é ação rara.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["softsensor"] }),
  });
}
