import { useEffect, useState } from "react";

import { getToken, type FlowOut } from "../../lib/api";

/**
 * Canvas ao vivo (RF-305, spec F3 §5.3/§6.2): um socket por editor aberto, assinando o
 * `flow_status` do flow da URL e morrendo com a página.
 *
 * `/ws` não aparece no OpenAPI (WebSocket não existe em OpenAPI 3.0), então o payload é
 * tipado aqui, à mão. `EstadoFlow` deriva do enum gerado para `desired_state`: `running` e
 * `stopped` são os mesmos literais do banco, e `failed` é o único estado que só existe no
 * barramento (`FlowStatus` de `bus.py`, spec §4.2).
 */

export type EstadoFlow = FlowOut["desired_state"] | "failed";

/** `PortValue` do barramento: `v` é `float | bool | None` e `ok` é a flag de invalidez. */
export interface PortValue {
  v: number | boolean | null;
  ok: boolean;
}

/** `{block_id: {porta: PortValue}}` — a tabela inteira de portas de uma varredura. */
export type PortsPorBloco = Readonly<Record<string, Readonly<Record<string, PortValue>>>>;

export interface FlowStatus {
  state: EstadoFlow;
  scan_ms: number;
  overruns: number;
  ts: string;
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

const PREFIXO_CANAL = "flow.status.";
const ATRASO_BASE_MS = 1000;
const ATRASO_TETO_MS = 15000;

const SEM_PORTS: PortsPorBloco = {};

const INICIAL: CanvasAoVivo = { conexao: "conectando", status: null, ports: SEM_PORTS };

// --------------------------------------------------------------------------------------
// Protocolo (§5.3) — puro, testado em `useFlowStatus.check.ts`
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

export function comandoAssinatura(acao: "subscribe" | "unsubscribe", flowId: number): string {
  return JSON.stringify({ [acao]: { flow_status: [flowId] } });
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

function objeto(valor: unknown): Record<string, unknown> | null {
  return typeof valor === "object" && valor !== null && !Array.isArray(valor)
    ? (valor as Record<string, unknown>)
    : null;
}

function ehEstado(valor: unknown): valor is EstadoFlow {
  return valor === "running" || valor === "stopped" || valor === "failed";
}

function lerPortValue(bruto: unknown): PortValue | null {
  const item = objeto(bruto);
  if (item === null || typeof item.ok !== "boolean") return null;
  const v = item.v;
  if (v !== null && typeof v !== "number" && typeof v !== "boolean") return null;
  return { v, ok: item.ok };
}

function lerPorts(bruto: unknown): PortsPorBloco {
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

export interface MensagemStatus {
  flowId: number;
  status: FlowStatus;
}

/**
 * Roteamento por `channel` (§5.3): o socket é um só e o fanout do servidor carimba o flow
 * no nome do canal. Mensagem de outro canal, malformada ou de outro flow é descartada sem
 * derrubar nada — o mesmo contrato de tolerância que o servidor aplica ao cliente.
 */
export function analisarMensagem(raw: string): MensagemStatus | null {
  let bruto: unknown;
  try {
    bruto = JSON.parse(raw);
  } catch {
    return null;
  }
  const envelope = objeto(bruto);
  if (envelope === null || typeof envelope.channel !== "string") return null;
  if (!envelope.channel.startsWith(PREFIXO_CANAL)) return null;
  const sufixo = envelope.channel.slice(PREFIXO_CANAL.length);
  if (!/^\d+$/.test(sufixo)) return null;

  const data = objeto(envelope.data);
  if (data === null) return null;
  const { state, scan_ms, overruns, ts } = data;
  if (!ehEstado(state)) return null;
  if (typeof scan_ms !== "number" || typeof overruns !== "number") return null;
  if (typeof ts !== "string") return null;

  return {
    flowId: Number(sufixo),
    status: { state, scan_ms, overruns, ts, ports: lerPorts(data.ports) },
  };
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
// Ciclo de vida do socket
// --------------------------------------------------------------------------------------

/**
 * Socket, relógio e sessão como dependências. Em produção são os do browser; no check de
 * desmonte são dublês, que é como se prova que nada sobrou aberto ou agendado.
 */
export interface AmbienteAoVivo {
  criarSocket: (url: string) => WebSocket;
  token: () => string | null;
  origem: () => Location;
  agendar: (acao: () => void, atrasoMs: number) => number;
  cancelar: (id: number) => void;
}

const AMBIENTE_BROWSER: AmbienteAoVivo = {
  criarSocket: (url) => new WebSocket(url),
  token: getToken,
  origem: () => window.location,
  agendar: (acao, atrasoMs) => window.setTimeout(acao, atrasoMs),
  cancelar: (id) => {
    window.clearTimeout(id);
  },
};

export type AplicarAoVivo = (transformacao: (atual: CanvasAoVivo) => CanvasAoVivo) => void;

/**
 * Abre o canal do flow e devolve o desmonte. Um socket por chamada, assinando só este flow.
 *
 * Vazar socket por navegação é o defeito clássico deste hook, então o desmonte é a primeira
 * coisa escrita aqui: ele desfaz tudo o que `conectar` cria (socket e timer de reconexão) e
 * `ativo` neutraliza os callbacks que ainda estiverem em voo.
 */
export function abrirCanalAoVivo(
  flowId: number,
  aplicar: AplicarAoVivo,
  ambiente: AmbienteAoVivo = AMBIENTE_BROWSER,
): () => void {
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
    // Desassinar antes de fechar: o `unregister` do servidor limpa de qualquer jeito, mas o
    // `unsubscribe` é o contrato do §5.3 e vale para o socket que ainda vai fechar.
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(comandoAssinatura("unsubscribe", flowId));
    }
    socket.close(1000, "Editor fechado");
    socket = null;
  }

  function conectar(): void {
    // O `cancelar` do desmonte não alcança um religamento que o relógio já entregou à fila
    // de tarefas: sem esta guarda, esse timer abriria um socket que ninguém mais fecha.
    if (!ativo) return;
    const token = ambiente.token();
    if (token === null) {
      aplicar((atual) => ({ ...atual, conexao: "sessao_invalida" }));
      return;
    }
    const ws = ambiente.criarSocket(urlDoWs(ambiente.origem(), token));
    socket = ws;

    ws.onopen = () => {
      if (!ativo) return;
      tentativa = 0;
      ws.send(comandoAssinatura("subscribe", flowId));
      aplicar((atual) => ({ ...atual, conexao: "aberta" }));
    };

    ws.onmessage = (evento: MessageEvent<unknown>) => {
      if (!ativo || typeof evento.data !== "string") return;
      const recebido = analisarMensagem(evento.data);
      if (recebido === null || recebido.flowId !== flowId) return;
      aplicar((atual) => ({
        conexao: atual.conexao,
        status: recebido.status,
        ports: mesclarPorts(atual.ports, recebido.status.ports),
      }));
    };

    ws.onclose = (evento: CloseEvent) => {
      socket = null;
      if (!ativo) return;
      if (!deveReconectar(evento.code)) {
        aplicar((atual) => ({ ...atual, conexao: "sessao_invalida" }));
        return;
      }
      aplicar((atual) => ({ ...atual, conexao: "reconectando" }));
      religar = ambiente.agendar(conectar, atrasoReconexao(tentativa));
      tentativa += 1;
    };
  }

  conectar();
  return desmontar;
}

/** Um socket por editor aberto (§5.3): nasce com o flow da URL e morre com a página. */
export function useFlowStatus(flowId: number): CanvasAoVivo {
  const [aoVivo, setAoVivo] = useState<CanvasAoVivo>(INICIAL);

  useEffect(() => abrirCanalAoVivo(flowId, setAoVivo), [flowId]);

  return aoVivo;
}
