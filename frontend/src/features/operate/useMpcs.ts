import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { components } from "../../lib/api-types";

/** Projeção de um bloco `mpc` (spec F5 §4.1-1, `GET /api/operate/mpcs`) — sem `pid`/pesos/TSS
 *  (§4.1-3); estado rodando/parado do flow não entra (§4.1-4). */
export type MpcNodeOut = components["schemas"]["MpcNodeOut"];

const CHAVE = ["operate", "mpcs"] as const;

/**
 * Descoberta dos blocos MPC do projeto ativo (decisão A-7; RF-701). Hook compartilhado: a
 * Home (tarefa 3.2) usa para o atalho por flow, o seletor/roteamento da operação (tarefa 4.1)
 * usa para listar/redirecionar — mesma `queryKey` nas duas telas, então abrir uma não duplica
 * a requisição em runtime enquanto o cache do react-query estiver vivo.
 *
 * Sem `staleTime`/`refetchOnWindowFocus` explícitos: o default do react-query (`staleTime: 0`)
 * já revalida ao montar e ao focar a aba (spec §7.4-2), mesmo padrão do resto do app
 * (`useFlows.ts`, `useConnections.ts` — nenhum hook daqui fixa `staleTime`).
 */
export function useMpcs(): UseQueryResult<MpcNodeOut[]> {
  return useQuery({
    queryKey: CHAVE,
    queryFn: () => api<MpcNodeOut[]>("/api/operate/mpcs"),
  });
}
