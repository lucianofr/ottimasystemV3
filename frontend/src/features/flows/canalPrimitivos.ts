import type { FlowOut } from "../../lib/api";
import type { FlowStatus as FlowStatusGerado, PortValue } from "../../lib/contracts.gen";

/**
 * Primitivos do protocolo `/ws` (§5.3/§4.2) compartilhados entre o provider do canal ao
 * vivo (`app/CanalAoVivo.tsx`) e o hook por-flow (`features/flows/useFlowStatus.ts`) —
 * débito 2 de frontend da F5 (spec F6 §6.6-2). Antes desta extração os dois arquivos se
 * importavam um ao outro (ciclo de runtime): `CanalAoVivo.tsx` usava estas sete funções
 * definidas em `useFlowStatus.ts`, que por sua vez importava `useAssinatura`/`useCanalAoVivo`
 * de volta. Este módulo é o terceiro lugar de verdade — tipos e funções puras do protocolo,
 * sem React e sem depender de nenhum dos dois arquivos originais — e os dois passam a
 * importar só dele. `useAssinatura`/`useCanalAoVivo` continuam em `CanalAoVivo.tsx` (leem os
 * contexts do provider, `AssinaturaContext`/`EstadoContext`, que não fazem sentido fora
 * dele); `useFlowStatus.ts` segue importando-os de lá — é dependência de mão única, não
 * ciclo, e mexer nisso alcançaria consumidores fora do escopo desta tarefa (`OperatePage.tsx`,
 * `EventsPage.tsx`, `AnnunciatorBar.tsx`).
 */

export type EstadoFlow = FlowOut["desired_state"] | "failed";

/** `{block_id: {porta: PortValue}}` — a tabela inteira de portas de uma varredura. */
export type PortsPorBloco = Readonly<Record<string, Readonly<Record<string, PortValue>>>>;

/** `ports` sai como visão somente-leitura (`PortsPorBloco`); o campo gerado é mutável — o
 *  contrato do wire é o mesmo, isto é só disciplina de imutabilidade do frontend. */
export interface FlowStatus extends Omit<FlowStatusGerado, "ports"> {
  ports: PortsPorBloco;
}

/**
 * Socket, relógio e sessão como dependências. Em produção são os do browser; no check de
 * desmonte (`canalAoVivo.check.ts`) são dublês, que é como se prova que nada sobrou aberto
 * ou agendado.
 */
export interface AmbienteAoVivo {
  criarSocket: (url: string) => WebSocket;
  token: () => string | null;
  origem: () => Location;
  agendar: (acao: () => void, atrasoMs: number) => number;
  cancelar: (id: number) => void;
}

/** Fechamento por sessão inválida (§5.3); qualquer outro código é queda de rede. */
export const CODIGO_SESSAO_INVALIDA = 1008;

const ATRASO_BASE_MS = 1000;
const ATRASO_TETO_MS = 15000;

const SEM_PORTS: PortsPorBloco = {};

/**
 * Path literal `/ws`, **sem** barra final: o `location /ws` do nginx casa por prefixo e não
 * reescreve o path, então `/ws/` chega ao Starlette como rota inexistente e vira 403 — que
 * é indistinguível de token recusado a olho nu.
 */
export function urlDoWs(origem: Location, token: string): string {
  const protocolo = origem.protocol === "https:" ? "wss:" : "ws:";
  return `${protocolo}//${origem.host}/ws?token=${encodeURIComponent(token)}`;
}

/** Backoff crescente e limitado: só para queda de rede, nunca para 1008. */
export function atrasoReconexao(tentativa: number): number {
  return Math.min(ATRASO_BASE_MS * 2 ** tentativa, ATRASO_TETO_MS);
}

export function deveReconectar(codigo: number): boolean {
  return codigo !== CODIGO_SESSAO_INVALIDA;
}

/**
 * Publicação de transição de estado vem com `ports` vazio (§4.2): o estado mudou e os
 * valores não fazem parte daquela mensagem. Apagar o canvas a cada deploy/parada seria
 * confundir "sem `ports`" com "sem valores".
 */
export function mesclarPorts(anterior: PortsPorBloco, recebido: PortsPorBloco): PortsPorBloco {
  return Object.keys(recebido).length === 0 ? anterior : recebido;
}

/** Exportado para reuso em `CanalAoVivo.tsx` (§7.1): o mesmo formato `{block_id: {porta:
 *  PortValue}}` chega por `flow.status.*`, roteado pelo provider da sessão. */
export function objeto(valor: unknown): Record<string, unknown> | null {
  return typeof valor === "object" && valor !== null && !Array.isArray(valor)
    ? (valor as Record<string, unknown>)
    : null;
}

export function ehEstado(valor: unknown): valor is EstadoFlow {
  return valor === "running" || valor === "stopped" || valor === "failed";
}

export function lerPortValue(bruto: unknown): PortValue | null {
  const item = objeto(bruto);
  if (item === null || typeof item.ok !== "boolean") return null;
  const v = item.v;
  if (v !== null && typeof v !== "number" && typeof v !== "boolean") return null;
  return { v, ok: item.ok };
}

export function lerPorts(bruto: unknown): PortsPorBloco {
  const mapa = objeto(bruto);
  if (mapa === null) return SEM_PORTS;
  const portsPorBloco: Record<string, Record<string, PortValue>> = {};
  for (const [blockId, portas] of Object.entries(mapa)) {
    const doBloco = objeto(portas);
    if (doBloco === null) continue;
    const valores: Record<string, PortValue> = {};
    for (const [porta, valorBruto] of Object.entries(doBloco)) {
      const valor = lerPortValue(valorBruto);
      if (valor !== null) valores[porta] = valor;
    }
    portsPorBloco[blockId] = valores;
  }
  return portsPorBloco;
}
