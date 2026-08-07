import type { FlowOut } from "../../lib/api";
import type { FlowStatus as FlowStatusGerado, PortValue } from "../../lib/contracts.gen";
import { useAssinatura, useCanalAoVivo, type EstadoDoCanal } from "../../app/CanalAoVivo";

/**
 * Canvas ao vivo (RF-305, spec F3 §5.3/§6.2, F5 §7.1-2/4): um editor por flow aberto,
 * registrando interesse em `flow_status` no canal único da sessão (`CanalAoVivo.tsx`) —
 * socket, reconexão e backoff moram no provider; este hook só recorta o estado agregado
 * para o flow da URL, com a mesma assinatura pública de antes do provider.
 *
 * `/ws` não aparece no OpenAPI (WebSocket não existe em OpenAPI 3.0); `FlowStatus`/`PortValue`
 * vêm de `contracts.gen.ts` (fonte: `ottima_core.bus`, débito 2+4 do plano F4a). `EstadoFlow`
 * deriva do enum gerado para `desired_state`: `running` e `stopped` são os mesmos literais do
 * banco, e `failed` é o único estado que só existe no barramento (spec §4.2).
 */

export type EstadoFlow = FlowOut["desired_state"] | "failed";

export type { PortValue };

/** `{block_id: {porta: PortValue}}` — a tabela inteira de portas de uma varredura. */
export type PortsPorBloco = Readonly<Record<string, Readonly<Record<string, PortValue>>>>;

/** `ports` sai como visão somente-leitura (`PortsPorBloco`); o campo gerado é mutável — o
 *  contrato do wire é o mesmo, isto é só disciplina de imutabilidade do frontend. */
export interface FlowStatus extends Omit<FlowStatusGerado, "ports"> {
  ports: PortsPorBloco;
}

/**
 * `sessao_invalida` é desfecho, não espera: o servidor fecha com 1008 quando o token não
 * vale mais (§5.3) e reconectar em laço nisso seria bomba de requisição contra a API.
 */
export type EstadoConexao = "conectando" | "aberta" | "reconectando" | "sessao_invalida";

export interface CanvasAoVivo {
  conexao: EstadoConexao;
  /** Último status recebido; `null` até a primeira varredura — não há replay (§5.3). */
  status: FlowStatus | null;
  /** Últimos valores conhecidos, preservados nas publicações de transição (§4.2). */
  ports: PortsPorBloco;
}

export const ROTULO_ESTADO: Record<EstadoFlow, string> = {
  running: "Rodando",
  stopped: "Parado",
  failed: "Falha",
};

/** Fechamento por sessão inválida (§5.3); qualquer outro código é queda de rede. */
export const CODIGO_SESSAO_INVALIDA = 1008;

const ATRASO_BASE_MS = 1000;
const ATRASO_TETO_MS = 15000;

const SEM_PORTS: PortsPorBloco = {};

// --------------------------------------------------------------------------------------
// Protocolo (§5.3) — puro, reusado pelo provider da sessão (`CanalAoVivo.tsx`, §7.1)
// --------------------------------------------------------------------------------------

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

// --------------------------------------------------------------------------------------
// Formatação de valor (Regra do Número Tabular / Regra do Canal Redundante)
// --------------------------------------------------------------------------------------

/** Decimal em pt-BR sem depender de dados de locale (mesmo critério de `formatarTs`). */
export function formatarNumero(valor: number): string {
  return String(Number(valor.toFixed(3))).replace(".", ",");
}

/** Texto do valor de uma porta. A invalidez (`ok === false`) é canal à parte, do chamador. */
export function formatarValorPorta(valor: PortValue): string {
  if (valor.v === null) return "sem valor";
  if (typeof valor.v === "boolean") return valor.v ? "verdadeiro" : "falso";
  return formatarNumero(valor.v);
}

// --------------------------------------------------------------------------------------
// Ambiente do socket (§7.1): quem abre e mantém o socket é o provider (`CanalAoVivo.tsx`);
// o formato mora aqui porque `urlDoWs`/`atrasoReconexao`/`deveReconectar` também moram.
// --------------------------------------------------------------------------------------

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

// --------------------------------------------------------------------------------------
// React: um editor por flow, sobre o canal único da sessão (§7.1)
// --------------------------------------------------------------------------------------

/** Recorte do estado agregado do canal para o flow do editor: `status`/`ports` já vêm
 *  mesclados pelo redutor do provider (§4.2) — preservar valores na transição não é mais
 *  responsabilidade deste hook. "aberto" do canal (multi-canal, `CanalAoVivo.tsx`) vira
 *  "aberta" da conexão (por-flow): mesmo desfecho, só o rótulo que a assinatura pública
 *  deste hook já usava antes do provider existir. */
export function selecionarCanvas(estado: EstadoDoCanal, flowId: number): CanvasAoVivo {
  const status = estado.flowStatus.get(flowId) ?? null;
  const conexao = estado.estado === "aberto" ? "aberta" : estado.estado;
  return { conexao, status, ports: status?.ports ?? SEM_PORTS };
}

/** Um editor por flow aberto (§5.3): registra `flow_status` do flow da URL no canal único
 *  da sessão (§7.1) e desassina no unmount — `useAssinatura` cuida do ciclo de vida. */
export function useFlowStatus(flowId: number): CanvasAoVivo {
  useAssinatura({ flow_status: [flowId] });
  return selecionarCanvas(useCanalAoVivo(), flowId);
}
