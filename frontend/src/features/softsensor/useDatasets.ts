import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { CHAVE_JOBS } from "./useJobs";
import type { DatasetCreate, DatasetCreated, DatasetOut, JobAccepted } from "./types";

const CHAVE_CONJUNTOS = ["softsensor", "datasets"] as const;

/**
 * Conjuntos de treino do projeto ativo. Enquanto algum está em montagem (`building`) a lista
 * se atualiza sozinha a cada 2 s: é a única forma de a tela ver `building -> ready/failed`, já
 * que quem muda o estado é o ml-worker.
 */
export function useDatasets(): UseQueryResult<DatasetOut[]> {
  return useQuery({
    queryKey: CHAVE_CONJUNTOS,
    queryFn: () => api<DatasetOut[]>("/api/softsensor/datasets"),
    refetchInterval: (query) =>
      query.state.data?.some((conjunto) => conjunto.status === "building") ? 2000 : false,
  });
}

/** Admin. A resposta traz `warnings` (ex.: início anterior à retenção do histórico). */
export function useCreateDataset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: DatasetCreate) =>
      api<DatasetCreated>("/api/softsensor/datasets", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE_CONJUNTOS }),
  });
}

/** Admin. 202: fecha o período agora e enfileira o job `dataset_build` (ADR-046). */
export function useFinalizeDataset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<JobAccepted>(`/api/softsensor/datasets/${String(id)}/finalize`, { method: "POST" }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: CHAVE_CONJUNTOS }),
        queryClient.invalidateQueries({ queryKey: CHAVE_JOBS }),
      ]),
  });
}

/** Admin. 204; 409 em `building` (cancele o job antes). Só a lista de conjuntos muda: os jobs
 *  já terminados do conjunto apagado ficam no histórico e a tela os ignora. */
export function useDeleteDataset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/api/softsensor/datasets/${String(id)}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE_CONJUNTOS }),
  });
}
