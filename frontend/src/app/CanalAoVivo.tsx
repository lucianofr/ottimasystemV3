import { useQueries } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { api, ApiError, getToken, type EventOut, type FlowDetail } from "../lib/api";
import type { MpcState } from "../lib/contracts.gen";
import {
  atrasoReconexao,
  deveReconectar,
  ehEstado,
  lerPorts,
  mesclarPorts,
  objeto,
  urlDoWs,
  type AmbienteAoVivo,
  type FlowStatus,
  type PortsPorBloco,
} from "../features/flows/useFlowStatus";
import { useActiveProject, useConnections } from "../features/connections/useConnections";
import { deGraphJson } from "../features/flows/graph";
import { useFlows } from "../features/flows/useFlows";
import {
  criarCacheBootstrapAlarmes,
  TETO_FLOWS,
  type EscopoBootstrap,
  type OrigemBlocoScript,
} from "./bootstrapAlarmes";
import { chaveMpc, resolverAlarmes, type CondicaoAtiva } from "./alarmes";

/**
 * Canal ao vivo da sessão (spec F5 §7.1-1/2/3; decisão A-6; F5R-22): **um** WebSocket por
 * aba, vivo enquanto houver sessão — reconexão, backoff e o fechamento 1008 moram aqui, não
 * em cada página. `flow_status`, `mpc_state` e `events` compartilham o mesmo socket; cada
 * página declara o que quer ver (`useAssinatura`) e o provider agrega os interesses de todas
 * as páginas montadas, mandando só o delta que muda a cada subscribe/unsubscribe (fila do
 * servidor é 8 com drop-oldest — spec F5R-22 — então assinar mais do que o necessário derruba
 * mensagem alheia).
 *
 * `events` é assinado uma vez no connect e nunca desliga: o banner (shell) depende dele estar
 * sempre vivo, então não é ref-contado como `flow_status`/`mpc_state`.
 */

/** O que uma página quer ver no canal. `mpc_state` já na forma de id do wire
 *  (`flowId/blockId`, spec F4 §6.2). Campo ausente = a página não quer nada daquele tipo. */
export type Interesse = { flow_status?: number[]; mpc_state?: string[] };

/** Mesmo formato de `EventOut` (`GET /api/events`): o canal `events` publica o mesmo
 *  `{ts, severity, origin, message, payload}` que a REST devolve (bus §1.1). */
export type EventMessage = EventOut;

type EstadoConexaoCanal = "conectando" | "aberto" | "reconectando" | "sessao_invalida";

export interface EstadoDoCanal {
  estado: EstadoConexaoCanal;
  flowStatus: ReadonlyMap<number, FlowStatus>;
  mpcStates: ReadonlyMap<string, MpcState>;
  eventos: readonly EventMessage[];
}

/** Teto de memória do buffer de eventos ao vivo (RNF-05): a tela também pagina via REST
 *  (`LIMITE_EVENTOS` em `useLastFlowState.ts`); este teto só evita crescimento sem fim numa
 *  sessão longa.
 *  ponytail: valor fixo; subir se uma tela precisar de mais histórico ao vivo do que isso. */
export const TETO_EVENTOS = 200;

const SEM_PORTS: PortsPorBloco = {};

const ESTADO_INICIAL: EstadoDoCanal = {
  estado: "conectando",
  flowStatus: new Map(),
  mpcStates: new Map(),
  eventos: [],
};

// --------------------------------------------------------------------------------------
// Agregação de interesses (§7.1): refcount por id, delta mínimo a cada subscribe/unsubscribe
// --------------------------------------------------------------------------------------

/** Delta de uma operação de registro: só os ids que de fato entraram (0→1) ou saíram (1→0)
 *  do agregado. Duas páginas pedindo o mesmo flow geram delta só na primeira. */
export interface DeltaInteresse {
  flow_status: readonly number[];
  mpc_state: readonly string[];
}

export interface RegistroInteresses {
  adicionar: (interesse: Interesse) => DeltaInteresse;
  remover: (interesse: Interesse) => DeltaInteresse;
  agregado: () => Interesse;
}

function ajustarContagem<T>(mapa: Map<T, number>, ids: readonly T[], passo: 1 | -1): T[] {
  const mudou: T[] = [];
  for (const id of ids) {
    const atual = mapa.get(id) ?? 0;
    const novo = atual + passo;
    if (novo <= 0) {
      mapa.delete(id);
      if (atual > 0) mudou.push(id);
    } else {
      mapa.set(id, novo);
      if (atual === 0) mudou.push(id);
    }
  }
  return mudou;
}

/** Uma instância por `CanalAoVivoProvider`: guarda quantas páginas montadas querem cada
 *  flow/bloco, para nunca desassinar um id que outra página ainda usa. */
export function criarRegistroInteresses(): RegistroInteresses {
  const flowRefs = new Map<number, number>();
  const mpcRefs = new Map<string, number>();

  return {
    adicionar: (interesse) => ({
      flow_status: ajustarContagem(flowRefs, interesse.flow_status ?? [], 1),
      mpc_state: ajustarContagem(mpcRefs, interesse.mpc_state ?? [], 1),
    }),
    remover: (interesse) => ({
      flow_status: ajustarContagem(flowRefs, interesse.flow_status ?? [], -1),
      mpc_state: ajustarContagem(mpcRefs, interesse.mpc_state ?? [], -1),
    }),
    agregado: () => ({ flow_status: [...flowRefs.keys()], mpc_state: [...mpcRefs.keys()] }),
  };
}

// --------------------------------------------------------------------------------------
// Quadro de assinatura: gerador de delta multi-canal (protocolo §5, F5R-15)
// --------------------------------------------------------------------------------------

interface CorpoAssinatura {
  flow_status?: readonly number[];
  mpc_state?: readonly string[];
  events?: true;
}

/** `{subscribe: {...}, unsubscribe: {...}}` — os dois cabem no mesmo quadro quando o delta
 *  troca dos dois lados na mesma operação. Canal sem id nenhum não entra no quadro: a fila
 *  do servidor é 8 com drop-oldest (F5R-22), então nunca vale mandar `flow_status: []`. */
export function comandoAssinatura(
  acoes: { subscribe?: CorpoAssinatura; unsubscribe?: CorpoAssinatura },
): string | null {
  const quadro: Record<string, Record<string, unknown>> = {};
  for (const acao of ["subscribe", "unsubscribe"] as const) {
    const dados = acoes[acao];
    if (dados === undefined) continue;
    const canal: Record<string, unknown> = {};
    if (dados.flow_status?.length) canal.flow_status = dados.flow_status;
    if (dados.mpc_state?.length) canal.mpc_state = dados.mpc_state;
    if (dados.events) canal.events = true;
    if (Object.keys(canal).length > 0) quadro[acao] = canal;
  }
  return Object.keys(quadro).length > 0 ? JSON.stringify(quadro) : null;
}

// --------------------------------------------------------------------------------------
// Roteamento de mensagem por canal (§5.3; fanout mpc.state — F4 §6.2; events — F5 §5)
// --------------------------------------------------------------------------------------

export interface MensagemFlowStatus {
  canal: "flow_status";
  flowId: number;
  status: FlowStatus;
}

export interface MensagemMpcState {
  canal: "mpc_state";
  chave: string;
  state: MpcState;
}

export interface MensagemEvento {
  canal: "events";
  evento: EventMessage;
}

export type MensagemCanal = MensagemFlowStatus | MensagemMpcState | MensagemEvento;

const PREFIXO_FLOW_STATUS = "flow.status.";
const PREFIXO_MPC_STATE = "mpc.state.";
const CANAL_EVENTS = "events";

const SEVERIDADES: Record<string, true> = { info: true, warning: true, alarm: true };

function lerFlowStatus(data: Record<string, unknown>): FlowStatus | null {
  const { state, scan_ms, overruns, ts } = data;
  if (!ehEstado(state)) return null;
  if (typeof scan_ms !== "number" || typeof overruns !== "number") return null;
  if (typeof ts !== "string") return null;
  return { state, scan_ms, overruns, ts, ports: lerPorts(data.ports) };
}

/** Validação leve: o barramento é a fonte da verdade (F4 §6.2); aqui só garante que o mapa
 *  nunca guarda algo que quebre um consumidor futuro.
 *  ponytail: sem checagem campo a campo de `vars`/`prediction`; apertar se a UI de MPC (fora
 *  do escopo desta tarefa) topar com bloco malformado vindo do wire. */
function lerMpcState(data: Record<string, unknown>): MpcState | null {
  if (typeof data.ts !== "string") return null;
  if (objeto(data.status) === null) return null;
  if (objeto(data.vars) === null) return null;
  return data as unknown as MpcState;
}

function lerEvento(data: Record<string, unknown>): EventMessage | null {
  if (typeof data.ts !== "string") return null;
  if (typeof data.severity !== "string" || SEVERIDADES[data.severity] !== true) return null;
  if (typeof data.origin !== "string") return null;
  if (typeof data.message !== "string") return null;
  if (objeto(data.payload) === null) return null;
  return data as unknown as EventMessage;
}

/**
 * Roteamento por `channel` (§5.3): o socket é um só e o fanout do servidor carimba o
 * flow/bloco no nome do canal. `mpc.state.<flowId>.<blockId>` corta só no primeiro ponto
 * (espelha `_mpc_id_of` do servidor — `block_id` pode ter ponto no nome). Mensagem de canal
 * desconhecido, malformada ou de sufixo inválido é descartada sem derrubar nada.
 */
export function analisarMensagemCanal(raw: string): MensagemCanal | null {
  let bruto: unknown;
  try {
    bruto = JSON.parse(raw);
  } catch {
    return null;
  }
  const env = objeto(bruto);
  if (env === null || typeof env.channel !== "string") return null;
  const canal = env.channel;
  const data = objeto(env.data);
  if (data === null) return null;

  if (canal === CANAL_EVENTS) {
    const evento = lerEvento(data);
    return evento === null ? null : { canal: "events", evento };
  }

  if (canal.startsWith(PREFIXO_FLOW_STATUS)) {
    const sufixo = canal.slice(PREFIXO_FLOW_STATUS.length);
    if (!/^\d+$/.test(sufixo)) return null;
    const status = lerFlowStatus(data);
    return status === null ? null : { canal: "flow_status", flowId: Number(sufixo), status };
  }

  if (canal.startsWith(PREFIXO_MPC_STATE)) {
    const sufixo = canal.slice(PREFIXO_MPC_STATE.length);
    const ponto = sufixo.indexOf(".");
    if (ponto <= 0) return null;
    const flowIdStr = sufixo.slice(0, ponto);
    const blockId = sufixo.slice(ponto + 1);
    if (!/^\d+$/.test(flowIdStr) || blockId.length === 0) return null;
    const state = lerMpcState(data);
    return state === null ? null : { canal: "mpc_state", chave: `${flowIdStr}/${blockId}`, state };
  }

  return null;
}

// --------------------------------------------------------------------------------------
// Redutor por canal (§4.2): mesclarPorts sobrevive, mpc_state substitui, eventos empilham
// --------------------------------------------------------------------------------------

function reduzir(atual: EstadoDoCanal, mensagem: MensagemCanal): EstadoDoCanal {
  switch (mensagem.canal) {
    case "flow_status": {
      const anterior = atual.flowStatus.get(mensagem.flowId);
      const ports = mesclarPorts(anterior?.ports ?? SEM_PORTS, mensagem.status.ports);
      const flowStatus = new Map(atual.flowStatus);
      flowStatus.set(mensagem.flowId, { ...mensagem.status, ports });
      return { ...atual, flowStatus };
    }
    case "mpc_state": {
      const mpcStates = new Map(atual.mpcStates);
      mpcStates.set(mensagem.chave, mensagem.state);
      return { ...atual, mpcStates };
    }
    case "events": {
      const eventos = [mensagem.evento, ...atual.eventos].slice(0, TETO_EVENTOS);
      return { ...atual, eventos };
    }
  }
}

// --------------------------------------------------------------------------------------
// Ciclo de vida do socket (§7.1): nasce com o provider, sobrevive à página, morre com a aba
// --------------------------------------------------------------------------------------

const AMBIENTE_BROWSER: AmbienteAoVivo = {
  criarSocket: (url) => new WebSocket(url),
  token: getToken,
  origem: () => window.location,
  agendar: (acao, atrasoMs) => window.setTimeout(acao, atrasoMs),
  cancelar: (id) => {
    window.clearTimeout(id);
  },
};

export type AplicarCanal = (transformacao: (atual: EstadoDoCanal) => EstadoDoCanal) => void;

export interface CicloVidaCanal {
  desmontar: () => void;
  /** Manda o delta assim que o socket estiver aberto; se ainda não conectou, não faz nada —
   *  o próximo `onopen`/religamento já lê `agregado()` e assina tudo de uma vez. */
  notificarInteresse: (delta: { subscribe?: DeltaInteresse; unsubscribe?: DeltaInteresse }) => void;
}

/**
 * Abre o socket da sessão e devolve o desmonte mais o canal de notificação de interesse.
 * Um socket só, para toda a aba: `agregado()` é a fonte da verdade do que assinar, lida no
 * connect e em cada reconexão (reconexão reassina tudo, nunca só o delta desde a queda).
 */
export function abrirCanalSessao(
  aplicar: AplicarCanal,
  agregado: () => Interesse,
  ambiente: AmbienteAoVivo = AMBIENTE_BROWSER,
): CicloVidaCanal {
  let ativo = true;
  let socket: WebSocket | null = null;
  let religar: number | null = null;
  let tentativa = 0;

  function desmontar(): void {
    ativo = false;
    if (religar !== null) {
      ambiente.cancelar(religar);
      religar = null;
    }
    if (socket === null) return;
    if (socket.readyState === WebSocket.OPEN) {
      const { flow_status, mpc_state } = agregado();
      const comando = comandoAssinatura({ unsubscribe: { flow_status, mpc_state, events: true } });
      if (comando !== null) socket.send(comando);
    }
    socket.close(1000, "Sessão encerrada");
    socket = null;
  }

  function conectar(): void {
    // O `cancelar` do desmonte não alcança um religamento que o relógio já entregou à fila
    // de tarefas: sem esta guarda, esse timer abriria um socket que ninguém mais fecha.
    if (!ativo) return;
    const token = ambiente.token();
    if (token === null) {
      aplicar((atual) => ({ ...atual, estado: "sessao_invalida" }));
      return;
    }
    const ws = ambiente.criarSocket(urlDoWs(ambiente.origem(), token));
    socket = ws;

    ws.onopen = () => {
      if (!ativo) return;
      tentativa = 0;
      const { flow_status, mpc_state } = agregado();
      const comando = comandoAssinatura({ subscribe: { flow_status, mpc_state, events: true } });
      if (comando !== null) ws.send(comando);
      aplicar((atual) => ({ ...atual, estado: "aberto" }));
    };

    ws.onmessage = (evento: MessageEvent<unknown>) => {
      if (!ativo || typeof evento.data !== "string") return;
      const mensagem = analisarMensagemCanal(evento.data);
      if (mensagem === null) return;
      aplicar((atual) => reduzir(atual, mensagem));
    };

    ws.onclose = (evento: CloseEvent) => {
      socket = null;
      if (!ativo) return;
      if (!deveReconectar(evento.code)) {
        aplicar((atual) => ({ ...atual, estado: "sessao_invalida" }));
        return;
      }
      aplicar((atual) => ({ ...atual, estado: "reconectando" }));
      religar = ambiente.agendar(conectar, atrasoReconexao(tentativa));
      tentativa += 1;
    };
  }

  function notificarInteresse(delta: { subscribe?: DeltaInteresse; unsubscribe?: DeltaInteresse }): void {
    if (socket === null || socket.readyState !== WebSocket.OPEN) return;
    const comando = comandoAssinatura(delta);
    if (comando !== null) socket.send(comando);
  }

  conectar();
  return { desmontar, notificarInteresse };
}

// --------------------------------------------------------------------------------------
// React: provider + hooks (spec F5 §7.1)
// --------------------------------------------------------------------------------------

interface ContextoAssinatura {
  registrar: (interesse: Interesse) => void;
  remover: (interesse: Interesse) => void;
}

const AssinaturaContext = createContext<ContextoAssinatura | null>(null);
const EstadoContext = createContext<EstadoDoCanal | null>(null);

/**
 * Atualiza o registro sempre, mesmo com `ciclo === null` (socket ainda não aberto): o
 * efeito de `useAssinatura` de uma página filha pode disparar antes do efeito do
 * `CanalAoVivoProvider` que abre o socket (React roda efeitos de filho para pai no mesmo
 * commit — é o caso de abrir a URL do editor direto, sem navegação prévia). Se o registro só
 * fosse atualizado atrás de `ciclo?.`, o interesse se perderia pra sempre e `conectar` nunca
 * veria o flow em `agregado()`. `notificarInteresse` é o único passo condicional ao ciclo já
 * existir: sem socket aberto ainda, o próprio `conectar` lê `agregado()` já atualizado.
 */
export function aplicarInteresse(
  registro: RegistroInteresses,
  ciclo: CicloVidaCanal | null,
  acao: "subscribe" | "unsubscribe",
  interesse: Interesse,
): void {
  const delta = acao === "subscribe" ? registro.adicionar(interesse) : registro.remover(interesse);
  ciclo?.notificarInteresse({ [acao]: delta });
}

// --------------------------------------------------------------------------------------
// Assinatura sob demanda por condição ativa (tarefa 2.3, spec F5 §7.1-5; F5R-04)
// --------------------------------------------------------------------------------------

const ORIGEM_FLOW = /^flow:(\d+)$/;

/** Deriva o `Interesse` que as famílias "estado" e "contador" de `resolverAlarmes` (2.1,
 *  `alarmes.ts`) exigem assinar: origem de bloco MPC (`flow:<id>/block:<id>`, `chaveMpc`)
 *  assina `mpc_state`; origem de flow (`flow:<id>`) assina `flow_status`. Famílias
 *  "par"/"ttl" não têm estado publicado nenhum pra seguir — ficam de fora por design, e
 *  nenhuma origem além das que `resolverAlarmes` já achou ativas entra aqui: nunca assina
 *  `flow_status` de todos os flows por precaução (spec §7.1-5).
 *
 *  Borda conhecida (documentada em `alarmes.ts`, `condicoesContador`): o toggle AUTO/MAN
 *  com um `mpc_overrun` pendente pode fazer `solver` sair de `"overrun"` sem ser o rearme
 *  de verdade — desde esta tarefa, isso gera um subscribe/unsubscribe REAL no socket (não
 *  só uma leitura em memória), consumindo um slot da fila de 8 do servidor (drop-oldest,
 *  `ws.py:45-48,68-74`). Disparado por ação do operador, não por oscilação automática. */
export function interesseDeCondicoes(condicoes: readonly CondicaoAtiva[]): Interesse {
  const flowIds = new Set<number>();
  const mpcChaves = new Set<string>();
  for (const condicao of condicoes) {
    if (condicao.familia !== "estado" && condicao.familia !== "contador") continue;
    const bloco = chaveMpc(condicao.origin);
    if (bloco !== null) {
      mpcChaves.add(bloco);
      continue;
    }
    const flow = ORIGEM_FLOW.exec(condicao.origin);
    if (flow !== null) flowIds.add(Number(flow[1]));
  }
  return { flow_status: [...flowIds], mpc_state: [...mpcChaves] };
}

export interface SincronizadorCondicoes {
  /** Compara o alvo desta varredura com o da anterior e manda só o delta que entrou/saiu —
   *  a mesma origem pode também estar pedida por uma página (`useAssinatura`); o
   *  unsubscribe do lado da condição só sai quando ESTA condição cessou, e o refcount do
   *  `RegistroInteresses` compartilhado garante que o socket só desliga o id quando ninguém
   *  mais (nem página, nem outra condição) ainda quer. */
  sincronizar: (
    condicoes: readonly CondicaoAtiva[],
    registro: RegistroInteresses,
    ciclo: CicloVidaCanal | null,
  ) => void;
}

/** Uma instância por `CanalAoVivoProvider` (mesmo padrão de `criarRegistroInteresses`):
 *  guarda o alvo da varredura anterior para nunca reincrementar o refcount de um id que já
 *  está sob assinatura por condição, e para saber exatamente o que soltar quando a condição
 *  cessa — sem isto, cada nova varredura chamaria `registro.adicionar` de novo para o mesmo
 *  id e o refcount nunca voltaria a zero.
 *
 *  Deliberadamente NÃO apaga a entrada de `mpcStates`/`flowStatus` quando desassina (fix
 *  round 1, revisão da tarefa 2.3): a checagem de frescor de `resolverAlarmes`
 *  (`estadoMaisNovoQueEvento`, `alarmes.ts`) já resolve a reocorrência sem isso — e apagar
 *  criaria um problema PIOR: `mpc.state` é publicado a cada execução do bloco em AUTO
 *  (`blocks/mpc.py:292-297`, "publicação a cada execução"), então a origem recém-cessada
 *  voltaria a publicar quase imediatamente; sem o estado retido, a próxima varredura cairia
 *  na regra A-4 ("sem estado ⇒ ativo"), reassinando na hora — e o ciclo se repetiria a cada
 *  execução do bloco, um FLAP contínuo de subscribe/unsubscribe (o `/ws` nunca reenvia um
 *  snapshot retido ao assinar, `ws.py:_apply_client_message`) — exatamente o tráfego que a
 *  assinatura sob demanda existe para evitar (fila de 8, drop-oldest, F5R-22). */
export function criarSincronizadorCondicoes(): SincronizadorCondicoes {
  let flowAtual = new Set<number>();
  let mpcAtual = new Set<string>();

  return {
    sincronizar(condicoes, registro, ciclo) {
      const alvo = interesseDeCondicoes(condicoes);
      const flowAlvo = new Set(alvo.flow_status ?? []);
      const mpcAlvo = new Set(alvo.mpc_state ?? []);

      const flowEntrando = [...flowAlvo].filter((id) => !flowAtual.has(id));
      const flowSaindo = [...flowAtual].filter((id) => !flowAlvo.has(id));
      const mpcEntrando = [...mpcAlvo].filter((chave) => !mpcAtual.has(chave));
      const mpcSaindo = [...mpcAtual].filter((chave) => !mpcAlvo.has(chave));

      if (flowEntrando.length > 0 || mpcEntrando.length > 0) {
        aplicarInteresse(registro, ciclo, "subscribe", { flow_status: flowEntrando, mpc_state: mpcEntrando });
      }
      if (flowSaindo.length > 0 || mpcSaindo.length > 0) {
        aplicarInteresse(registro, ciclo, "unsubscribe", { flow_status: flowSaindo, mpc_state: mpcSaindo });
      }

      flowAtual = flowAlvo;
      mpcAtual = mpcAlvo;
    },
  };
}

/** Blocos Script de um flow (emenda ao bootstrap, fix round 2, achado 2): `deGraphJson`
 *  já é a leitura tolerante e testada do `graph_json` (`graph.ts`) — nó ilegível vira
 *  descarte lá, nunca quebra aqui. Reaproveitada para não duplicar o parse. */
function blocosScriptDoFlow(flow: FlowDetail): OrigemBlocoScript[] {
  return deGraphJson(flow.graph_json)
    .nodes.filter((no) => no.type === "script")
    .map((no) => ({ flowId: flow.id, blockId: no.id }));
}

/** Fix round 3, gap 2: uma `FlowDetail` que falha não pode ficar muda — mesma regra do
 *  `logarFalha` de `bootstrapAlarmes.ts` (path + `status`/mensagem quando é `ApiError`),
 *  aqui identificando o flow em vez do path. Sem isto, um flow com `script_error`
 *  latchado cujo `graph_json` falhe ao carregar perderia a cobertura da emenda em
 *  silêncio, sem rastro nenhum (não há `onError` global — `router.tsx` usa
 *  `new QueryClient()` sem config). */
function logarFalhaGraphJson(flowId: number, motivo: unknown): void {
  const detalhe =
    motivo instanceof ApiError ? `${String(motivo.status)} ${motivo.message}` : String(motivo);
  console.error(
    `CanalAoVivoProvider: falha ao buscar graph_json do flow ${String(flowId)} para blocos Script (${detalhe})`,
  );
}

/** Fix round 4, mesma classe do achado 1/gap 2: `projetoAtivo`/`flows`/`conexoes`
 *  falhando (rede, 404) não pode virar bootstrap silenciosamente vazio. A política
 *  continua best-effort — o gate libera o bootstrap com o escopo que der (parcial ou
 *  vazio, nunca trava a sessão) — mas a perda de origem tem que deixar rastro. */
function logarFalhaConsulta(nome: string, motivo: unknown): void {
  const detalhe =
    motivo instanceof ApiError ? `${String(motivo.status)} ${motivo.message}` : String(motivo);
  console.error(
    `CanalAoVivoProvider: falha ao carregar ${nome} para o bootstrap de alarmes (${detalhe})`,
  );
}

/** Montado no `AppShell`: um socket por aba, vivo enquanto a sessão durar. `events` sempre
 *  assinado (o banner é do shell). Dois contexts, não um: `estado` muda a cada mensagem do
 *  socket, e um componente que só chama `useAssinatura` (registra e esquece) não precisa
 *  re-renderizar a cada varredura. */
export function CanalAoVivoProvider({ children }: { children: ReactNode }) {
  const [estado, setEstado] = useState<EstadoDoCanal>(ESTADO_INICIAL);
  const [registro] = useState(() => criarRegistroInteresses());
  const cicloRef = useRef<CicloVidaCanal | null>(null);
  const projetoAtivo = useActiveProject();
  const projectId = projetoAtivo.data?.id ?? null;
  const flows = useFlows(projectId);
  const conexoes = useConnections(projectId);
  /** Fix round 4: `projetoAtivo`/`flows`/`conexoes` falhando não pode passar batido —
   *  o bootstrap abaixo segue best-effort com o escopo que tiver (política inalterada),
   *  mas cada falha é logada uma única vez (mesmo desenho do efeito de `detalhesFlow`
   *  acima: nenhum efeito colateral dentro de `combine`/render). */
  const falhasConsultaLogadasRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const falhas: { chave: string; nome: string; motivo: unknown }[] = [
      ...(projetoAtivo.isError
        ? [{ chave: "projeto", nome: "o projeto ativo", motivo: projetoAtivo.error }]
        : []),
      ...(flows.isError
        ? [{ chave: "flows", nome: "os flows do projeto ativo", motivo: flows.error }]
        : []),
      ...(conexoes.isError
        ? [{ chave: "conexoes", nome: "as conexões do projeto ativo", motivo: conexoes.error }]
        : []),
    ];
    for (const { chave, nome, motivo } of falhas) {
      if (falhasConsultaLogadasRef.current.has(chave)) continue;
      falhasConsultaLogadasRef.current.add(chave);
      logarFalhaConsulta(nome, motivo);
    }
  }, [projetoAtivo.isError, projetoAtivo.error, flows.isError, flows.error, conexoes.isError, conexoes.error]);

  /** Flows cujo `graph_json` é buscado para achar blocos Script (emenda ao bootstrap,
   *  fix round 2, achado 2) — mesmo teto de flows do grupo 1 (`TETO_FLOWS`), corte
   *  determinístico (`flows.data` já chega ordenado por nome, `routers/flows.py`).
   *  `queryKey` igual à de `useFlow` (`useFlows.ts`) de propósito: compartilha cache com
   *  o editor se o operador abrir o mesmo flow depois. Uma falha isolada (rede, 404) não
   *  trava as outras nem o bootstrap — `pronto` só espera cada consulta assentar
   *  (sucesso OU erro), nunca as bloqueia entre si (mesmo espírito do
   *  `Promise.allSettled` de `bootstrapAlarmes`) — mas também não fica muda: `falhas`
   *  sai daqui (combine tem que ficar puro) e um efeito à parte loga cada uma
   *  (`logarFalhaGraphJson`, fix round 3, gap 2). */
  const idsParaBlocosScript = (flows.data ?? []).slice(0, TETO_FLOWS).map((flow) => flow.id);
  const detalhesFlow = useQueries({
    queries: idsParaBlocosScript.map((id) => ({
      queryKey: ["flows", "detalhe", id],
      queryFn: () => api<FlowDetail>(`/api/flows/${String(id)}`),
    })),
    combine: (resultados) => ({
      pronto: resultados.every((resultado) => resultado.isSuccess || resultado.isError),
      scriptBlocks: resultados.flatMap((resultado) =>
        resultado.data ? blocosScriptDoFlow(resultado.data) : [],
      ),
      falhas: resultados.flatMap((resultado, indice) =>
        resultado.isError
          ? [{ flowId: idsParaBlocosScript[indice], motivo: resultado.error }]
          : [],
      ),
    }),
  });
  const falhasLogadasRef = useRef<Set<number>>(new Set());
  useEffect(() => {
    for (const { flowId, motivo } of detalhesFlow.falhas) {
      if (falhasLogadasRef.current.has(flowId)) continue;
      falhasLogadasRef.current.add(flowId);
      logarFalhaGraphJson(flowId, motivo);
    }
  }, [detalhesFlow.falhas]);
  const [cacheBootstrap] = useState(() => criarCacheBootstrapAlarmes());
  const bootstrapFeitoRef = useRef(false);

  useEffect(() => {
    const ciclo = abrirCanalSessao((transformacao) => setEstado(transformacao), registro.agregado);
    cicloRef.current = ciclo;
    return () => {
      cicloRef.current = null;
      ciclo.desmontar();
    };
  }, [registro]);

  /** Assinatura sob demanda por condição ativa (tarefa 2.3, spec F5 §7.1-5; F5R-04): a cada
   *  varredura de `eventos`/`flowStatus`/`mpcStates`, `resolverAlarmes` (2.1) reavalia as
   *  famílias "estado"/"contador" e o sincronizador assina/desassina a origem correspondente
   *  — depende só do estado do canal, nunca de qual página está aberta. `cicloRef.current`
   *  pode estar `null` no primeiro commit (mesma corrida documentada em `aplicarInteresse`
   *  acima); o registro fica correto de qualquer forma e a varredura seguinte, já com o
   *  socket aberto, herda o alvo normalmente. */
  const [sincronizadorCondicoes] = useState(() => criarSincronizadorCondicoes());
  useEffect(() => {
    const condicoes = resolverAlarmes(estado.eventos, estado.flowStatus, estado.mpcStates, new Date());
    sincronizadorCondicoes.sincronizar(condicoes, registro, cicloRef.current);
  }, [estado.eventos, estado.flowStatus, estado.mpcStates, registro, sincronizadorCondicoes]);

  /** Bootstrap de alarmes (tarefa 2.2, spec F5 §7.2-3, emenda do fix round 2 — blocos
   *  Script): roda uma vez, quando o projeto ativo e (se houver um) seus flows/conexões
   *  e os `graph_json` para achar blocos Script terminam de carregar — nunca de novo por
   *  causa de um refetch em segundo plano da lista. Sem projeto ativo, o escopo por
   *  origem fica vazio e só o grupo 2 (severidade/janela, global) traz algo. Depois
   *  disto, só WS: os eventos ao vivo já chegam via `reduzir` acima. */
  useEffect(() => {
    if (bootstrapFeitoRef.current) return;
    if (projetoAtivo.isPending) return;
    if (projectId !== null && (flows.isPending || conexoes.isPending || !detalhesFlow.pronto)) return;
    bootstrapFeitoRef.current = true;
    const escopo: EscopoBootstrap = {
      flowIds: (flows.data ?? []).map((flow) => flow.id),
      connectionIds: (conexoes.data ?? []).map((conexao) => conexao.id),
      scriptBlocks: detalhesFlow.scriptBlocks,
    };
    cacheBootstrap
      .obter(escopo, new Date())
      .then((eventos) => {
        setEstado((atual) => ({
          ...atual,
          eventos: [...atual.eventos, ...eventos].slice(0, TETO_EVENTOS),
        }));
      })
      .catch(() => {
        // bootstrapAlarmes já é resiliente por dentro (Promise.allSettled, uma origem que
        // falha não derruba as outras nem impede o resto do estado retroativo de entrar).
        // Este catch só existe para nunca deixar uma promise sem handler se algo realmente
        // inesperado estourar aqui fora — não é o caminho normal de falha de origem.
      });
  }, [
    projetoAtivo.isPending,
    projectId,
    flows.isPending,
    flows.data,
    conexoes.isPending,
    conexoes.data,
    detalhesFlow.pronto,
    detalhesFlow.scriptBlocks,
    cacheBootstrap,
  ]);

  const contexto = useMemo<ContextoAssinatura>(
    () => ({
      registrar: (interesse) => aplicarInteresse(registro, cicloRef.current, "subscribe", interesse),
      remover: (interesse) => aplicarInteresse(registro, cicloRef.current, "unsubscribe", interesse),
    }),
    [registro],
  );

  return (
    <AssinaturaContext.Provider value={contexto}>
      <EstadoContext.Provider value={estado}>{children}</EstadoContext.Provider>
    </AssinaturaContext.Provider>
  );
}

/** Registra o interesse no mount, remove no unmount — sem reatividade a mudanças de
 *  `interesse` durante a vida do componente (o valor do primeiro render vale para a vida
 *  inteira; quem precisa de outro flow/bloco monta outro componente). */
export function useAssinatura(interesse: Interesse): void {
  const contexto = useContext(AssinaturaContext);
  if (contexto === null) {
    throw new Error("useAssinatura fora de CanalAoVivoProvider");
  }
  const interesseInicial = useRef(interesse).current;
  useEffect(() => {
    contexto.registrar(interesseInicial);
    return () => contexto.remover(interesseInicial);
  }, [contexto, interesseInicial]);
}

export function useCanalAoVivo(): EstadoDoCanal {
  const estado = useContext(EstadoContext);
  if (estado === null) {
    throw new Error("useCanalAoVivo fora de CanalAoVivoProvider");
  }
  return estado;
}
