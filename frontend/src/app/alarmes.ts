import type { FlowStatus } from "../features/flows/useFlowStatus";
import type { MpcState } from "../lib/contracts.gen";
import type { EventMessage } from "./CanalAoVivo";

/**
 * `resolverAlarmes` — tarefa 2.1 do plano F5b (spec F5 §7.2-1; decisão A-4; RF-705;
 * ADR-020). Função PURA e stateless: sem timers, sem estado de módulo, sem I/O — `agora` é
 * o único relógio, e não há parâmetro de períodos (nenhuma família depende de Ts, F5R-02).
 *
 * A condição "ativa" é derivada no cliente por 4 famílias que espelham o rearme dos
 * produtores (eles latcham: emitem 1 vez e só rearmam na recuperação — cessação por
 * silêncio seria falso *all clear*). Origem sem estado publicado nenhum ⇒ condição ativa,
 * nunca silenciosa (regra normativa A-4).
 */

export type CondicaoAtiva = {
  familia: "par" | "estado" | "contador" | "ttl";
  kind: string;
  origin: string;
  desde: string;
  severity: "warning" | "alarm";
  message: string;
};

const TTL_ARM_FAILED_MS = 60_000;

/** `kind` mora em `payload.kind` (bus.py `publish_event`), não é campo de topo do evento —
 *  mesmo padrão de `texto()` em `useLastFlowState.ts`/`useLastConnectionState.ts`. */
function kindDoEvento(evento: EventMessage): string | null {
  const valor = evento.payload.kind;
  return typeof valor === "string" ? valor : null;
}

/** Os `kind`s tratados por esta função nunca publicam severity "info" (tabelas de kinds
 *  F2/F3/F4 §5.3 e F5 §7.2-1, `bus.py`): a condição herda a severidade tal como veio do
 *  barramento — fonte única, sem tradução duplicada no cliente. */
function condicaoDe(familia: CondicaoAtiva["familia"], kind: string, evento: EventMessage): CondicaoAtiva {
  return {
    familia,
    kind,
    origin: evento.origin,
    desde: evento.ts,
    severity: evento.severity as "warning" | "alarm",
    message: evento.message,
  };
}

/** Evento mais recente (a lista chega mais novo primeiro) de um dos `kinds`, por `origin` —
 *  base comum das 4 famílias: cada uma só olha o ÚLTIMO evento relevante de cada origem. */
function maisRecentePorOrigem(
  eventos: readonly EventMessage[],
  kinds: Readonly<Record<string, true>>,
): Map<string, EventMessage> {
  const porOrigem = new Map<string, EventMessage>();
  for (const evento of eventos) {
    const kind = kindDoEvento(evento);
    if (kind === null || kinds[kind] !== true) continue;
    if (!porOrigem.has(evento.origin)) porOrigem.set(evento.origin, evento);
  }
  return porOrigem;
}

// ------------------------------------------------------------------------------------
// Família 1 — par de eventos (§7.2-1): ativa desde o evento de abertura, cessa com o
// evento par da MESMA origin.
// ------------------------------------------------------------------------------------

interface ParDef {
  relevantes: Readonly<Record<string, true>>;
  fechamento: string;
}

const PARES: readonly ParDef[] = [
  { relevantes: { comm_failure: true, comm_restored: true }, fechamento: "comm_restored" },
  { relevantes: { flow_failed: true, flow_deployed: true }, fechamento: "flow_deployed" },
  {
    relevantes: { script_timeout: true, script_error: true, script_recovered: true },
    fechamento: "script_recovered",
  },
];

function condicoesPar(eventos: readonly EventMessage[]): CondicaoAtiva[] {
  const condicoes: CondicaoAtiva[] = [];
  for (const par of PARES) {
    for (const evento of maisRecentePorOrigem(eventos, par.relevantes).values()) {
      const kind = kindDoEvento(evento);
      if (kind !== null && kind !== par.fechamento) {
        condicoes.push(condicaoDe("par", kind, evento));
      }
    }
  }
  return condicoes;
}

// ------------------------------------------------------------------------------------
// Família 2 — estado publicado (§7.2-1): ativa desde o evento, cessa quando o `mpc.state`
// do bloco publica o estado de recuperação. Origem é sempre bloco MPC (`flow:<id>/block:<id>`).
// ------------------------------------------------------------------------------------

function chaveMpc(origin: string): string | null {
  const m = /^flow:(\d+)\/block:(.+)$/.exec(origin);
  return m === null ? null : `${m[1]}/${m[2]}`;
}

interface EstadoDef {
  kind: string;
  cessou: (estado: MpcState) => boolean;
}

const ESTADOS: readonly EstadoDef[] = [
  { kind: "mpc_solver_error", cessou: (e) => e.status.solver !== "error" },
  { kind: "mpc_input_invalid", cessou: (e) => e.status.input_valid },
  { kind: "mpc_shed", cessou: (e) => e.status.armed },
];

function condicoesEstado(
  eventos: readonly EventMessage[],
  mpcStates: ReadonlyMap<string, MpcState>,
): CondicaoAtiva[] {
  const condicoes: CondicaoAtiva[] = [];
  for (const def of ESTADOS) {
    for (const [origin, evento] of maisRecentePorOrigem(eventos, { [def.kind]: true })) {
      const chave = chaveMpc(origin);
      const estado = chave === null ? undefined : mpcStates.get(chave);
      if (estado === undefined || !def.cessou(estado)) {
        condicoes.push(condicaoDe("estado", def.kind, evento));
      }
    }
  }
  return condicoes;
}

// ------------------------------------------------------------------------------------
// Família 3 — contador publicado (§7.2-1): ativa desde o evento, cessa com duas
// publicações consecutivas do mesmo produtor com `overruns` inalterado (espelho do
// rearme — scheduler.py:232, blocks/mpc.py:313).
// ------------------------------------------------------------------------------------

/** `flow_overrun` carrega `overruns` no payload (scheduler.py:248-253 — o valor da MESMA
 *  varredura da publicação concorrente de `flow.status`). "Duas publicações consecutivas
 *  inalteradas" (o rearme de `scheduler.py:232-238`, a 1a varredura no orçamento) é, para
 *  uma leitura única sem histórico, exatamente: uma publicação de `flow.status`
 *  ESTRITAMENTE POSTERIOR ao evento com o MESMO `overruns` — a publicação concorrente do
 *  próprio evento (a "primeira") ainda não conta; só a seguinte ("segunda", sem novo
 *  overrun no meio) fecha a condição. */
function flowOverrunCessou(evento: EventMessage, estado: FlowStatus): boolean {
  const overrunsEvento = evento.payload.overruns;
  if (typeof overrunsEvento !== "number") return false;
  if (estado.overruns !== overrunsEvento) return false;
  return new Date(estado.ts).getTime() > new Date(evento.ts).getTime();
}

function condicoesContador(
  eventos: readonly EventMessage[],
  flowStatus: ReadonlyMap<number, FlowStatus>,
  mpcStates: ReadonlyMap<string, MpcState>,
): CondicaoAtiva[] {
  const condicoes: CondicaoAtiva[] = [];

  for (const [origin, evento] of maisRecentePorOrigem(eventos, { flow_overrun: true })) {
    const idFlow = /^flow:(\d+)$/.exec(origin);
    const estado = idFlow === null ? undefined : flowStatus.get(Number(idFlow[1]));
    if (estado === undefined || !flowOverrunCessou(evento, estado)) {
      condicoes.push(condicaoDe("contador", "flow_overrun", evento));
    }
  }

  // `mpc_overrun` não carrega `overruns` no payload (`blocks/mpc.py::_report_overrun`,
  // payload `{}`) — sem valor de referência, a comparação de contador de `flow_overrun` não
  // se aplica aqui. `status.solver` é o espelho equivalente já publicado: só sai de
  // `"overrun"` no MESMO `_apply_result` que rearma o dedupe (`blocks/mpc.py:313`), o mesmo
  // instante que "overruns inalterado" descreveria — sem precisar do contador.
  for (const [origin, evento] of maisRecentePorOrigem(eventos, { mpc_overrun: true })) {
    const chave = chaveMpc(origin);
    const estado = chave === null ? undefined : mpcStates.get(chave);
    if (estado === undefined || estado.status.solver === "overrun") {
      condicoes.push(condicaoDe("contador", "mpc_overrun", evento));
    }
  }

  return condicoes;
}

// ------------------------------------------------------------------------------------
// Família 4 — TTL (§7.2-1): só `mpc_arm_failed`. Cessa 60 s sem repetição do mesmo
// `kind`+`origin` — cada nova ocorrência renova a janela (só a mais recente importa).
// ------------------------------------------------------------------------------------

function condicoesTtl(eventos: readonly EventMessage[], agora: Date): CondicaoAtiva[] {
  const condicoes: CondicaoAtiva[] = [];
  for (const evento of maisRecentePorOrigem(eventos, { mpc_arm_failed: true }).values()) {
    const decorridoMs = agora.getTime() - new Date(evento.ts).getTime();
    if (decorridoMs < TTL_ARM_FAILED_MS) {
      condicoes.push(condicaoDe("ttl", "mpc_arm_failed", evento));
    }
  }
  return condicoes;
}

// ------------------------------------------------------------------------------------

export function resolverAlarmes(
  eventos: readonly EventMessage[],
  flowStatus: ReadonlyMap<number, FlowStatus>,
  mpcStates: ReadonlyMap<string, MpcState>,
  agora: Date,
): CondicaoAtiva[] {
  return [
    ...condicoesPar(eventos),
    ...condicoesEstado(eventos, mpcStates),
    ...condicoesContador(eventos, flowStatus, mpcStates),
    ...condicoesTtl(eventos, agora),
  ];
}
