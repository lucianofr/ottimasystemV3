import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";

/**
 * Estado VIVO da sessão OPC por conexão: o opc-worker reporta `state` da máquina
 * connecting/up/failed (`ConnectionState`, `state.py`) no seu `/health`, agregado por
 * `/api/health/workers` (F5R-09). Complementa `useLastConnectionState` (eventos, janela de
 * 200): a bolinha da tela reflete a sessão agora — nunca fica vermelha obsoleta enquanto um
 * `comm_failure` velho ainda couber na janela, nem cai para "—" quando o `comm_restored`
 * sair dela.
 *
 * MESMA queryKey de `useWorkersHealth` (`["health", "workers"]`): react-query compartilha o
 * cache — um só fetch a cada ciclo, e cada observador aplica o seu `select`. O tipo fica
 * local: o compartilhado (`WorkerHealth`) tem índice `unknown`, e importá-lo exigiria cast
 * de `connections` sem ganho nenhum.
 *
 * Semântica da chave:
 * - `true`  = sessão estabelecida (`state === "up"`).
 * - `false` = worker vivo e conexão em `connecting`/`failed`.
 * - ausente = worker em queda (`up !== true`) ou conexão fora do projeto ativo.
 */

const POLLING_MS = 5000;

interface WorkersHealth {
  opc_worker?: {
    up?: boolean;
    connections?: Record<string, { state?: string }>;
  };
}

/** `conn_id -> sessão up`; vazio quando o worker não responde (estado desconhecido). */
export function derivarConectadas(saude: WorkersHealth | undefined): ReadonlyMap<number, boolean> {
  const porConexao = new Map<number, boolean>();
  const worker = saude?.opc_worker;
  if (worker?.up !== true) return porConexao;
  for (const [id, conn] of Object.entries(worker.connections ?? {})) {
    porConexao.set(Number(id), conn.state === "up");
  }
  return porConexao;
}

const VAZIO: ReadonlyMap<number, boolean> = new Map();

/** Estado vivo da sessão por conexão, derivado do MESMO polling de `useWorkersHealth`. */
export function useConnectionsLive(): ReadonlyMap<number, boolean> {
  const query = useQuery({
    queryKey: ["health", "workers"],
    queryFn: () => api<WorkersHealth>("/api/health/workers"),
    refetchInterval: POLLING_MS,
    select: derivarConectadas,
  });
  return query.data ?? VAZIO;
}
