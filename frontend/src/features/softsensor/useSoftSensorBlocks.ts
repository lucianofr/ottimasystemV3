import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { SoftSensorBlockOut } from "./types";

/**
 * Blocos de sensor virtual do projeto ativo (SV-1, `GET /api/softsensor/blocks`). A lista
 * vazia é o que esconde o item "Coleta e treino" da navegação (`AppShell`).
 */
export function useSoftSensorBlocks(): UseQueryResult<SoftSensorBlockOut[]> {
  return useQuery({
    queryKey: ["softsensor", "blocks"],
    queryFn: () => api<SoftSensorBlockOut[]>("/api/softsensor/blocks"),
  });
}
