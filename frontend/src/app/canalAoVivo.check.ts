import { expect, test } from "@playwright/test";

import { CODIGO_SESSAO_INVALIDA, type AmbienteAoVivo } from "../features/flows/useFlowStatus";
import {
  abrirCanalSessao,
  analisarMensagemCanal,
  aplicarInteresse,
  comandoAssinatura,
  criarRegistroInteresses,
  TETO_EVENTOS,
  type CicloVidaCanal,
  type EstadoDoCanal,
  type RegistroInteresses,
} from "./CanalAoVivo";

/** O `Location` do browser tem muito mais superfície do que a URL do WS precisa. */
function origem(protocol: string, host: string): Location {
  return { protocol, host } as Location;
}

function envelope(channel: string, data: Record<string, unknown>): string {
  return JSON.stringify({ channel, data });
}

const VARREDURA = {
  state: "running",
  scan_ms: 3.2,
  overruns: 0,
  ts: "2026-08-04T12:00:00Z",
  ports: { leitura_1: { out: { v: 42.5, ok: true } } },
};

const MPC_STATE = {
  ts: "2026-08-04T12:00:00Z",
  modes: { mv_1: "auto" },
  status: { solver: "ok", overruns: 0, last_solve_ms: 12.5, armed: true, input_valid: true },
  vars: { mv_1: { v: 50, sp: 55 } },
  cost: 0.42,
  prediction: { ts: "2026-08-04T12:00:00Z", t: [0, 1], cv: [[1, 2]], mv: [[3, 4]] },
};

const EVENTO = {
  ts: "2026-08-04T12:00:00Z",
  severity: "warning",
  origin: "flow:1",
  message: "Falha",
  payload: {},
};

// ----------------------------------------------------------------------------------------
// Agregação de interesses de N páginas: refcount, deltas mínimos
// ----------------------------------------------------------------------------------------

test("duas páginas pedindo o mesmo flow: só a primeira gera delta de entrada", () => {
  const registro = criarRegistroInteresses();

  expect(registro.adicionar({ flow_status: [12] })).toEqual({ flow_status: [12], mpc_state: [] });
  expect(registro.adicionar({ flow_status: [12] })).toEqual({ flow_status: [], mpc_state: [] });
  expect(registro.agregado()).toEqual({ flow_status: [12], mpc_state: [] });
});

test("remover só desliga quando a última página que queria o id sai", () => {
  const registro = criarRegistroInteresses();
  registro.adicionar({ flow_status: [12] });
  registro.adicionar({ flow_status: [12] });

  expect(registro.remover({ flow_status: [12] })).toEqual({ flow_status: [], mpc_state: [] });
  expect(registro.agregado()).toEqual({ flow_status: [12], mpc_state: [] });

  expect(registro.remover({ flow_status: [12] })).toEqual({ flow_status: [12], mpc_state: [] });
  expect(registro.agregado()).toEqual({ flow_status: [], mpc_state: [] });
});

test("três páginas com interesses parcialmente sobrepostos agregam a união, sem duplicar", () => {
  const registro = criarRegistroInteresses();

  expect(registro.adicionar({ flow_status: [1, 2], mpc_state: ["1/b1"] })).toEqual({
    flow_status: [1, 2],
    mpc_state: ["1/b1"],
  });
  expect(registro.adicionar({ flow_status: [2, 3] })).toEqual({ flow_status: [3], mpc_state: [] });
  expect(registro.adicionar({ mpc_state: ["1/b1", "2/b2"] })).toEqual({
    flow_status: [],
    mpc_state: ["2/b2"],
  });

  expect(registro.agregado()).toEqual({ flow_status: [1, 2, 3], mpc_state: ["1/b1", "2/b2"] });

  // Uma das duas páginas que queriam o flow 2 sai: o outro ainda segura o id, sem delta.
  expect(registro.remover({ flow_status: [2, 3] })).toEqual({ flow_status: [3], mpc_state: [] });
  expect(registro.agregado()).toEqual({ flow_status: [1, 2], mpc_state: ["1/b1", "2/b2"] });
});

// ----------------------------------------------------------------------------------------
// Quadro de assinatura: delta multi-canal
// ----------------------------------------------------------------------------------------

test("quadro de assinatura só carrega os canais com id, nunca uma lista vazia", () => {
  expect(comandoAssinatura({ subscribe: { flow_status: [12], mpc_state: [], events: true } })).toBe(
    '{"subscribe":{"flow_status":[12],"events":true}}',
  );
  expect(comandoAssinatura({ subscribe: { flow_status: [], mpc_state: ["1/b1"] } })).toBe(
    '{"subscribe":{"mpc_state":["1/b1"]}}',
  );
});

test("subscribe e unsubscribe cabem no mesmo quadro quando o delta troca dos dois lados", () => {
  expect(
    comandoAssinatura({ subscribe: { flow_status: [3] }, unsubscribe: { flow_status: [7] } }),
  ).toBe('{"subscribe":{"flow_status":[3]},"unsubscribe":{"flow_status":[7]}}');
});

test("delta inteiramente vazio não produz quadro nenhum: nada para enviar", () => {
  expect(comandoAssinatura({ subscribe: { flow_status: [], mpc_state: [] } })).toBeNull();
  expect(comandoAssinatura({})).toBeNull();
});

// ----------------------------------------------------------------------------------------
// Roteamento de mensagem por canal (flow.status.*, mpc.state.*, events)
// ----------------------------------------------------------------------------------------

test("flow.status.<id> vira mensagem de flow_status com o id do canal, não do corpo", () => {
  const msg = analisarMensagemCanal(envelope("flow.status.12", VARREDURA));

  expect(msg?.canal).toBe("flow_status");
  if (msg?.canal === "flow_status") {
    expect(msg.flowId).toBe(12);
    expect(msg.status.state).toBe("running");
    expect(msg.status.ports).toEqual({ leitura_1: { out: { v: 42.5, ok: true } } });
  }
});

test("mpc.state.<flowId>.<blockId> vira mensagem de mpc_state com a chave flowId/blockId", () => {
  const msg = analisarMensagemCanal(envelope("mpc.state.1.b1", MPC_STATE));

  expect(msg?.canal).toBe("mpc_state");
  if (msg?.canal === "mpc_state") {
    expect(msg.chave).toBe("1/b1");
    expect(msg.state.vars.mv_1).toEqual({ v: 50, sp: 55 });
  }
});

test("bloco com ponto no nome usa só o primeiro ponto como separador flowId/blockId", () => {
  const msg = analisarMensagemCanal(envelope("mpc.state.1.b1.aux", MPC_STATE));

  expect(msg?.canal).toBe("mpc_state");
  if (msg?.canal === "mpc_state") expect(msg.chave).toBe("1/b1.aux");
});

test("events vira mensagem de evento com os 5 campos do contrato", () => {
  const msg = analisarMensagemCanal(envelope("events", EVENTO));

  expect(msg?.canal).toBe("events");
  if (msg?.canal === "events") {
    expect(msg.evento.message).toBe("Falha");
    expect(msg.evento.severity).toBe("warning");
  }
});

test("canal fora do vocabulário, sufixo não numérico ou payload inválido são descartados", () => {
  expect(analisarMensagemCanal("não é json")).toBeNull();
  expect(analisarMensagemCanal("[]")).toBeNull();
  expect(analisarMensagemCanal(JSON.stringify({ data: VARREDURA }))).toBeNull();
  expect(analisarMensagemCanal(envelope("opc.values.3", VARREDURA))).toBeNull();
  expect(analisarMensagemCanal(envelope("flow.status.abc", VARREDURA))).toBeNull();
  expect(analisarMensagemCanal(envelope("flow.status.1", { ...VARREDURA, state: "pausado" }))).toBeNull();
  expect(analisarMensagemCanal(envelope("flow.status.1", { ...VARREDURA, scan_ms: "3.2" }))).toBeNull();
  expect(analisarMensagemCanal(envelope("mpc.state.abc.b1", MPC_STATE))).toBeNull();
  expect(analisarMensagemCanal(envelope("mpc.state.1.", MPC_STATE))).toBeNull();
  expect(analisarMensagemCanal(envelope("events", { ...EVENTO, severity: "critico" }))).toBeNull();
});

// ----------------------------------------------------------------------------------------
// Ciclo de vida da sessão (§7.1): um socket por aba, reconexão reassina tudo, 1008 sem retry
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
  sockets: SocketFalso[];
  agendados: { id: number; acao: () => void; atrasoMs: number }[];
  cancelados: number[];
  registro: RegistroInteresses;
  estado: () => EstadoDoCanal;
  pendentes: () => number[];
  abrir: () => CicloVidaCanal;
}

const ESTADO_INICIAL: EstadoDoCanal = {
  estado: "conectando",
  flowStatus: new Map(),
  mpcStates: new Map(),
  eventos: [],
};

function bancada(token: string | null = "jwt"): Bancada {
  const sockets: SocketFalso[] = [];
  const agendados: { id: number; acao: () => void; atrasoMs: number }[] = [];
  const cancelados: number[] = [];
  const disparados: number[] = [];
  const registro = criarRegistroInteresses();
  let atual: EstadoDoCanal = ESTADO_INICIAL;

  const ambiente: AmbienteAoVivo = {
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
  };

  return {
    sockets,
    agendados,
    cancelados,
    registro,
    estado: () => atual,
    pendentes: () =>
      agendados.map(({ id }) => id).filter((id) => !cancelados.includes(id) && !disparados.includes(id)),
    abrir: () =>
      abrirCanalSessao(
        (transformacao) => {
          atual = transformacao(atual);
        },
        registro.agregado,
        ambiente,
      ),
  };
}

test("conectar manda um único quadro com events e o agregado das páginas já assinadas", () => {
  const b = bancada();
  b.registro.adicionar({ flow_status: [1, 2], mpc_state: ["1/b1"] });

  b.abrir();
  b.sockets[0].abrir();

  expect(b.sockets[0].enviados).toEqual([
    '{"subscribe":{"flow_status":[1,2],"mpc_state":["1/b1"],"events":true}}',
  ]);
  expect(b.estado().estado).toBe("aberto");
});

test("desmonte no meio do handshake fecha o socket que ainda nem abriu", () => {
  const b = bancada();
  const ciclo = b.abrir();
  ciclo.desmontar();

  expect(b.sockets[0].enviados).toEqual([]);
  expect(b.sockets[0].fechamentos).toEqual([1000]);
});

test("desmonte cancela o timer de reconexão e não deixa nem socket nem timer pendente", () => {
  const b = bancada();
  const ciclo = b.abrir();
  b.sockets[0].abrir();
  b.sockets[0].cair(1006);

  expect(b.pendentes()).toHaveLength(1);

  ciclo.desmontar();

  expect(b.pendentes()).toEqual([]);
  expect(b.sockets).toHaveLength(1);
  expect(b.sockets.every((socket) => socket.readyState === 3)).toBe(true);
});

test("timer que dispara depois do desmonte não ressuscita o socket", () => {
  const b = bancada();
  const ciclo = b.abrir();
  b.sockets[0].abrir();
  b.sockets[0].cair(1006);
  ciclo.desmontar();
  b.agendados[0].acao();

  expect(b.sockets).toHaveLength(1);
});

test("1008 encerra a sessão sem agendar reconexão: nada de bomba de requisição", () => {
  const b = bancada();
  b.abrir();
  b.sockets[0].abrir();
  b.sockets[0].cair(CODIGO_SESSAO_INVALIDA);

  expect(b.estado().estado).toBe("sessao_invalida");
  expect(b.agendados).toEqual([]);
  expect(b.sockets).toHaveLength(1);
});

test("queda de rede religa com backoff crescente e reassina o agregado inteiro, não só o delta", () => {
  const b = bancada();
  b.registro.adicionar({ flow_status: [12] });
  b.abrir();
  b.sockets[0].abrir();
  b.sockets[0].cair(1006);

  expect(b.estado().estado).toBe("reconectando");
  expect(b.agendados[0].atrasoMs).toBe(1000);

  // Entre a queda e o religamento uma segunda página passa a querer outro flow: o
  // religamento tem que enxergar o agregado atual, não o que existia antes da queda.
  b.registro.adicionar({ flow_status: [7] });

  b.agendados[0].acao();
  b.sockets[1].abrir();

  expect(b.sockets[1].enviados).toEqual(['{"subscribe":{"flow_status":[12,7],"events":true}}']);
  expect(b.estado().estado).toBe("aberto");
});

test("sem token não abre socket nenhum: sessão inválida antes do handshake", () => {
  const b = bancada(null);
  b.abrir();

  expect(b.sockets).toEqual([]);
  expect(b.estado().estado).toBe("sessao_invalida");
});

test("interesse que chega depois de conectado manda só o delta, sem repetir o que já ia assinado", () => {
  const b = bancada();
  b.registro.adicionar({ flow_status: [12] });
  const ciclo = b.abrir();
  b.sockets[0].abrir();
  b.sockets[0].enviados = [];

  const delta = b.registro.adicionar({ flow_status: [12, 7] });
  ciclo.notificarInteresse({ subscribe: delta });

  expect(b.sockets[0].enviados).toEqual(['{"subscribe":{"flow_status":[7]}}']);
});

test("interesse que muda antes de conectar não manda nada: a conexão herda do agregado", () => {
  const b = bancada();
  const ciclo = b.abrir();
  const delta = b.registro.adicionar({ flow_status: [12] });
  ciclo.notificarInteresse({ subscribe: delta });

  expect(b.sockets[0].enviados).toEqual([]);

  b.sockets[0].abrir();
  expect(b.sockets[0].enviados).toEqual(['{"subscribe":{"flow_status":[12],"events":true}}']);
});

test("desmontar com socket aberto desassina o agregado inteiro antes de fechar", () => {
  const b = bancada();
  b.registro.adicionar({ flow_status: [12], mpc_state: ["1/b1"] });
  const ciclo = b.abrir();
  b.sockets[0].abrir();
  b.sockets[0].enviados = [];

  ciclo.desmontar();

  expect(b.sockets[0].enviados).toEqual([
    '{"unsubscribe":{"flow_status":[12],"mpc_state":["1/b1"],"events":true}}',
  ]);
  expect(b.sockets[0].fechamentos).toEqual([1000]);
});

// ----------------------------------------------------------------------------------------
// `aplicarInteresse` (§7.1): registro nunca pode se perder por causa da ordem dos efeitos
// ----------------------------------------------------------------------------------------

test("registrar sem ciclo (socket ainda não aberto) não perde o interesse no agregado", () => {
  const registro = criarRegistroInteresses();

  // Reproduz a corrida real: o efeito de `useAssinatura` de uma página filha roda antes do
  // efeito do `CanalAoVivoProvider` que abre o socket (React roda efeitos de filho para pai
  // no mesmo commit ao abrir a URL do editor direto) — `ciclo` ainda é `null` aqui.
  aplicarInteresse(registro, null, "subscribe", { flow_status: [461] });

  expect(registro.agregado()).toEqual({ flow_status: [461], mpc_state: [] });
});

test("remover sem ciclo também atualiza o agregado, mesmo sem socket para notificar", () => {
  const registro = criarRegistroInteresses();
  registro.adicionar({ flow_status: [461] });

  aplicarInteresse(registro, null, "unsubscribe", { flow_status: [461] });

  expect(registro.agregado()).toEqual({ flow_status: [], mpc_state: [] });
});

test("com o ciclo já aberto, aplicarInteresse manda o delta na hora", () => {
  const b = bancada();
  const ciclo = b.abrir();
  b.sockets[0].abrir();
  b.sockets[0].enviados = [];

  aplicarInteresse(b.registro, ciclo, "subscribe", { flow_status: [461] });

  expect(b.sockets[0].enviados).toEqual(['{"subscribe":{"flow_status":[461]}}']);
  expect(b.registro.agregado()).toEqual({ flow_status: [461], mpc_state: [] });
});

// ----------------------------------------------------------------------------------------
// Redutor por canal (§4.2): mesclarPorts sobrevive, mpc_state substitui, eventos empilham
// ----------------------------------------------------------------------------------------

test("mensagem de flow_status preserva os últimos valores conhecidos na transição de estado", () => {
  const b = bancada();
  b.abrir();
  b.sockets[0].abrir();
  b.sockets[0].receber(envelope("flow.status.12", VARREDURA));

  expect(b.estado().flowStatus.get(12)?.ports).toEqual({ leitura_1: { out: { v: 42.5, ok: true } } });

  b.sockets[0].receber(
    envelope("flow.status.12", { state: "stopped", scan_ms: 0, overruns: 0, ts: VARREDURA.ts, ports: {} }),
  );

  expect(b.estado().flowStatus.get(12)?.state).toBe("stopped");
  expect(b.estado().flowStatus.get(12)?.ports).toEqual({ leitura_1: { out: { v: 42.5, ok: true } } });
});

test("mensagem de mpc_state indexa por flowId/blockId e substitui a leitura inteira", () => {
  const b = bancada();
  b.abrir();
  b.sockets[0].abrir();
  b.sockets[0].receber(envelope("mpc.state.1.b1", MPC_STATE));

  expect(b.estado().mpcStates.get("1/b1")?.cost).toBe(0.42);
});

test("eventos entram mais novo primeiro e respeitam o teto de memória", () => {
  const b = bancada();
  b.abrir();
  b.sockets[0].abrir();

  for (let i = 0; i < TETO_EVENTOS + 5; i++) {
    b.sockets[0].receber(envelope("events", { ...EVENTO, message: `evento ${String(i)}` }));
  }

  expect(b.estado().eventos).toHaveLength(TETO_EVENTOS);
  expect(b.estado().eventos[0].message).toBe(`evento ${String(TETO_EVENTOS + 4)}`);
  expect(b.estado().eventos[TETO_EVENTOS - 1].message).toBe("evento 5");
});
