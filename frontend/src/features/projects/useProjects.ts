import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { api, type ProjectOut } from "../../lib/api";
import type { components } from "../../lib/api-types";

export type ProjectCreate = components["schemas"]["ProjectCreate"];
export type ProjectUpdate = components["schemas"]["ProjectUpdate"];
export type ProjectImportOut = components["schemas"]["ProjectImportOut"];

export const CHAVE_PROJETOS = ["projects"] as const;

/** Ação de mutação de projeto — linha da tabela de invalidação (spec §6.1-8, F6R-11). */
export type AcaoProjeto = "criar" | "renomear" | "excluir" | "ativar" | "importar";

/**
 * Chaves invalidadas por ação, verbatim da spec §6.1-8: Ativar e Importar trocam o recorte
 * de projeto ativo de todas as telas de engenharia — sem isso reintroduzem o bug de tela
 * presa que motiva a fase (F6R-11). Criar/renomear/excluir só mudam a lista de projetos.
 */
export function chavesInvalidadasPor(acao: AcaoProjeto): readonly (readonly unknown[])[] {
  if (acao === "ativar" || acao === "importar") {
    return [CHAVE_PROJETOS, ["connections"], ["tags"], ["flows"], ["operate", "mpcs"]];
  }
  return [CHAVE_PROJETOS];
}

function invalidarPor(queryClient: QueryClient, acao: AcaoProjeto): void {
  for (const queryKey of chavesInvalidadasPor(acao)) {
    void queryClient.invalidateQueries({ queryKey });
  }
}

/** Projeto ativo: um só por instalação (PRD, projeto ativo único). Pura para teste sem hook. */
export function selecionarProjetoAtivo(projetos: ProjectOut[]): ProjectOut | null {
  return projetos.find((p) => p.is_active) ?? null;
}

export function useProjects(): UseQueryResult<ProjectOut[]> {
  return useQuery({
    queryKey: CHAVE_PROJETOS,
    queryFn: () => api<ProjectOut[]>("/api/projects"),
  });
}

/** Movido de `features/connections/useConnections.ts:14-20` (spec §6.1-8, F6R-11). */
export function useActiveProject(): UseQueryResult<ProjectOut | null> {
  return useQuery({
    queryKey: CHAVE_PROJETOS,
    queryFn: () => api<ProjectOut[]>("/api/projects"),
    select: selecionarProjetoAtivo,
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectCreate) =>
      api<ProjectOut>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => invalidarPor(queryClient, "criar"),
  });
}

export function useUpdateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: ProjectUpdate }) =>
      api<ProjectOut>(`/api/projects/${String(id)}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => invalidarPor(queryClient, "renomear"),
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/projects/${String(id)}`, { method: "DELETE" }),
    onSuccess: () => invalidarPor(queryClient, "excluir"),
  });
}

/** Encerra a execução de todos os flows do projeto atual (spec §6.1-4) — efeito físico. */
export function useActivateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<ProjectOut>(`/api/projects/${String(id)}/activate`, { method: "POST" }),
    onSuccess: () => invalidarPor(queryClient, "ativar"),
  });
}

/** Corpo estrutural de `POST /api/projects/import` (contrato §3.2); nasce sempre inativo. */
export function useImportProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name?: string | null; bundle: Record<string, unknown> }) =>
      api<ProjectImportOut>("/api/projects/import", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => invalidarPor(queryClient, "importar"),
  });
}
