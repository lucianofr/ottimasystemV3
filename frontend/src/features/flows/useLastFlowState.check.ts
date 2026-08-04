import { expect, test } from "@playwright/test";

import type { EventOut } from "../../lib/api";
import { aguardandoConfirmacao, derivarUltimoEstado } from "./useLastFlowState";

/** Base arbitrária: só a ordem relativa dos carimbos importa. */
const T0 = Date.parse("2026-01-01T12:00:00Z");

function carimbo(deslocamentoS: number): string {
  return new Date(T0 + deslocamentoS * 1000).toISOString();
}

function evento(
  deslocamentoS: number,
  origin: string,
  kind: string,
  reason?: string,
): EventOut {
  return {
    ts: carimbo(deslocamentoS),
    severity: kind === "flow_failed" ? "alarm" : "info",
    origin,
    message: kind,
    payload: reason === undefined ? { kind } : { kind, reason },
  };
}

/** O endpoint devolve `ts` desc; as listas dos testes montam nessa ordem. */
function desc(eventos: EventOut[]): EventOut[] {
  return [...eventos].sort((a, b) => b.ts.localeCompare(a.ts));
}

test("último evento de estado por flow vence, e cada flow é independente", () => {
  const mapa = derivarUltimoEstado(
    desc([
      evento(0, "flow:7", "flow_deployed"),
      evento(10, "flow:7", "flow_stopped", "user"),
      evento(5, "flow:8", "flow_deployed"),
    ]),
  );

  expect(mapa.get(7)).toEqual({
    estado: "parado",
    rotulo: "Parado: comandado pelo usuário",
    falha: false,
    ts: carimbo(10),
  });
  expect(mapa.get(8)?.estado).toBe("rodando");
  expect(mapa.get(8)?.rotulo).toBe("Rodando");
});

test("origin de bloco não é estado do flow", () => {
  // `flow:12/block:abc` casaria num `startsWith("flow:12")` e reportaria o flow 12 como
  // parado/falho por causa de um erro de script — que não derruba o flow.
  const mapa = derivarUltimoEstado(
    desc([
      evento(0, "flow:12", "flow_deployed"),
      evento(10, "flow:12/block:abc", "script_error"),
      evento(20, "flow:12/block:abc", "flow_failed", "comm_failure"),
    ]),
  );

  expect(mapa.get(12)?.estado).toBe("rodando");
  expect(mapa.size).toBe(1);
});

test("auditoria de CRUD e eventos de outros domínios não entram", () => {
  const mapa = derivarUltimoEstado(
    desc([
      evento(0, "user:3", "flow_created"),
      evento(10, "user:3", "flow_deleted"),
      // Auditoria com o mesmo `kind` do runtime continua fora: o `origin` é que decide.
      evento(20, "user:3", "flow_stopped", "user"),
      evento(30, "conn:1", "comm_failure", "session_lost"),
    ]),
  );

  expect(mapa.size).toBe(0);
});

test("flow_failed vira estado de falha com motivo em pt-BR; motivo ausente não vira vazio", () => {
  const mapa = derivarUltimoEstado(
    desc([
      evento(0, "flow:1", "flow_failed", "comm_failure"),
      evento(0, "flow:2", "flow_failed"),
      evento(0, "flow:3", "flow_stopped", "project_activated"),
    ]),
  );

  expect(mapa.get(1)).toMatchObject({
    estado: "falha",
    falha: true,
    rotulo: "Falha: falha de comunicação",
  });
  expect(mapa.get(2)?.rotulo).toBe("Falha: motivo desconhecido");
  expect(mapa.get(3)?.rotulo).toBe("Parado: projeto ativado");
});

test("pendente é exatamente a divergência entre desejado e publicado", () => {
  const rodando = derivarUltimoEstado([evento(0, "flow:1", "flow_deployed")]).get(1);
  const parado = derivarUltimoEstado([evento(0, "flow:1", "flow_stopped", "user")]).get(1);
  const falha = derivarUltimoEstado([evento(0, "flow:1", "flow_failed", "comm_failure")]).get(1);

  // Comandado e confirmado: nada pendente.
  expect(aguardandoConfirmacao("running", rodando)).toBe(false);
  expect(aguardandoConfirmacao("stopped", parado)).toBe(false);

  // Divergência: o comando não se materializou (publicação perdida — não há reconciliação
  // automática: nem o watermark de 10 s cobre deploy/stop, ADR-017).
  expect(aguardandoConfirmacao("running", parado)).toBe(true);
  expect(aguardandoConfirmacao("stopped", rodando)).toBe(true);

  // Falha é desfecho publicado, não espera: quem informa é a coluna "Último estado".
  expect(aguardandoConfirmacao("running", falha)).toBe(false);
  expect(aguardandoConfirmacao("stopped", falha)).toBe(false);

  // Sem evento nenhum: boot parado é o estado natural (ADR-017), rodando é comando sem eco.
  expect(aguardandoConfirmacao("stopped", undefined)).toBe(false);
  expect(aguardandoConfirmacao("running", undefined)).toBe(true);
});
