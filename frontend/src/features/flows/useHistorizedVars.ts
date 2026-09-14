import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  api,
  type HistorizedVarCreate,
  type HistorizedVarOut,
} from "../../lib/api";

const CHAVE = ["historized-vars"] as const;

/** Variável historiada é linha de `tags` (ADR-041 D1, mesmo compartilhamento de id da tag
 *  calculada, ADR-033 D1): criar/remover aqui também muda o que `GET /api/tags` devolve, então
 *  toda mutation invalida as duas listas. */
const CHAVE_TAGS = ["tags"] as const;

/** `GET /api/historized-vars` exige `flow_id` (a lista do TREND vem de `GET /api/tags`; esta
 *  é só o cadastro por flow, consumido pela seção "Historiar portas" do modal de config). */
export function useHistorizedVars(
  flowId: number,
): UseQueryResult<HistorizedVarOut[]> {
  return useQuery({
    queryKey: [...CHAVE, flowId],
    queryFn: () =>
      api<HistorizedVarOut[]>(`/api/historized-vars?flow_id=${String(flowId)}`),
  });
}

const VAZIO: readonly HistorizedVarOut[] = [];

/** Resultado do agregado: sem `pronto`/`erro`, a tela Tags não distingue "nenhuma
 *  historiada" de "ainda não sei" nem de "falhou" — nos dois últimos casos a historiada
 *  voltaria a aparecer como Calculada, com botão Editar que dá 404. */
export interface IdsHistoriados {
  ids: ReadonlySet<number>;
  pronto: boolean;
  erro: boolean;
}

/** `tag_id` de toda variável historiada do conjunto de flows dado, agregado por `useQueries`
 *  (um `GET` por flow — a API não aceita `project_id`, mesma limitação de `GET /api/tags`).
 *  Serve à tela Tags (ADR-041 D1): essas linhas de `tags` saem da tabela porque se gerenciam
 *  no editor de flow, não em Tags. Mesma chave de `useHistorizedVars` por flow, então as duas
 *  reaproveitam o mesmo cache. */
export function useHistorizedVarIdsDoProjeto(
  flowIds: readonly number[],
): IdsHistoriados {
  return useQueries({
    queries: flowIds.map((id) => ({
      queryKey: [...CHAVE, id],
      queryFn: () =>
        api<HistorizedVarOut[]>(`/api/historized-vars?flow_id=${String(id)}`),
    })),
    combine: combinarIds,
  });
}

/** Fora do componente: identidade estável entre renders, como o TanStack Query pede. */
function combinarIds(
  resultados: readonly UseQueryResult<HistorizedVarOut[]>[],
): IdsHistoriados {
  const ids = new Set<number>();
  for (const resultado of resultados) {
    for (const registro of resultado.data ?? VAZIO) ids.add(registro.tag_id);
  }
  // Conjunto INCOMPLETO (carregando ou falhando) mantém a tabela de Tags fora do ar em vez
  // de mostrar linha com ação quebrada; `erro` dá à tela o que exibir no lugar de um
  // "Carregando…" eterno. Lista vazia de flows é caso legítimo (projeto sem flow), então
  // `pronto` verdadeiro — `every` sobre vazio é `true` e aqui isso é o que se quer.
  return {
    ids,
    pronto: resultados.every((resultado) => resultado.isSuccess),
    erro: resultados.some((resultado) => resultado.isError),
  };
}

/** Nome da tag congela no cadastro (ADR-041 D6): o backend decide, não o formulário. */
export function useCriarHistorizedVar() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: HistorizedVarCreate) =>
      api<HistorizedVarOut>("/api/historized-vars", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    // Devolve a Promise: sem isso `mutateAsync` resolve antes do refetch e o checkbox
    // reabilita mostrando o estado velho por um round-trip — janela para clique duplo.
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: CHAVE }),
        queryClient.invalidateQueries({ queryKey: CHAVE_TAGS }),
      ]),
  });
}

/** Remoção sempre pela linha de `tags` (ADR-041 D5): cascateia `historized_vars`, nunca o
 *  inverso — senão sobra tag órfã, eterna no seletor do TREND. */
export function useRemoverHistorizedVar() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (tagId: number) =>
      api<void>(`/api/historized-vars/${String(tagId)}`, { method: "DELETE" }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: CHAVE }),
        queryClient.invalidateQueries({ queryKey: CHAVE_TAGS }),
      ]),
  });
}
