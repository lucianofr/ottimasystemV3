import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import {
  api,
  type ConnectionCreate,
  type ConnectionOut,
  type ConnectionUpdate,
  type ProjectOut,
} from "../../lib/api";

const CHAVE = ["connections"] as const;

/** Projeto ativo: um só por instalação (PRD, projeto ativo único). */
export function useActiveProject(): UseQueryResult<ProjectOut | null> {
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => api<ProjectOut[]>("/api/projects"),
    select: (projetos) => projetos.find((p) => p.is_active) ?? null,
  });
}

export function useConnections(projectId: number | null): UseQueryResult<ConnectionOut[]> {
  return useQuery({
    queryKey: [...CHAVE, projectId],
    queryFn: () => api<ConnectionOut[]>(`/api/connections?project_id=${String(projectId)}`),
    enabled: projectId !== null,
  });
}

export function useCreateConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ConnectionCreate) =>
      api<ConnectionOut>("/api/connections", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}

export function useUpdateConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: ConnectionUpdate }) =>
      api<ConnectionOut>(`/api/connections/${String(id)}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}

export function useDeleteConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/api/connections/${String(id)}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}
