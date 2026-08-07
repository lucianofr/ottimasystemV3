import { expect, test } from "@playwright/test";

import { resolverAlarmes } from "./alarmes";
import {
  bootstrapAlarmes,
  criarCacheBootstrapAlarmes,
  type AmbienteBootstrap,
} from "./bootstrapAlarmes";
import type { EventMessage } from "./CanalAoVivo";

/**
 * `bootstrapAlarmes` (tarefa 2.2, spec F5 §7.2-3; F5R-03) — os dois grupos que alimentam
 * `resolverAlarmes` (2.1) no mount do shell: sem eles, um par latchado antes do reload
 * (`flow_failed` sem `flow_deployed` seguinte, por exemplo) fica invisível até o próximo
 * evento ao vivo — o REST não tem TTL. Cobre: teto de chamadas do grupo 1 (par, incluindo
 * a emenda de blocos Script — fix round 2), uma severidade por chamada + janela de 2h do
 * grupo 2 (demais famílias), cache de 60s, a mescla dos dois grupos, e a integração com
 * `resolverAlarmes` (último evento = abertura ⇒ ativa; par já fechado ⇒ inativa).
 */

const AGORA = new Date("2026-01-01T12:00:00.000Z");
const INICIO_JANELA = "2026-01-01T10:00:00.000Z"; // AGORA - 2h
const AVISO = `/api/events?severity=warning&start=${encodeURIComponent(INICIO_JANELA)}&limit=500`;
const ALARME = `/api/events?severity=alarm&start=${encodeURIComponent(INICIO_JANELA)}&limit=500`;

function evento(
  kind: string,
  origin: string,
  parcial: { ts?: string; severity?: "info" | "warning" | "alarm" } = {},
): EventMessage {
  return {
    ts: parcial.ts ?? AGORA.toISOString(),
    severity: parcial.severity ?? "alarm",
    origin,
    message: `mensagem de ${kind}`,
    payload: { kind },
  };
}

/** Fake de rede: devolve o que `respostas` mapeia para cada `path` exato (vazio por
 *  padrão) e registra toda chamada feita, na ordem em que aconteceram. */
function ambienteFake(respostas: Record<string, EventMessage[]> = {}): {
  ambiente: AmbienteBootstrap;
  chamadas: string[];
} {
  const chamadas: string[] = [];
  return {
    chamadas,
    ambiente: {
      buscar: (path) => {
        chamadas.push(path);
        return Promise.resolve(respostas[path] ?? []);
      },
    },
  };
}

// ----------------------------------------------------------------------------------------
// Grupo 1 — par de eventos: teto de chamadas
// ----------------------------------------------------------------------------------------

test("grupo 1: uma chamada origin por id, teto de 10 flows e 5 conexões, limit 20", async () => {
  const { ambiente, chamadas } = ambienteFake();
  const flowIds = Array.from({ length: 12 }, (_, i) => i + 1);
  const connectionIds = Array.from({ length: 7 }, (_, i) => i + 1);

  await bootstrapAlarmes({ flowIds, connectionIds, scriptBlocks: [] }, AGORA, ambiente);

  const deFlow = chamadas.filter((c) => c.includes("origin=flow:") && !c.includes("/block:"));
  const deConexao = chamadas.filter((c) => c.includes("origin=conn:"));
  expect(deFlow).toHaveLength(10);
  expect(deConexao).toHaveLength(5);
  expect(deFlow).toContain("/api/events?origin=flow:1&limit=20");
  expect(deFlow).not.toContain("/api/events?origin=flow:11&limit=20");
  expect(deConexao).toContain("/api/events?origin=conn:1&limit=20");
  expect(deConexao).not.toContain("/api/events?origin=conn:6&limit=20");
});

// ----------------------------------------------------------------------------------------
// Grupo 1 (emenda, fix round 2) — blocos Script: origem flow:<id>/block:<id>, teto de 20
// ----------------------------------------------------------------------------------------

test("grupo 1 (emenda): uma chamada origin por bloco Script, limit 20", async () => {
  const { ambiente, chamadas } = ambienteFake();

  await bootstrapAlarmes(
    {
      flowIds: [],
      connectionIds: [],
      scriptBlocks: [
        { flowId: 9, blockId: "script_a1b2c3d4" },
        { flowId: 12, blockId: "script_e5f6a7b8" },
      ],
    },
    AGORA,
    ambiente,
  );

  expect(chamadas).toContain("/api/events?origin=flow:9/block:script_a1b2c3d4&limit=20");
  expect(chamadas).toContain("/api/events?origin=flow:12/block:script_e5f6a7b8&limit=20");
});

test("grupo 1 (emenda): teto de 20 blocos Script no total, corte determinístico", async () => {
  const { ambiente, chamadas } = ambienteFake();
  const scriptBlocks = Array.from({ length: 25 }, (_, i) => ({
    flowId: 1,
    blockId: `script_${String(i + 1)}`,
  }));

  await bootstrapAlarmes({ flowIds: [], connectionIds: [], scriptBlocks }, AGORA, ambiente);

  const deBloco = chamadas.filter((c) => c.includes("/block:"));
  expect(deBloco).toHaveLength(20);
  expect(deBloco).toContain("/api/events?origin=flow:1/block:script_1&limit=20");
  expect(deBloco).not.toContain("/api/events?origin=flow:1/block:script_21&limit=20");
});

// ----------------------------------------------------------------------------------------
// Grupo 2 — demais famílias: uma severidade por chamada, janela de 2h
// ----------------------------------------------------------------------------------------

test("grupo 2: duas chamadas (warning e alarm), cada uma com sua própria severidade e a janela de 2h", async () => {
  const { ambiente, chamadas } = ambienteFake();

  await bootstrapAlarmes({ flowIds: [], connectionIds: [], scriptBlocks: [] }, AGORA, ambiente);

  expect(chamadas).toContain(AVISO);
  expect(chamadas).toContain(ALARME);
  // uma severidade por chamada: a API não aceita lista (schemas/events.py)
  expect(chamadas.some((c) => c.includes("severity=warning") && c.includes("severity=alarm"))).toBe(false);
});

test("grupo 2: a janela é recalculada a partir de `agora`, nunca fixa", async () => {
  const { ambiente, chamadas } = ambienteFake();
  const outroAgora = new Date("2026-03-15T08:30:00.000Z");
  const inicioEsperado = new Date(outroAgora.getTime() - 2 * 60 * 60 * 1000).toISOString();

  await bootstrapAlarmes({ flowIds: [], connectionIds: [], scriptBlocks: [] }, outroAgora, ambiente);

  expect(chamadas).toContain(
    `/api/events?severity=warning&start=${encodeURIComponent(inicioEsperado)}&limit=500`,
  );
});

// ----------------------------------------------------------------------------------------
// Mescla dos dois grupos
// ----------------------------------------------------------------------------------------

test("mescla os grupos por ts desc e remove duplicatas exatas entre eles", async () => {
  const duplicado = evento("flow_failed", "flow:9", { ts: "2026-01-01T11:00:00.000Z" });
  const maisNovo = evento("comm_failure", "conn:1", { ts: "2026-01-01T11:45:00.000Z" });
  const { ambiente } = ambienteFake({
    "/api/events?origin=flow:9&limit=20": [duplicado],
    [ALARME]: [duplicado, maisNovo],
  });

  const eventos = await bootstrapAlarmes(
    { flowIds: [9], connectionIds: [], scriptBlocks: [] },
    AGORA,
    ambiente,
  );

  expect(eventos).toEqual([maisNovo, duplicado]);
});

test("uma chamada rejeitada não derruba as outras: bootstrapAlarmes nunca rejeita", async () => {
  const sobrevivente = evento("comm_failure", "conn:1", { ts: "2026-01-01T11:00:00.000Z" });
  const ambiente: AmbienteBootstrap = {
    buscar: (path) => {
      if (path === "/api/events?origin=flow:9&limit=20") {
        return Promise.reject(new Error("falha de rede"));
      }
      if (path === ALARME) return Promise.resolve([sobrevivente]);
      return Promise.resolve([]);
    },
  };

  const eventos = await bootstrapAlarmes(
    { flowIds: [9], connectionIds: [], scriptBlocks: [] },
    AGORA,
    ambiente,
  );

  expect(eventos).toEqual([sobrevivente]);
});

// ----------------------------------------------------------------------------------------
// Cache de 60 s
// ----------------------------------------------------------------------------------------

test("cache: mesmo escopo dentro de 60s reaproveita, expira depois e refaz as chamadas", async () => {
  const { ambiente, chamadas } = ambienteFake();
  const cache = criarCacheBootstrapAlarmes();
  const escopo = { flowIds: [1], connectionIds: [], scriptBlocks: [] };

  await cache.obter(escopo, AGORA, ambiente);
  const apos1a = chamadas.length;
  expect(apos1a).toBeGreaterThan(0);

  await cache.obter(escopo, new Date(AGORA.getTime() + 59_999), ambiente);
  expect(chamadas).toHaveLength(apos1a);

  await cache.obter(escopo, new Date(AGORA.getTime() + 60_001), ambiente);
  expect(chamadas.length).toBeGreaterThan(apos1a);
});

test("cache: escopo diferente não reaproveita, mesmo dentro da janela de 60s", async () => {
  const { ambiente, chamadas } = ambienteFake();
  const cache = criarCacheBootstrapAlarmes();

  await cache.obter({ flowIds: [1], connectionIds: [], scriptBlocks: [] }, AGORA, ambiente);
  const apos1a = chamadas.length;

  await cache.obter({ flowIds: [2], connectionIds: [], scriptBlocks: [] }, AGORA, ambiente);
  expect(chamadas.length).toBeGreaterThan(apos1a);
});

test("cache: só a lista de blocos Script mudar (mesmos flows/conexões) também não reaproveita", async () => {
  const { ambiente, chamadas } = ambienteFake();
  const cache = criarCacheBootstrapAlarmes();

  await cache.obter({ flowIds: [1], connectionIds: [], scriptBlocks: [] }, AGORA, ambiente);
  const apos1a = chamadas.length;

  await cache.obter(
    { flowIds: [1], connectionIds: [], scriptBlocks: [{ flowId: 1, blockId: "script_1" }] },
    AGORA,
    ambiente,
  );
  expect(chamadas.length).toBeGreaterThan(apos1a);
});

// ----------------------------------------------------------------------------------------
// Integração com `resolverAlarmes`: último evento = abertura ⇒ ativa; par fechado ⇒ inativa
// ----------------------------------------------------------------------------------------

test("último evento do par é a abertura: resolverAlarmes acha a condição ativa", async () => {
  const { ambiente } = ambienteFake({
    "/api/events?origin=flow:9&limit=20": [
      evento("flow_failed", "flow:9", { ts: "2026-01-01T11:00:00.000Z" }),
    ],
    [AVISO]: [],
    [ALARME]: [],
  });

  const eventos = await bootstrapAlarmes(
    { flowIds: [9], connectionIds: [], scriptBlocks: [] },
    AGORA,
    ambiente,
  );
  const condicoes = resolverAlarmes(eventos, new Map(), new Map(), AGORA);

  expect(condicoes).toEqual([
    {
      familia: "par",
      kind: "flow_failed",
      origin: "flow:9",
      desde: "2026-01-01T11:00:00.000Z",
      severity: "alarm",
      message: "mensagem de flow_failed",
    },
  ]);
});

test("par já fechado (evento de recuperação é o mais recente): resolverAlarmes não acha condição ativa", async () => {
  const { ambiente } = ambienteFake({
    "/api/events?origin=flow:9&limit=20": [
      evento("flow_deployed", "flow:9", { ts: "2026-01-01T11:30:00.000Z" }),
      evento("flow_failed", "flow:9", { ts: "2026-01-01T11:00:00.000Z" }),
    ],
    [AVISO]: [],
    [ALARME]: [],
  });

  const eventos = await bootstrapAlarmes(
    { flowIds: [9], connectionIds: [], scriptBlocks: [] },
    AGORA,
    ambiente,
  );
  const condicoes = resolverAlarmes(eventos, new Map(), new Map(), AGORA);

  expect(condicoes).toEqual([]);
});

// ----------------------------------------------------------------------------------------
// Integração com `resolverAlarmes`: blocos Script (emenda, fix round 2, achado 2)
// ----------------------------------------------------------------------------------------

test("script_error como último evento na origem de bloco: resolverAlarmes acha a condição ativa", async () => {
  const origemBloco = "flow:9/block:script_a1b2c3d4";
  const { ambiente } = ambienteFake({
    "/api/events?origin=flow:9/block:script_a1b2c3d4&limit=20": [
      evento("script_error", origemBloco, { ts: "2026-01-01T09:00:00.000Z" }), // fora da janela de 2h
    ],
    [AVISO]: [],
    [ALARME]: [],
  });

  const eventos = await bootstrapAlarmes(
    { flowIds: [], connectionIds: [], scriptBlocks: [{ flowId: 9, blockId: "script_a1b2c3d4" }] },
    AGORA,
    ambiente,
  );
  const condicoes = resolverAlarmes(eventos, new Map(), new Map(), AGORA);

  expect(condicoes).toEqual([
    {
      familia: "par",
      kind: "script_error",
      origin: origemBloco,
      desde: "2026-01-01T09:00:00.000Z",
      severity: "alarm",
      message: "mensagem de script_error",
    },
  ]);
});

test("script_error seguido de script_recovered na mesma origem de bloco: resolverAlarmes não acha condição ativa", async () => {
  const origemBloco = "flow:9/block:script_a1b2c3d4";
  const { ambiente } = ambienteFake({
    "/api/events?origin=flow:9/block:script_a1b2c3d4&limit=20": [
      evento("script_recovered", origemBloco, { ts: "2026-01-01T11:30:00.000Z" }),
      evento("script_error", origemBloco, { ts: "2026-01-01T11:00:00.000Z" }),
    ],
    [AVISO]: [],
    [ALARME]: [],
  });

  const eventos = await bootstrapAlarmes(
    { flowIds: [], connectionIds: [], scriptBlocks: [{ flowId: 9, blockId: "script_a1b2c3d4" }] },
    AGORA,
    ambiente,
  );
  const condicoes = resolverAlarmes(eventos, new Map(), new Map(), AGORA);

  expect(condicoes).toEqual([]);
});
