import { expect, test } from "@playwright/test";

import type { EstadoDoCanal } from "../../app/CanalAoVivo";
import {
  atrasoReconexao,
  CODIGO_SESSAO_INVALIDA,
  deveReconectar,
  ehEstado,
  lerPorts,
  mesclarPorts,
  urlDoWs,
  type FlowStatus,
  type PortsPorBloco,
} from "./canalPrimitivos";
import {
  formatarNumero,
  formatarValorPorta,
  rotuloDeEspera,
  selecionarCanvas,
} from "./useFlowStatus";

/** O `Location` do browser tem muito mais superfície do que a URL do WS precisa. */
function origem(protocol: string, host: string): Location {
  return { protocol, host } as Location;
}

const ESTADO_VAZIO: EstadoDoCanal = {
  estado: "conectando",
  flowStatus: new Map(),
  mpcStates: new Map(),
  fuzzyStates: new Map(),
  eventos: [],
  tagValues: new Map(),
};

const STATUS: FlowStatus = {
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
  // como rota inexistente e vira 403, indistinguível de token recusado a olho nu.
  expect(url).not.toContain("/ws/");
});

test("origem https vira wss e o token é escapado para a query", () => {
  expect(urlDoWs(origem("https:", "planta.local"), "a b/c+d=")).toBe(
    "wss://planta.local/ws?token=a%20b%2Fc%2Bd%3D",
  );
});

// ----------------------------------------------------------------------------------------
// Leitura de portas do wire (§4.2) — reusada pelo provider em `lerFlowStatus`/`lerMpcState`
// ----------------------------------------------------------------------------------------

test("estado fora do vocabulário do flow não é um EstadoFlow válido", () => {
  expect(ehEstado("running")).toBe(true);
  expect(ehEstado("stopped")).toBe(true);
  expect(ehEstado("failed")).toBe(true);
  expect(ehEstado("pausado")).toBe(false);
});

test("porta de forma inesperada é descartada sem levar a varredura junto", () => {
  const ports = lerPorts({
    b1: { boa: { v: 1, ok: true }, ruim: { v: 1 }, texto: { v: "x", ok: true } },
  });

  expect(ports).toEqual({ b1: { boa: { v: 1, ok: true } } });
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
// Recorte do canal para o editor (§7.1): status/ports do flow pedido, conexão traduzida
// ----------------------------------------------------------------------------------------

test("sem mensagem do flow ainda: status nulo e conexão espelha o canal", () => {
  expect(selecionarCanvas(ESTADO_VAZIO, 12)).toEqual({ conexao: "conectando", status: null, ports: {} });
});

test("canal aberto vira conexão aberta: só o rótulo muda, o desfecho é o mesmo", () => {
  expect(selecionarCanvas({ ...ESTADO_VAZIO, estado: "aberto" }, 12).conexao).toBe("aberta");
});

test("reconectando e sessão inválida atravessam sem tradução", () => {
  expect(selecionarCanvas({ ...ESTADO_VAZIO, estado: "reconectando" }, 12).conexao).toBe("reconectando");
  expect(selecionarCanvas({ ...ESTADO_VAZIO, estado: "sessao_invalida" }, 12).conexao).toBe(
    "sessao_invalida",
  );
});

test("status e ports vêm do flow pedido, não de outro flow assinado no mesmo canal", () => {
  const flowStatus = new Map<number, FlowStatus>([
    [12, STATUS],
    [7, { ...STATUS, state: "stopped" }],
  ]);
  const canvas = selecionarCanvas({ ...ESTADO_VAZIO, flowStatus }, 12);

  expect(canvas.status).toEqual(STATUS);
  expect(canvas.ports).toBe(STATUS.ports);
});

test("flow sem mensagem no canal com outros flows assinados continua sem status", () => {
  const flowStatus = new Map<number, FlowStatus>([[7, STATUS]]);

  expect(selecionarCanvas({ ...ESTADO_VAZIO, flowStatus }, 12).status).toBeNull();
});

// ----------------------------------------------------------------------------------------
// Rótulo de espera do cabeçalho do editor: flow não comandado não "aguarda varredura"
// ----------------------------------------------------------------------------------------

test("flow não comandado (desejado parado, sem estado publicado) é 'Flow parado'", () => {
  expect(rotuloDeEspera("aberta", "stopped")).toBe("Flow parado");
  expect(rotuloDeEspera("conectando", "stopped")).toBe("Flow parado");
});

test("comando pendente mantém a espera da conexão: o operador comandou e aguarda", () => {
  expect(rotuloDeEspera("aberta", "running")).toBe("Aguardando dado da varredura");
  expect(rotuloDeEspera("conectando", "running")).toBe("Conectando ao canal ao vivo…");
  expect(rotuloDeEspera("reconectando", "running")).toBe("Reconectando ao canal ao vivo…");
});
