import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { precisaAcompanhar } from "./treino";
import type { SoftSensorBlockOut } from "./types";

export const CHAVE_BLOCOS_SENSOR_VIRTUAL = ["softsensor", "blocks"] as const;

/**
 * Blocos de sensor virtual do projeto ativo (SV-1, `GET /api/softsensor/blocks`). A lista
 * vazia é o que esconde o item "Coleta e treino" da navegação (`AppShell`). Enquanto houver troca
 * de modelo em curso (`precisaAcompanhar`) atualiza a cada 2 s: é assim que "aquecendo" vira "em
 * uso" na tela, sem depender do WebSocket.
 */
export function useSoftSensorBlocks(): UseQueryResult<SoftSensorBlockOut[]> {
  return useQuery({
    queryKey: CHAVE_BLOCOS_SENSOR_VIRTUAL,
    queryFn: () => api<SoftSensorBlockOut[]>("/api/softsensor/blocks"),
    refetchInterval: (query) => (precisaAcompanhar(query.state.data) ? 2000 : false),
  });
}
