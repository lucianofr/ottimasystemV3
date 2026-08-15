import { api, ApiError } from "../lib/api";
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
 * - grupo 1 (família "par"): uma consulta por origem — `origin=flow:<id>`,
 *   `origin=conn:<id>` e (EMENDA aprovada à spec §7.2-3, fix round 2 — bloco Script
 *   latcha `script_timeout`/`script_error` até `script_recovered`, mas publica com
 *   `origin=flow:<id>/block:<id>`, `blocks/script.py:62`; igualdade exata no servidor,
 *   `routers/events.py:44`, não casa com `origin=flow:<id>` sozinho — sem isto, um
 *   block:<id>` por bloco Script e `origin=tag:<id>` por tag calculada (ADR-033: o
 *   `calc-worker` latcha `calc_tag_timeout`/`calc_tag_error` até `calc_tag_recovered`
 *   exatamente como o bloco Script, e publica com `origin=tag:<id>` — sem esta consulta,
 *   uma tag calculada em falha permanente há mais de 2 h some do banner no reload, porque
 *   o latch por transição não reemite nada) — teto de 10 flows + 5 conexões + 20 blocos
 *   Script + 20 tags calculadas
 *   (RNF-01 dimensiona ~10 flows; RF-201 dimensiona 5 conexões; 20 blocos é o corte
 *   desta emenda, documentado junto de `TETO_BLOCOS_SCRIPT`), `limit=20` (padrão
 *   `useLastFlowState.ts:112-133`: o suficiente para achar o último evento do par sem
 *   que uma origem ruidosa empurre a de outra para fora da janela);
 * - grupo 2 (famílias "estado"/"contador"/"ttl"): duas consultas globais por
 *   severidade — a API não aceita lista (`schemas/events.py`) — na janela das
 *   últimas 2 h.
 *
 * Depois deste bootstrap, só WS: o canal `events` (já assinado desde a abertura do
 * socket, `CanalAoVivo.tsx`) cobre o resto da sessão.
 */

/** Exportado: `CanalAoVivo.tsx` reaproveita o mesmo teto para decidir de quantos flows
 *  buscar o `graph_json` (descoberta dos blocos Script da emenda abaixo) — os blocos
 *  Script pesquisados são sempre os dos mesmos flows já em escopo no grupo 1. */
export const TETO_FLOWS = 10;
const TETO_CONEXOES = 5;
/** Corte desta emenda (fix round 2, achado 2 aprovado pelo dono do plano): teto total de
 *  origens de bloco Script consultadas, no espírito dos tetos de flows/conexões acima —
 *  corte determinístico (`Array.prototype.slice`, ordem de chegada do escopo). */
const TETO_BLOCOS_SCRIPT = 20;
/** Mesmo espírito do teto de blocos Script: corte determinístico das origens `tag:<id>`
 *  consultadas no bootstrap (ADR-033). */
const TETO_TAGS_CALCULADAS = 20;
const LIMITE_PAR = 20;
const LIMITE_JANELA = 500;
const JANELA_MS = 2 * 60 * 60 * 1000;
const CACHE_MS = 60_000;

/** Origem de um bloco Script (`flow:<flowId>/block:<blockId>`, `blocks/script.py:62`). */
export interface OrigemBlocoScript {
  flowId: number;
  blockId: string;
}

export interface EscopoBootstrap {
  flowIds: readonly number[];
  connectionIds: readonly number[];
  /** Emenda aprovada à spec F5 §7.2-3 (fix round 2, achado 2): blocos Script do projeto
   *  ativo, para o grupo 1 também cobrir `script_timeout`/`script_error` ⇒
   *  `script_recovered` (família "par", `alarmes.ts`). */
  scriptBlocks: readonly OrigemBlocoScript[];
  /** Tags calculadas do projeto ativo (ADR-033), pelo mesmo motivo dos blocos Script: o
   *  par `calc_tag_timeout`/`calc_tag_error` ⇒ `calc_tag_recovered` publica com
   *  `origin=tag:<id>`, que a consulta por flow/conexão não alcança. */
  calcTagIds: readonly number[];
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

/** Uma origem falhando (rede, 401, 500...) nunca pode apagar as outras: regra
 *  normativa A-4, já documentada em `alarmes.ts` — "condição ativa, nunca silenciosa".
 *  Loga path + status/detail (`ApiError`, `lib/api.ts`) para diagnóstico; a origem que
 *  falhou simplesmente não contribui evento nenhum neste ciclo. */
function logarFalha(caminho: string, motivo: unknown): void {
  const detalhe =
    motivo instanceof ApiError ? `${String(motivo.status)} ${motivo.message}` : String(motivo);
  console.error(`bootstrapAlarmes: falha ao buscar ${caminho} (${detalhe})`);
}

/** Fetch dos dois grupos, sem cache — `criarCacheBootstrapAlarmes` embrulha isto com o
 *  TTL de 60 s. Exportada à parte para o teste isolar o comportamento de rede do de
 *  cache. `Promise.allSettled`, não `Promise.all`: uma origem que falha não pode
 *  derrubar as até 36 outras — a condição ativa que ela carregava ficaria invisível
 *  até o próximo bootstrap ou evento ao vivo (regra A-4). Esta função nunca rejeita. */
export async function bootstrapAlarmes(
  escopo: EscopoBootstrap,
  agora: Date,
  ambiente: AmbienteBootstrap = AMBIENTE_PADRAO,
): Promise<EventMessage[]> {
  const flowIds = escopo.flowIds.slice(0, TETO_FLOWS);
  const connectionIds = escopo.connectionIds.slice(0, TETO_CONEXOES);
  const scriptBlocks = escopo.scriptBlocks.slice(0, TETO_BLOCOS_SCRIPT);
  const calcTagIds = escopo.calcTagIds.slice(0, TETO_TAGS_CALCULADAS);
  const inicioJanela = new Date(agora.getTime() - JANELA_MS).toISOString();
  const janela = new URLSearchParams({ start: inicioJanela, limit: String(LIMITE_JANELA) });

  const caminhos = [
    ...flowIds.map((id) => `/api/events?origin=flow:${String(id)}&limit=${String(LIMITE_PAR)}`),
    ...connectionIds.map((id) => `/api/events?origin=conn:${String(id)}&limit=${String(LIMITE_PAR)}`),
    ...scriptBlocks.map(
      ({ flowId, blockId }) =>
        `/api/events?origin=flow:${String(flowId)}/block:${blockId}&limit=${String(LIMITE_PAR)}`,
    ),
    ...calcTagIds.map((id) => `/api/events?origin=tag:${String(id)}&limit=${String(LIMITE_PAR)}`),
    `/api/events?severity=warning&${janela.toString()}`,
    `/api/events?severity=alarm&${janela.toString()}`,
  ];

  const resultados = await Promise.allSettled(caminhos.map((caminho) => ambiente.buscar(caminho)));
  const grupos: EventMessage[][] = [];
  for (const [indice, resultado] of resultados.entries()) {
    if (resultado.status === "rejected") {
      logarFalha(caminhos[indice], resultado.reason);
      continue;
    }
    grupos.push(resultado.value);
  }

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
 *  navegação que desmonta e remonta o shell) não refazer as até 37 chamadas do
 *  bootstrap. Guarda a Promise, não o resultado: duas chamadas concorrentes no mesmo
 *  escopo, antes da primeira resolver, também dividem a mesma requisição. */
export function criarCacheBootstrapAlarmes(): CacheBootstrapAlarmes {
  let entrada: EntradaCache | null = null;
  return {
    obter(escopo, agora, ambiente = AMBIENTE_PADRAO) {
      const chave = JSON.stringify([
        [...escopo.flowIds].sort((a, b) => a - b),
        [...escopo.connectionIds].sort((a, b) => a - b),
        [...escopo.scriptBlocks]
          .map(({ flowId, blockId }) => `${String(flowId)}:${blockId}`)
          .sort(),
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
