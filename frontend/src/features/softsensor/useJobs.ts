import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { temJobAtivo } from "./coleta";
import type { MetodoSensor } from "./treino";
import type { JobAccepted, MlJobOut, TrainJobIn, TuneJobIn } from "./types";

export const CHAVE_JOBS = ["softsensor", "jobs"] as const;

/**
 * Jobs do conjunto (`?dataset_id=`): a montagem (`dataset_build`) e os treinos e otimizações que o
 * usam, mais novos primeiro. O filtro é do servidor — procurar na fila inteira dos 100 mais novos
 * perderia o job de um conjunto antigo. Atualiza a cada 2 s enquanto houver job ativo na resposta
 * (molde de `useServerCertificateInfo`); é de onde a tela tira o erro de um job que falhou.
 * `tipo` restringe só o polling aos jobs desse `kind` (a página Otimização só acompanha `tune`);
 * a chave e a resposta são as mesmas, então as invalidações de enfileirar/cancelar valem igual.
 */
export function useJobsDoConjunto(
  conjuntoId: number | null,
  tipo?: string,
): UseQueryResult<MlJobOut[]> {
  return useQuery({
    queryKey: [...CHAVE_JOBS, conjuntoId],
    queryFn: () => api<MlJobOut[]>(`/api/softsensor/jobs?dataset_id=${String(conjuntoId)}`),
    enabled: conjuntoId !== null,
    refetchInterval: (query) => {
      const jobs = query.state.data;
      return temJobAtivo(tipo === undefined ? jobs : jobs?.filter((job) => job.kind === tipo))
        ? 2000
        : false;
    },
  });
}

export type TrainJobBody = Omit<TrainJobIn, "method"> & { method: MetodoSensor };
export type TuneJobBody = Omit<TuneJobIn, "method"> & { method: MetodoSensor };

/** Admin. Treino (`kind: "train"`) ou otimização (`kind: "tune"`). 202 `{job_id}`; 422/409 trazem
 *  o motivo em pt-BR no `detail` (nome repetido, conjunto incompatível, hiperparâmetro fora da
 *  faixa, tentativas fora de 10..500). */
export function useEnqueueTrain() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TrainJobBody | TuneJobBody) =>
      api<JobAccepted>("/api/softsensor/jobs", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE_JOBS }),
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
