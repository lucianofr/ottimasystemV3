import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { SoftSensorBlockOut } from "./types";

export const CHAVE_BLOCOS_SENSOR_VIRTUAL = ["softsensor", "blocks"] as const;

/**
 * Blocos de sensor virtual do projeto ativo (SV-1, `GET /api/softsensor/blocks`). A lista
 * vazia é o que esconde o item "Coleta e treino" da navegação (`AppShell`).
 */
export function useSoftSensorBlocks(): UseQueryResult<SoftSensorBlockOut[]> {
  return useQuery({
    queryKey: CHAVE_BLOCOS_SENSOR_VIRTUAL,
    queryFn: () => api<SoftSensorBlockOut[]>("/api/softsensor/blocks"),
  });
}
