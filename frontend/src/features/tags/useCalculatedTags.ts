import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  api,
  type CalculatedTagCreate,
  type CalculatedTagOut,
  type CalculatedTagUpdate,
} from "../../lib/api";

const CHAVE = ["calculated-tags"] as const;
const CHAVE_TAGS = ["tags"] as const;

export type PeriodoSegundos = CalculatedTagOut["period_seconds"];

/** Periodicidades fixas do pedido (ADR-033) — mesma convenção de `TS_OPCOES`
 *  (`features/flows/useFlows.ts`): fonte única para o `<select>` e para o rótulo. */
export const PERIODO_OPCOES = [1, 2, 5, 10, 30, 60] as const satisfies readonly PeriodoSegundos[];

/** A lista de período é fechada e inteira: sem casa decimal para tratar (RNF-08). */
export function formatarPeriodo(segundos: PeriodoSegundos): string {
  return `${String(segundos)} s`;
}

/** `GET /api/calculated-tags` aceita `project_id`, ao contrário de `/api/tags` (spec F9). */
export function useCalculatedTags(projectId: number | null): UseQueryResult<CalculatedTagOut[]> {
  return useQuery({
    queryKey: [...CHAVE, projectId],
    queryFn: () => api<CalculatedTagOut[]>(`/api/calculated-tags?project_id=${String(projectId)}`),
    enabled: projectId !== null,
  });
}

/** Registro completo (script, período, entradas) para o formulário de edição — a linha de
 *  `TagOut` da tabela não traz esses campos. */
export function useCalculatedTag(tagId: number | null): UseQueryResult<CalculatedTagOut> {
  return useQuery({
    queryKey: [...CHAVE, "detail", tagId],
    queryFn: () => api<CalculatedTagOut>(`/api/calculated-tags/${String(tagId)}`),
    enabled: tagId !== null,
  });
}

/** Toda mutação invalida `calculated-tags` E `tags`: uma tag calculada também é uma linha de
 *  `tags` (ADR-033 D1) — a tabela desta tela e o seletor do Trend leem a outra chave. */
function invalidarAmbas(queryClient: QueryClient): void {
  queryClient.invalidateQueries({ queryKey: CHAVE });
  queryClient.invalidateQueries({ queryKey: CHAVE_TAGS });
}

export function useCreateCalculatedTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CalculatedTagCreate) =>
      api<CalculatedTagOut>("/api/calculated-tags", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => invalidarAmbas(queryClient),
  });
}

export function useUpdateCalculatedTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: CalculatedTagUpdate }) =>
      api<CalculatedTagOut>(`/api/calculated-tags/${String(id)}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => invalidarAmbas(queryClient),
  });
}

export function useDeleteCalculatedTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/calculated-tags/${String(id)}`, { method: "DELETE" }),
    onSuccess: () => invalidarAmbas(queryClient),
  });
}
