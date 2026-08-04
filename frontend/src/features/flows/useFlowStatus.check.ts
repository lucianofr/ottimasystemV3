import { expect, test } from "@playwright/test";

import {
  abrirCanalAoVivo,
  analisarMensagem,
  atrasoReconexao,
  CODIGO_SESSAO_INVALIDA,
  comandoAssinatura,
  deveReconectar,
  formatarNumero,
  formatarValorPorta,
  mesclarPorts,
  urlDoWs,
  type AmbienteAoVivo,
  type CanvasAoVivo,
  type PortsPorBloco,
} from "./useFlowStatus";

/** O `Location` do browser tem muito mais superfície do que a URL do WS precisa. */
function origem(protocol: string, host: string): Location {
  return { protocol, host } as Location;
}

function envelope(flowId: number, data: Record<string, unknown>): string {
  return JSON.stringify({ channel: `flow.status.${String(flowId)}`, data });
}

const VARREDURA = {
  state: "running",
  scan_ms: 3.2,
  overruns: 0,
  ts: "2026-08-04T12:00:00Z",
  ports: { leitura_1: { out: { v: 42.5, ok: true } } },
};

// ----------------------------------------------------------------------------------------
// URL (§5.3): `/ws` literal, nunca `/ws/`
// ----------------------------------------------------------------------------------------

test("a URL do WS termina em /ws antes da query, sem barra final", () => {
  const url = urlDoWs(origem("http:", "localhost:8080"), "abc.def");

  expect(url).toBe("ws://localhost:8080/ws?token=abc.def");
  // `location /ws` do nginx casa por prefixo e não reescreve: `/ws/` chega ao Starlette
  // como rota inexistente e vira 403, indistinguível de token recusado.
  expect(url).not.toContain("/ws/");
});

test("origem https vira wss e o token é escapado para a query", () => {
  expect(urlDoWs(origem("https:", "planta.local"), "a b/c+d=")).toBe(
    "wss://planta.local/ws?token=a%20b%2Fc%2Bd%3D",
  );
});

test("o quadro de assinatura é o do §5.3, verbatim", () => {
  expect(comandoAssinatura("subscribe", 12)).toBe('{"subscribe":{"flow_status":[12]}}');
  expect(comandoAssinatura("unsubscribe", 12)).toBe('{"unsubscribe":{"flow_status":[12]}}');
});

// ----------------------------------------------------------------------------------------
// Roteamento de mensagem por `channel`
// ----------------------------------------------------------------------------------------

test("mensagem do canal do flow vira status com as portas da varredura", () => {
  const recebido = analisarMensagem(envelope(12, VARREDURA));

  expect(recebido?.flowId).toBe(12);
  expect(recebido?.status.state).toBe("running");
  expect(recebido?.status.scan_ms).toBe(3.2);
  expect(recebido?.status.overruns).toBe(0);
  expect(recebido?.status.ports).toEqual({ leitura_1: { out: { v: 42.5, ok: true } } });
});

test("o flow vem do canal, não do corpo: dois flows não se misturam", () => {
  expect(analisarMensagem(envelope(7, VARREDURA))?.flowId).toBe(7);
  expect(analisarMensagem(envelope(70, VARREDURA))?.flowId).toBe(70);
});

test("canal de outro assunto ou com sufixo não numérico é descartado", () => {
  const data = VARREDURA;
  expect(analisarMensagem(JSON.stringify({ channel: "events", data }))).toBeNull();
  expect(analisarMensagem(JSON.stringify({ channel: "opc.values.3", data }))).toBeNull();
  expect(analisarMensagem(JSON.stringify({ channel: "flow.status.", data }))).toBeNull();
  expect(analisarMensagem(JSON.stringify({ channel: "flow.status.abc", data }))).toBeNull();
});

test("quadro não-JSON, sem envelope ou com estado fora do vocabulário não derruba nada", () => {
  expect(analisarMensagem("não é json")).toBeNull();
  expect(analisarMensagem("[]")).toBeNull();
  expect(analisarMensagem(JSON.stringify({ data: VARREDURA }))).toBeNull();
  expect(analisarMensagem(envelope(1, { ...VARREDURA, state: "pausado" }))).toBeNull();
  expect(analisarMensagem(envelope(1, { ...VARREDURA, scan_ms: "3.2" }))).toBeNull();
});

test("porta de forma inesperada é descartada sem levar a varredura junto", () => {
  const recebido = analisarMensagem(
    envelope(1, {
      ...VARREDURA,
      ports: { b1: { boa: { v: 1, ok: true }, ruim: { v: 1 }, texto: { v: "x", ok: true } } },
    }),
  );

  expect(recebido?.status.ports).toEqual({ b1: { boa: { v: 1, ok: true } } });
});

test("publicação de transição chega sem ports e continua sendo estado válido", () => {
  const recebido = analisarMensagem(
    envelope(3, { state: "stopped", scan_ms: 0, overruns: 0, ts: VARREDURA.ts, ports: {} }),
  );

  expect(recebido?.status.state).toBe("stopped");
  expect(recebido?.status.ports).toEqual({});
});

// ----------------------------------------------------------------------------------------
// Preservação de valores na transição (§4.2)
// ----------------------------------------------------------------------------------------

test("transição de estado preserva os últimos valores conhecidos", () => {
  const conhecidos: PortsPorBloco = { b1: { out: { v: 42.5, ok: true } } };

  expect(mesclarPorts(conhecidos, {})).toBe(conhecidos);
});

test("varredura substitui a tabela inteira, inclusive apagando bloco que saiu do grafo", () => {
  const conhecidos: PortsPorBloco = { b1: { out: { v: 1, ok: true } }, b2: { in: { v: 2, ok: true } } };
  const nova: PortsPorBloco = { b1: { out: { v: 9, ok: true } } };

  expect(mesclarPorts(conhecidos, nova)).toEqual({ b1: { out: { v: 9, ok: true } } });
});

// ----------------------------------------------------------------------------------------
// Política de reconexão (§5.3): 1008 é sessão, não rede
// ----------------------------------------------------------------------------------------

test("1008 não reconecta; queda de rede reconecta", () => {
  expect(deveReconectar(CODIGO_SESSAO_INVALIDA)).toBe(false);
  expect(deveReconectar(1006)).toBe(true); // fechamento anormal (queda)
  expect(deveReconectar(1001)).toBe(true); // servidor saindo
  expect(deveReconectar(1012)).toBe(true); // reinício do serviço
});

test("o backoff cresce e tem teto: nunca vira rajada nem espera infinita", () => {
  const atrasos = [0, 1, 2, 3, 4, 5, 20].map(atrasoReconexao);

  expect(atrasos.slice(0, 4)).toEqual([1000, 2000, 4000, 8000]);
  expect(atrasos.every((atraso, i) => i === 0 || atraso >= atrasos[i - 1])).toBe(true);
  expect(Math.max(...atrasos)).toBe(15000);
});

// ----------------------------------------------------------------------------------------
// Formatação de valor por tipo
// ----------------------------------------------------------------------------------------

test("numérico sai em pt-BR, com decimal por vírgula e sem cauda de ponto flutuante", () => {
  expect(formatarValorPorta({ v: 42.5, ok: true })).toBe("42,5");
  expect(formatarValorPorta({ v: 42, ok: true })).toBe("42");
  expect(formatarValorPorta({ v: -0.125, ok: true })).toBe("-0,125");
  expect(formatarValorPorta({ v: 0.1 + 0.2, ok: true })).toBe("0,3");
  expect(formatarNumero(1234.5678)).toBe("1234,568");
});

test("booleano e ausência de valor são texto, nunca zero", () => {
  expect(formatarValorPorta({ v: true, ok: true })).toBe("verdadeiro");
  expect(formatarValorPorta({ v: false, ok: true })).toBe("falso");
  expect(formatarValorPorta({ v: null, ok: false })).toBe("sem valor");
  // `false` é valor legítimo: não pode virar "sem valor" por queda em falsy.
  expect(formatarValorPorta({ v: false, ok: true })).not.toBe("sem valor");
});

test("invalidez não muda o texto do valor: dessaturar e rotular é canal à parte", () => {
  expect(formatarValorPorta({ v: 42.5, ok: false })).toBe("42,5");
});

// ----------------------------------------------------------------------------------------
// Ciclo de vida (§5.3, contrato "um socket por editor, e ele morre com a página")
// ----------------------------------------------------------------------------------------

/** Dublê do `WebSocket`: registra o que foi enviado e fechado, e deixa disparar os eventos.
 *  O cast é o preço de dublar uma classe do DOM cuja superfície não usamos inteira. */
class SocketFalso {
  readyState = 0; // CONNECTING
  enviados: string[] = [];
  fechamentos: number[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((evento: MessageEvent<unknown>) => void) | null = null;
  onclose: ((evento: CloseEvent) => void) | null = null;

  send(dados: string): void {
    this.enviados.push(dados);
  }

  close(codigo?: number): void {
    this.readyState = 3; // CLOSED
    this.fechamentos.push(codigo ?? 1005);
  }

  abrir(): void {
    this.readyState = 1; // OPEN
    this.onopen?.();
  }

  receber(texto: string): void {
    this.onmessage?.({ data: texto } as MessageEvent<unknown>);
  }

  cair(code: number): void {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }
}

interface Bancada {
  ambiente: AmbienteAoVivo;
  sockets: SocketFalso[];
  agendados: { id: number; acao: () => void; atrasoMs: number }[];
  cancelados: number[];
  estado: () => CanvasAoVivo;
  aplicar: (transformacao: (atual: CanvasAoVivo) => CanvasAoVivo) => void;
  /** Timers criados e ainda não cancelados nem disparados. */
  pendentes: () => number[];
}

function bancada(token: string | null = "jwt"): Bancada {
  const sockets: SocketFalso[] = [];
  const agendados: { id: number; acao: () => void; atrasoMs: number }[] = [];
  const cancelados: number[] = [];
  const disparados: number[] = [];
  let atual: CanvasAoVivo = { conexao: "conectando", status: null, ports: {} };

  return {
    sockets,
    agendados,
    cancelados,
    estado: () => atual,
    aplicar: (transformacao) => {
      atual = transformacao(atual);
    },
    pendentes: () =>
      agendados
        .map(({ id }) => id)
        .filter((id) => !cancelados.includes(id) && !disparados.includes(id)),
    ambiente: {
      criarSocket: () => {
        const falso = new SocketFalso();
        sockets.push(falso);
        return falso as unknown as WebSocket;
      },
      token: () => token,
      origem: () => origem("http:", "localhost:8080"),
      agendar: (acao, atrasoMs) => {
        const id = agendados.length + 1;
        agendados.push({
          id,
          atrasoMs,
          acao: () => {
            disparados.push(id);
            acao();
          },
        });
        return id;
      },
      cancelar: (id) => cancelados.push(id),
    },
  };
}

test("abrir assina só o flow do editor, e o desmonte desassina e fecha o socket", () => {
  const b = bancada();

  const desmontar = abrirCanalAoVivo(12, b.aplicar, b.ambiente);
  b.sockets[0].abrir();

  expect(b.sockets).toHaveLength(1);
  expect(b.sockets[0].enviados).toEqual(['{"subscribe":{"flow_status":[12]}}']);
  expect(b.estado().conexao).toBe("aberta");

  desmontar();

  expect(b.sockets[0].enviados).toEqual([
    '{"subscribe":{"flow_status":[12]}}',
    '{"unsubscribe":{"flow_status":[12]}}',
  ]);
  expect(b.sockets[0].fechamentos).toEqual([1000]);
  expect(b.sockets[0].readyState).toBe(3);
});

test("desmonte no meio do handshake fecha o socket que ainda nem abriu", () => {
  const b = bancada();

  const desmontar = abrirCanalAoVivo(12, b.aplicar, b.ambiente);
  desmontar();

  // Socket em CONNECTING não recebe `unsubscribe` (o quadro se perderia), mas fecha.
  expect(b.sockets[0].enviados).toEqual([]);
  expect(b.sockets[0].fechamentos).toEqual([1000]);
});

test("desmonte cancela o timer de reconexão e não deixa nem socket nem timer pendente", () => {
  const b = bancada();

  const desmontar = abrirCanalAoVivo(12, b.aplicar, b.ambiente);
  b.sockets[0].abrir();
  b.sockets[0].cair(1006); // queda de rede: agenda religamento

  expect(b.pendentes()).toHaveLength(1);

  desmontar();

  expect(b.pendentes()).toEqual([]);
  expect(b.sockets).toHaveLength(1);
  expect(b.sockets.every((socket) => socket.readyState === 3)).toBe(true);
});

test("timer que dispara depois do desmonte não ressuscita o socket", () => {
  const b = bancada();

  const desmontar = abrirCanalAoVivo(12, b.aplicar, b.ambiente);
  b.sockets[0].abrir();
  b.sockets[0].cair(1006);
  desmontar();
  // Timer já disparado pelo relógio real antes do `clearTimeout` chegar: mesmo assim o
  // desmonte é definitivo.
  b.agendados[0].acao();

  expect(b.sockets).toHaveLength(1);
});

test("1008 encerra a sessão sem agendar reconexão: nada de bomba de requisição", () => {
  const b = bancada();

  abrirCanalAoVivo(12, b.aplicar, b.ambiente);
  b.sockets[0].abrir();
  b.sockets[0].cair(CODIGO_SESSAO_INVALIDA);

  expect(b.estado().conexao).toBe("sessao_invalida");
  expect(b.agendados).toEqual([]);
  expect(b.sockets).toHaveLength(1);
});

test("queda de rede religa com backoff crescente e reassina o flow", () => {
  const b = bancada();

  abrirCanalAoVivo(12, b.aplicar, b.ambiente);
  b.sockets[0].abrir();
  b.sockets[0].cair(1006);

  expect(b.estado().conexao).toBe("reconectando");
  expect(b.agendados[0].atrasoMs).toBe(1000);

  b.agendados[0].acao();
  b.sockets[1].cair(1006); // segunda queda, ainda sem abrir

  expect(b.agendados[1].atrasoMs).toBe(2000);

  b.agendados[1].acao();
  b.sockets[2].abrir();

  expect(b.sockets[2].enviados).toEqual(['{"subscribe":{"flow_status":[12]}}']);
  expect(b.estado().conexao).toBe("aberta");

  // Reconexão bem-sucedida rearma o backoff: a próxima queda não herda o atraso da anterior.
  b.sockets[2].cair(1006);
  expect(b.agendados[2].atrasoMs).toBe(1000);
});

test("sem token não abre socket nenhum: sessão inválida antes do handshake", () => {
  const b = bancada(null);

  abrirCanalAoVivo(12, b.aplicar, b.ambiente);

  expect(b.sockets).toEqual([]);
  expect(b.estado().conexao).toBe("sessao_invalida");
});

test("transição de estado não apaga o canvas, e mensagem de outro flow é ignorada", () => {
  const b = bancada();

  abrirCanalAoVivo(12, b.aplicar, b.ambiente);
  b.sockets[0].abrir();
  b.sockets[0].receber(envelope(12, VARREDURA));

  expect(b.estado().ports).toEqual({ leitura_1: { out: { v: 42.5, ok: true } } });

  b.sockets[0].receber(
    envelope(12, { state: "stopped", scan_ms: 0, overruns: 0, ts: VARREDURA.ts, ports: {} }),
  );

  expect(b.estado().status?.state).toBe("stopped");
  expect(b.estado().ports).toEqual({ leitura_1: { out: { v: 42.5, ok: true } } });

  b.sockets[0].receber(envelope(99, { ...VARREDURA, overruns: 7 }));

  expect(b.estado().status?.overruns).toBe(0);
});