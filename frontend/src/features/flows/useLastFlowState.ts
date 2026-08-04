import { useQuery } from "@tanstack/react-query";

import { api, type EventOut, type FlowOut } from "../../lib/api";

/** Uma única chamada por ciclo cobre todos os flows do projeto (~10 — RNF-01). Filtrar por
 *  `origin=flow:<id>` no servidor não serviria: o mesmo `origin` também carrega `flow_overrun`
 *  e `reload_rejected`, então o evento mais recente daquele `origin` frequentemente NÃO é de
 *  estado. Filtrar por `kind` no cliente é o que garante o estado correto. Paliativo até o WS
 *  da F5 (spec F2 §9.1); o estado vivo contínuo do canvas é do editor, via `/ws` (§5.3). */
const LIMITE_EVENTOS = 200;
const POLLING_MS = 5000;

const KIND_RODANDO = "flow_deployed";
const KIND_PARADO = "flow_stopped";
const KIND_FALHA = "flow_failed";

/** `reason` de `flow_stopped` e `flow_failed` (spec F3 §4.3) em pt-BR. */
const MOTIVOS: Record<string, string> = {
  user: "comandado pelo usuário",
  project_activated: "projeto ativado",
  comm_failure: "falha de comunicação",
};

export type EstadoPublicado = "rodando" | "parado" | "falha";

export interface UltimoEstadoFlow {
  estado: EstadoPublicado;
  /** Rótulo textual — Regra do Canal Redundante: cor nunca é o único canal. */
  rotulo: string;
  falha: boolean;
  ts: string;
}

const VAZIO: ReadonlyMap<number, UltimoEstadoFlow> = new Map();

function texto(payload: EventOut["payload"], chave: string): string | null {
  const valor = payload[chave];
  return typeof valor === "string" ? valor : null;
}

/** Igualdade exata, nunca prefixo: `flow:12/block:x` é evento de bloco (`script_error`,
 *  `write_suppressed`) e `user:3` é auditoria de CRUD — nenhum dos dois é estado de flow. */
function idDaOrigem(origin: string): number | null {
  const casamento = /^flow:(\d+)$/.exec(origin);
  return casamento ? Number(casamento[1]) : null;
}

/** Eventos chegam em `ts` desc: o primeiro casamento por flow é o último estado publicado. */
export function derivarUltimoEstado(eventos: EventOut[]): ReadonlyMap<number, UltimoEstadoFlow> {
  const porFlow = new Map<number, UltimoEstadoFlow>();
  for (const evento of eventos) {
    const kind = texto(evento.payload, "kind");
    if (kind !== KIND_RODANDO && kind !== KIND_PARADO && kind !== KIND_FALHA) continue;
    const id = idDaOrigem(evento.origin);
    if (id === null || porFlow.has(id)) continue;
    if (kind === KIND_RODANDO) {
      porFlow.set(id, { estado: "rodando", rotulo: "Rodando", falha: false, ts: evento.ts });
      continue;
    }
    const motivo = texto(evento.payload, "reason");
    const motivoPtBr = (motivo && MOTIVOS[motivo]) ?? "motivo desconhecido";
    const falha = kind === KIND_FALHA;
    porFlow.set(id, {
      estado: falha ? "falha" : "parado",
      rotulo: `${falha ? "Falha" : "Parado"}: ${motivoPtBr}`,
      falha,
      ts: evento.ts,
    });
  }
  return porFlow;
}

/**
 * Regra do Estado Publicado: o comando fica pendente enquanto o desejado (banco) e o publicado
 * (runtime) divergem. Não há reconciliação no cliente — o watermark de 10 s do runtime cobre
 * só `reload`, e `desired_state` nunca é auto-aplicado (ADR-017), então um comando cuja
 * publicação falhou fica visivelmente pendente até o operador recomandar.
 *
 * Sem evento publicado o estado real é desconhecido: "rodando" desejado é pendente (foi
 * comandado e nada confirmou), "parado" não é (boot parado é o estado natural, ADR-017).
 * `falha` é desfecho publicado, não espera: quem informa é a coluna "Último estado".
 */
export function aguardandoConfirmacao(
  desejado: FlowOut["desired_state"],
  publicado: UltimoEstadoFlow | undefined,
): boolean {
  if (!publicado) return desejado === "running";
  if (publicado.estado === "falha") return false;
  return publicado.estado !== (desejado === "running" ? "rodando" : "parado");
}

/** Último `flow_deployed`/`flow_stopped`/`flow_failed` por flow, por polling de 5 s.
 *  `refetchIntervalInBackground` fica no default (false): aba oculta não faz polling. */
export function useLastFlowState(): ReadonlyMap<number, UltimoEstadoFlow> {
  const { data } = useQuery({
    queryKey: ["events", "estado-flows"],
    queryFn: () => api<EventOut[]>(`/api/events?limit=${String(LIMITE_EVENTOS)}`),
    refetchInterval: POLLING_MS,
    select: derivarUltimoEstado,
  });
  return data ?? VAZIO;
}
