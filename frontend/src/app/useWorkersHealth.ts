import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../lib/api";

const POLLING_MS = 5000;

export type WorkerId = "opc_worker" | "flow_runtime" | "recorder" | "calc_worker";

/** Corpo por worker (`_fetch_worker_health`, `routers/health.py`): `up` é o único campo
 *  garantido — o resto (`status`/`service`/`version`/...) só existe quando `up: true`, e a
 *  rota devolve `dict` puro (sem `response_model`, spec F5 §4.2), então nunca vira schema
 *  tipado no OpenAPI. */
export interface WorkerHealth {
  up: boolean;
  [campo: string]: unknown;
}

export type WorkersHealth = Record<WorkerId, WorkerHealth>;

export interface LampadaWorker {
  id: WorkerId;
  rotulo: string;
  /** Estado textual — Regra do Canal Redundante (DESIGN.md §Colors): cor nunca é o único
   *  canal, a lâmpada sempre traz o rótulo junto (DESIGN §Shapes "Lâmpada de estado"). */
  estado: string;
  ativo: boolean;
}

const ROTULO_WORKER: Record<WorkerId, string> = {
  opc_worker: "OPC Worker",
  flow_runtime: "Flow Runtime",
  recorder: "Recorder",
  calc_worker: "Calc Worker",
};

/** Ordem fixa das lâmpadas (mesma do agregador, `health.py`). */
const ORDEM: readonly WorkerId[] = ["opc_worker", "flow_runtime", "recorder", "calc_worker"];

/** Deriva as lâmpadas do agregador (`GET /api/health/workers`, spec F5 §4.2, decisão A-8).
 *  Sem resposta ainda (pending ou erro de rede) todas ficam indisponíveis — a lâmpada nunca
 *  some da tela por falta de dado, só muda de estado. */
export function derivarLampadas(saude: WorkersHealth | undefined): LampadaWorker[] {
  return ORDEM.map((id) => {
    const ativo = saude?.[id]?.up === true;
    return { id, rotulo: ROTULO_WORKER[id], estado: ativo ? "Ativo" : "Indisponível", ativo };
  });
}

/** Heartbeat dos workers (RNF-07, plano F5b tarefa 3.2) por polling de 5 s — sem WS aqui.
 *  `refetchIntervalInBackground` fica no default (false), mesma escolha de `useLastFlowState`. */
export function useWorkersHealth(): UseQueryResult<WorkersHealth> {
  return useQuery({
    queryKey: ["health", "workers"],
    queryFn: () => api<WorkersHealth>("/api/health/workers"),
    refetchInterval: POLLING_MS,
  });
}
