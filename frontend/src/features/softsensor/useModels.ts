import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { temTrocaPendente } from "./treino";
import type { SoftSensorModelOut } from "./types";
import { CHAVE_BLOCOS_SENSOR_VIRTUAL } from "./useSoftSensorBlocks";

export const CHAVE_MODELOS = ["softsensor", "models"] as const;

/**
 * Modelos do projeto ativo (todos, não só os do conjunto em tela), com métricas e `in_use`.
 * Atualiza a cada 2 s enquanto algum bloco aquece ou aguarda o runtime (`temTrocaPendente`): é
 * assim que "aquecendo" vira "em uso" na tela, sem depender do WebSocket.
 */
export function useModels(): UseQueryResult<SoftSensorModelOut[]> {
  return useQuery({
    queryKey: CHAVE_MODELOS,
    queryFn: () => api<SoftSensorModelOut[]>("/api/softsensor/models"),
    refetchInterval: (query) => (temTrocaPendente(query.state.data) ? 2000 : false),
  });
}

interface Ativacao {
  flowId: number;
  blockId: string;
  modelId: number;
}

/** Admin. 202: só grava o pedido (`desired_model_id`); quem ativa e aquece é o runtime. 422 traz o
 *  motivo inteiro (método, entradas ou Ts incompatíveis). */
export function useActivateModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ flowId, blockId, modelId }: Ativacao) =>
      api<void>(`/api/operate/${String(flowId)}/${blockId}/model`, {
        method: "POST",
        body: JSON.stringify({ model_id: modelId }),
      }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: CHAVE_MODELOS }),
        queryClient.invalidateQueries({ queryKey: CHAVE_BLOCOS_SENSOR_VIRTUAL }),
      ]),
  });
}

/** Admin. 204; 409 quando algum bloco ainda referencia o modelo (ativo, candidato ou pedido). */
export function useDeleteModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/api/softsensor/models/${String(id)}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE_MODELOS }),
  });
}
