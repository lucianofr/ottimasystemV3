import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import {
  api,
  type ConnectionOut,
  type TagCreate,
  type TagOut,
  type TagUpdate,
} from "../../lib/api";

const CHAVE = ["tags"] as const;

export type Direcao = TagOut["direction"];
export type TipoDado = TagOut["data_type"];

/** Rótulos pt-BR de `ck_tags_direction` (`models/tag.py`). */
export const ROTULO_DIRECAO: Record<Direcao, string> = {
  r: "Leitura",
  w: "Escrita",
};

/** Rótulos pt-BR de `ck_tags_data_type` (`models/tag.py`). */
export const ROTULO_TIPO: Record<TipoDado, string> = {
  float: "Real",
  int: "Inteiro",
  bool: "Booleano",
};

export interface FiltrosTags {
  /** `null` = todas as conexões. */
  connectionId: number | null;
  /** `null` = ambas as direções. */
  direction: Direcao | null;
}

/** Filtro é server-side: os dois viram query params de `GET /api/tags` (spec F2 §9.1). */
function querystring(filtros: FiltrosTags): string {
  const params = new URLSearchParams();
  if (filtros.connectionId !== null) params.set("connection_id", String(filtros.connectionId));
  if (filtros.direction !== null) params.set("direction", filtros.direction);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function useTags(filtros: FiltrosTags): UseQueryResult<TagOut[]> {
  return useQuery({
    queryKey: [...CHAVE, filtros.connectionId, filtros.direction],
    queryFn: () => api<TagOut[]>(`/api/tags${querystring(filtros)}`),
  });
}

/** Tags não são escopadas por projeto na API; a lista completa de conexões resolve o nome de
 *  qualquer `connection_id` que apareça na tabela. */
export function useAllConnections(): UseQueryResult<ConnectionOut[]> {
  return useQuery({
    queryKey: ["connections", null],
    queryFn: () => api<ConnectionOut[]>("/api/connections"),
  });
}

export function useCreateTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TagCreate) =>
      api<TagOut>("/api/tags", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}

export function useUpdateTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: TagUpdate }) =>
      api<TagOut>(`/api/tags/${String(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}

export function useDeleteTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/tags/${String(id)}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}
