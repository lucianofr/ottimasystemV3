import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api, type FlowCreate, type FlowDetail, type FlowOut, type FlowSaved } from "../../lib/api";
import type { GraphJson } from "./graph";

const CHAVE = ["flows"] as const;

export type TsSegundos = FlowCreate["ts_seconds"];

/** Lista fixa de Ts (ADR-007). Fonte única no frontend: o `select` do formulário e qualquer
 *  rótulo saem daqui. O `satisfies` amarra os valores ao enum gerado do OpenAPI. */
export const TS_OPCOES = [0.5, 1, 2, 5, 10, 30, 60] as const satisfies readonly TsSegundos[];

/** Decimal em pt-BR (RNF-08) sem depender de dados de locale: a lista de Ts é fechada. */
export function formatarTs(segundos: number): string {
  return String(segundos).replace(".", ",");
}

/** Rótulos pt-BR de `desired_state` (`models/flow.py`) — o que o operador comandou. */
export const ROTULO_DESEJADO: Record<FlowOut["desired_state"], string> = {
  running: "Rodando",
  stopped: "Parado",
};

/** Escopo pelo projeto ativo é server-side: diferente de `/api/tags`, `GET /api/flows`
 *  aceita `project_id` (spec F3 §5.1). */
export function useFlows(projectId: number | null): UseQueryResult<FlowOut[]> {
  return useQuery({
    queryKey: [...CHAVE, projectId],
    queryFn: () => api<FlowOut[]>(`/api/flows?project_id=${String(projectId)}`),
    enabled: projectId !== null,
  });
}

/** Detalhe com `graph_json` (spec F3 §5.1) — a lista não o traz. */
export function useFlow(flowId: number): UseQueryResult<FlowDetail> {
  return useQuery({
    queryKey: [...CHAVE, "detalhe", flowId],
    queryFn: () => api<FlowDetail>(`/api/flows/${String(flowId)}`),
  });
}

/** PUT do grafo: 200 com `warnings[]` não-bloqueantes (RF-307), 422 com `detail` em pt-BR. */
export function useSaveFlow(flowId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (graph_json: GraphJson) =>
      api<FlowSaved>(`/api/flows/${String(flowId)}`, {
        method: "PUT",
        body: JSON.stringify({ graph_json }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}

/** PUT de propriedades (nome/Ts/watchdog, tarefa 3.1 + ADR-009 revisado): `graph_json` fica de
 *  fora — o backend mantém o grafo salvo quando o campo vem ausente (spec F3, contrato 0.3) —
 *  o editor não é tocado por este PUT. Os cinco campos de watchdog sempre viajam juntos: é o
 *  único diálogo que os edita, então não há "campo ausente mantém o valor atual" a preservar
 *  aqui. Mesma invalidação de `useSaveFlow`. */
export function useSalvarPropriedades(flowId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      ts_seconds: TsSegundos;
      watchdog_enabled: boolean;
      watchdog_connection_id: number | null;
      watchdog_read_node_id: string | null;
      watchdog_write_node_id: string | null;
      watchdog_period_ms: number;
      watchdog_timeout_s: number;
    }) =>
      api<FlowSaved>(`/api/flows/${String(flowId)}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}

export function useCreateFlow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: FlowCreate) =>
      api<FlowDetail>("/api/flows", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}

export function useDeleteFlow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/flows/${String(id)}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}

/** Deploy e Parar respondem 202: gravam `desired_state` e publicam o comando. A confirmação
 *  é o estado publicado pelo runtime (Regra do Estado Publicado) — a invalidação aqui só
 *  atualiza o *desejado*, nunca o último estado. */
export function useComandarFlow(comando: "deploy" | "stop") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/api/flows/${String(id)}/${comando}`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}
