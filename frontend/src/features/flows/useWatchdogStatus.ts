import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";

/**
 * Watchdog de comunicação por flow (ADR-009 revisado): o opc-worker mantém um bit alternante
 * por flow e reporta `flow_watchdog_alive` no seu `/health`, agregado por `/api/health/workers`
 * (F5R-09). O estado de cada flow mora na conexão onde seu watchdog foi registrado
 * (`watchdog_connection_id`) — escaneamos todas as conexões.
 *
 * Semântica da chave (espelha `ConnectionSnapshot.flow_watchdog_alive`, `state.py`):
 * - `true`  = bit alternando, comunicação viva.
 * - `false` = watchdog registrado mas bit parado (falha de comunicação, ADR-009) ou partida.
 * - ausente = flow sem watchdog configurado (ou worker em queda).
 */

const POLLING_MS = 5000;

interface WorkersHealth {
  opc_worker?: {
    up?: boolean;
    connections?: Record<
      string,
      { flow_watchdog_alive?: Record<string, boolean> }
    >;
  };
}

/** Achata `flow_watchdog_alive` de todas as conexões em `flow_id -> vivo`. */
export function extrairWatchdog(saude: WorkersHealth): ReadonlyMap<number, boolean> {
  const porFlow = new Map<number, boolean>();
  for (const conn of Object.values(saude.opc_worker?.connections ?? {})) {
    for (const [fid, vivo] of Object.entries(conn.flow_watchdog_alive ?? {})) {
      porFlow.set(Number(fid), vivo);
    }
  }
  return porFlow;
}

const VAZIO: ReadonlyMap<number, boolean> = new Map();

/** Polling de 5 s do estado vivo do watchdog por flow. Chave presente = watchdog registrado
 *  (vivo/morto); ausente = sem watchdog ou worker em queda. */
export function useWatchdogStatus(): ReadonlyMap<number, boolean> {
  const query = useQuery({
    queryKey: ["health", "workers", "watchdog"],
    queryFn: () => api<WorkersHealth>("/api/health/workers"),
    refetchInterval: POLLING_MS,
    select: extrairWatchdog,
  });
  return query.data ?? VAZIO;
}
