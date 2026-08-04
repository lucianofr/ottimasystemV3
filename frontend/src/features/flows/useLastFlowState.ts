import { useQueries } from "@tanstack/react-query";

import { api, type EventOut, type FlowOut } from "../../lib/api";

/**
 * Uma consulta por flow, escopada por `?origin=flow:<id>` — `GET /api/events` compara `origin`
 * por **igualdade** (`routers/events.py:43-44`), então eventos de bloco
 * (`flow:<id>/block:<bid>`) e de auditoria (`user:<id>`) não entram nem no servidor.
 *
 * A F2 rejeitou este desenho para conexões por um motivo que **não** vale aqui: lá o mesmo
 * `origin=conn:<id>` também carrega eventos de subscription e de escrita rejeitada, então
 * filtrar por origin não discriminava nada. A convenção de `origin` da F3 (spec §4.3) separa
 * flow de bloco, então aqui discrimina. O ganho é eliminar a contenção da janela: com uma
 * consulta única, um flow ruidoso ocuparia as vagas mais recentes e empurraria o
 * `flow_deployed` de OUTRO flow para fora dela antes de qualquer filtro de cliente.
 *
 * Custo: ~10 requisições por ciclo (RNF-01 dimensiona ~10 flows) contra a API local.
 * Paliativo até o WS da F5 (spec F2 §9.1); o estado vivo contínuo do canvas é do editor (§5.3).
 */
const LIMITE_EVENTOS = 20;
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

/** Igualdade exata, nunca prefixo. O servidor já filtra por `origin` exato, mas a derivação é
 *  a fonte da verdade testada: `flow:12/block:x` é evento de bloco (`script_error`,
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

/** Último `flow_deployed`/`flow_stopped`/`flow_failed` de cada flow, por polling de 5 s.
 *  `refetchIntervalInBackground` fica no default (false): aba oculta não faz polling.
 *  Flow cuja janela não traz evento de estado nenhum fica **fora** do mapa: "sem estado
 *  publicado" e "parado" são coisas diferentes (Regra do Estado Publicado). */
export function useLastFlowState(
  flowIds: readonly number[],
): ReadonlyMap<number, UltimoEstadoFlow> {
  return useQueries({
    queries: flowIds.map((id) => ({
      queryKey: ["events", "estado-flow", id],
      queryFn: () =>
        api<EventOut[]>(
          `/api/events?origin=flow:${String(id)}&limit=${String(LIMITE_EVENTOS)}`,
        ),
      refetchInterval: POLLING_MS,
      select: derivarUltimoEstado,
    })),
    combine: (resultados) => {
      const porFlow = new Map<number, UltimoEstadoFlow>();
      for (const resultado of resultados) {
        for (const [id, estado] of resultado.data ?? VAZIO) porFlow.set(id, estado);
      }
      return porFlow;
    },
  });
}
