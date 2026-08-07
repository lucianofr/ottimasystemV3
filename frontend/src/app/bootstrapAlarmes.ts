import { api } from "../lib/api";
import type { EventMessage } from "./CanalAoVivo";

/**
 * Bootstrap de alarmes na montagem do shell (tarefa 2.2 do plano F5b; spec F5 §7.2-3;
 * F5R-03). `resolverAlarmes` (2.1, `alarmes.ts`) deriva a condição ativa a partir de
 * `eventos`, mas o canal `events` só carrega o que chega depois do socket abrir — sem
 * este bootstrap, um par latchado antes do reload (`flow_failed` sem `flow_deployed`
 * seguinte, por exemplo) fica invisível até o próximo evento ao vivo, às vezes por até
 * 1 mês (nenhuma das famílias "par"/"estado"/"contador" tem TTL). Dois grupos, cada um
 * cobrindo metade das 4 famílias:
 *
 * - grupo 1 (família "par"): uma consulta por origem — `origin=flow:<id>` e
 *   `origin=conn:<id>` — teto de 10 flows + 5 conexões (RNF-01 dimensiona ~10 flows;
 *   RF-201 dimensiona 5 conexões), `limit=20` (padrão `useLastFlowState.ts:112-133`: o
 *   suficiente para achar o último evento do par sem que um flow ruidoso empurre o de
 *   outro para fora da janela);
 * - grupo 2 (famílias "estado"/"contador"/"ttl"): duas consultas globais por
 *   severidade — a API não aceita lista (`schemas/events.py`) — na janela das
 *   últimas 2 h.
 *
 * Depois deste bootstrap, só WS: o canal `events` (já assinado desde a abertura do
 * socket, `CanalAoVivo.tsx`) cobre o resto da sessão.
 */

const TETO_FLOWS = 10;
const TETO_CONEXOES = 5;
const LIMITE_PAR = 20;
const LIMITE_JANELA = 500;
const JANELA_MS = 2 * 60 * 60 * 1000;
const CACHE_MS = 60_000;

export interface EscopoBootstrap {
  flowIds: readonly number[];
  connectionIds: readonly number[];
}

/** Só o fetch é injetável — `agora` já entra como parâmetro explícito (mesmo padrão de
 *  `resolverAlarmes`), então não precisa de outro campo aqui só para o relógio. */
export interface AmbienteBootstrap {
  buscar: (path: string) => Promise<EventMessage[]>;
}

const AMBIENTE_PADRAO: AmbienteBootstrap = {
  buscar: (path) => api<EventMessage[]>(path),
};

/** Descarta duplicatas exatas entre os dois grupos (uma origem que aparece tanto no par
 *  quanto na janela de severidade) e devolve `ts` desc — a ordem que `resolverAlarmes`
 *  e o redutor do canal (`CanalAoVivo.tsx`, `reduzir`) assumem em todo lugar. */
function mesclar(grupos: readonly EventMessage[][]): EventMessage[] {
  const vistos = new Set<string>();
  const unicos: EventMessage[] = [];
  for (const evento of grupos.flat()) {
    const chave = `${evento.ts}|${evento.origin}|${evento.message}`;
    if (vistos.has(chave)) continue;
    vistos.add(chave);
    unicos.push(evento);
  }
  return unicos.sort((a, b) => b.ts.localeCompare(a.ts));
}

/** Fetch dos dois grupos, sem cache — `criarCacheBootstrapAlarmes` embrulha isto com o
 *  TTL de 60 s. Exportada à parte para o teste isolar o comportamento de rede do de
 *  cache. */
export async function bootstrapAlarmes(
  escopo: EscopoBootstrap,
  agora: Date,
  ambiente: AmbienteBootstrap = AMBIENTE_PADRAO,
): Promise<EventMessage[]> {
  const flowIds = escopo.flowIds.slice(0, TETO_FLOWS);
  const connectionIds = escopo.connectionIds.slice(0, TETO_CONEXOES);
  const inicioJanela = new Date(agora.getTime() - JANELA_MS).toISOString();
  const janela = new URLSearchParams({ start: inicioJanela, limit: String(LIMITE_JANELA) });

  const grupos = await Promise.all([
    ...flowIds.map((id) =>
      ambiente.buscar(`/api/events?origin=flow:${String(id)}&limit=${String(LIMITE_PAR)}`),
    ),
    ...connectionIds.map((id) =>
      ambiente.buscar(`/api/events?origin=conn:${String(id)}&limit=${String(LIMITE_PAR)}`),
    ),
    ambiente.buscar(`/api/events?severity=warning&${janela.toString()}`),
    ambiente.buscar(`/api/events?severity=alarm&${janela.toString()}`),
  ]);

  return mesclar(grupos);
}

export interface CacheBootstrapAlarmes {
  obter: (
    escopo: EscopoBootstrap,
    agora: Date,
    ambiente?: AmbienteBootstrap,
  ) => Promise<EventMessage[]>;
}

interface EntradaCache {
  chave: string;
  expiraEm: number;
  resultado: Promise<EventMessage[]>;
}

/** Uma instância por `CanalAoVivoProvider` (mesmo padrão de `criarRegistroInteresses`):
 *  cache de 60 s por escopo, para um remount do provider (StrictMode em dev, ou uma
 *  navegação que desmonta e remonta o shell) não refazer as até 17 chamadas do
 *  bootstrap. Guarda a Promise, não o resultado: duas chamadas concorrentes no mesmo
 *  escopo, antes da primeira resolver, também dividem a mesma requisição. */
export function criarCacheBootstrapAlarmes(): CacheBootstrapAlarmes {
  let entrada: EntradaCache | null = null;
  return {
    obter(escopo, agora, ambiente = AMBIENTE_PADRAO) {
      const chave = JSON.stringify([
        [...escopo.flowIds].sort((a, b) => a - b),
        [...escopo.connectionIds].sort((a, b) => a - b),
      ]);
      const agoraMs = agora.getTime();
      if (entrada !== null && entrada.chave === chave && agoraMs < entrada.expiraEm) {
        return entrada.resultado;
      }
      const resultado = bootstrapAlarmes(escopo, agora, ambiente);
      entrada = { chave, expiraEm: agoraMs + CACHE_MS, resultado };
      return resultado;
    },
  };
}
