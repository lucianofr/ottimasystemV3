import type { PortValue } from "../../lib/contracts.gen";
import { useAssinatura, useCanalAoVivo, type EstadoDoCanal } from "../../app/CanalAoVivo";
import { type EstadoFlow, type FlowStatus, type PortsPorBloco } from "./canalPrimitivos";

/**
 * Canvas ao vivo (RF-305, spec F3 §5.3/§6.2, F5 §7.1-2/4): um editor por flow aberto,
 * registrando interesse em `flow_status` no canal único da sessão (`CanalAoVivo.tsx`) —
 * socket, reconexão e backoff moram no provider; este hook só recorta o estado agregado
 * para o flow da URL, com a mesma assinatura pública de antes do provider.
 *
 * `/ws` não aparece no OpenAPI (WebSocket não existe em OpenAPI 3.0); `FlowStatus`/`PortValue`
 * vêm de `contracts.gen.ts` (fonte: `ottima_core.bus`, débito 2+4 do plano F4a) e, junto com
 * `EstadoFlow`/`PortsPorBloco`, são reexportados aqui a partir de `canalPrimitivos.ts` (débito
 * 2 de frontend da F5, spec F6 §6.6-2 — primitivos do protocolo que o provider também usa,
 * sem import circular entre os dois). `EstadoFlow` deriva do enum gerado para
 * `desired_state`: `running` e `stopped` são os mesmos literais do banco, e `failed` é o
 * único estado que só existe no barramento (spec §4.2).
 */

export type { EstadoFlow, FlowStatus, PortsPorBloco };

export type { PortValue };

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

const SEM_PORTS: PortsPorBloco = {};

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
