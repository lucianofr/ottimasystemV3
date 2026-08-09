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

/** Os `kind`s tratados por esta função nunca deveriam publicar severity "info" (tabelas
 *  de kinds F2/F3/F4 §5.3 e F5 §7.2-1, `bus.py`) — mas a condição não pode ficar
 *  silenciosa por um contrato de severity violado a montante nem mascarar o dado com um
 *  `as`: normaliza para "warning" quando não é "alarm" (nunca oculta um alarme real; na
 *  pior hipótese subestima a severidade, nunca a esconde). Fix round 1, achado 1. */
function condicaoDe(familia: CondicaoAtiva["familia"], kind: string, evento: EventMessage): CondicaoAtiva {
  return {
    familia,
    kind,
    origin: evento.origin,
    desde: evento.ts,
    severity: evento.severity === "alarm" ? "alarm" : "warning",
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

export function chaveMpc(origin: string): string | null {
  const m = /^flow:(\d+)\/block:(.+)$/.exec(origin);
  return m === null ? null : `${m[1]}/${m[2]}`;
}

/** Só considera cessado se o estado publicado for ESTRITAMENTE POSTERIOR ao evento que abriu
 *  a condição — mesma defesa de `flowOverrunCessou` abaixo, generalizada. Sem isto, um estado
 *  "recuperado" antigo (o mapa nunca apaga entradas — `CanalAoVivo.tsx`, `reduzir`) silenciaria
 *  a REOCORRÊNCIA do mesmo alarme: um evento novo chega pelo canal `events` (sempre assinado),
 *  mas a leitura do estado publicado, sem checar frescor, concluiria "cessou" com base numa
 *  recuperação anterior à nova ocorrência — viola a regra normativa A-4 ("nunca silenciosa").
 *  Fix round 1, achado crítico (revisão da tarefa 2.3). */
function estadoMaisNovoQueEvento(estadoTs: string, evento: EventMessage): boolean {
  return new Date(estadoTs).getTime() > new Date(evento.ts).getTime();
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
      const cessou = estado !== undefined && def.cessou(estado) && estadoMaisNovoQueEvento(estado.ts, evento);
      if (!cessou) {
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
  return estadoMaisNovoQueEvento(estado.ts, evento);
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

  // `mpc_overrun` carrega `overruns` no payload desde a tarefa F6a 5.1 (`blocks/mpc.py::_report_overrun`,
  // payload `{"overruns": self._overruns}`, linha 462) — mas a comparação de contador de `flow_overrun`
  // continua não se aplicando aqui: dois eventos `mpc_overrun` consecutivos NUNCA carregam o mesmo
  // valor. O dedupe de `_overrun_reported` só reabre com `status != "overrun"` (`_apply_result`,
  // `blocks/mpc.py:345-346`) ou com `reset()` (`blocks/mpc.py:236`), e `_overruns` sempre incrementa
  // ANTES de publicar (`blocks/mpc.py:376-378`) — o próximo evento reportado já chega com um valor
  // maior, nunca igual. `status.solver` segue o espelho equivalente usado para a cessação: só sai de
  // `"overrun"` no MESMO `_apply_result` que rearma o dedupe, o mesmo instante em que uma comparação
  // de contador entre eventos tentaria capturar — sem precisar dela. A checagem de frescor
  // (`estadoMaisNovoQueEvento`, fix round 1) cobre a mesma reocorrência da família "estado" acima: sem
  // ela, um `solver` já rearmado ANTES de uma nova ocorrência do mesmo `mpc_overrun` silenciaria a
  // reincidência.
  //
  // Borda conhecida (fix round 1, achado 2 da tarefa 2.1): `_build_state` (`blocks/mpc.py`)
  // sobrepõe `solver` para "idle"/"building" fora de AUTO, INDEPENDENTE do `_overrun_reported`
  // interno — então `solver !== "overrun"` pode virar verdadeiro por um motivo diferente do
  // rearme (ex.: operador troca para MAN com o overrun ainda não rearmado por dentro).
  // Autocorretivo: voltar a AUTO com o problema persistente publica `solver = "overrun"` de
  // novo e a condição reativa. Desde a tarefa 2.3, essa borda tem um efeito NOVO e real: cada
  // toggle AUTO/MAN nessa condição gera um subscribe/unsubscribe de verdade no socket
  // (`CanalAoVivo.tsx`, `criarSincronizadorCondicoes`) — consome um slot da fila de 8 do
  // servidor (drop-oldest, `ws.py:45-48,68-74`). É disparado por ação do operador, não por
  // oscilação automática, mas vale saber: um operador alternando modo repetidamente com um
  // overrun pendente reassina a mesma origem repetidamente.
  for (const [origin, evento] of maisRecentePorOrigem(eventos, { mpc_overrun: true })) {
    const chave = chaveMpc(origin);
    const estado = chave === null ? undefined : mpcStates.get(chave);
    const cessou =
      estado !== undefined && estado.status.solver !== "overrun" && estadoMaisNovoQueEvento(estado.ts, evento);
    if (!cessou) {
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
