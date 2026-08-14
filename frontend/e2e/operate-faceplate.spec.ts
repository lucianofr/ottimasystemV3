import { expect, test } from "@playwright/test";

import { criarAmbiente, entrarNoShell, NODES, type AmbienteE2E } from "./fixtures";

/**
 * PW-FC-01..03 — faceplates da Operação na taxa OPC (decisão F6 A-1 revertida): canal
 * `opc.values` assinado por tag no `/ws`, PV do faceplate atualizando mais rápido que o
 * Ts_mpc, e escala da barra = faixa de instrumento `[zero, zero+span]` (RF-609).
 *
 * Grafo MPC mínimo com DEPLOY (diferente de `operate-trend.spec.ts`): `opc_read` no `sine`
 * do opcsim alimenta a CV, e a MV direta usa a MESMA tag como `readback_tag_id` — então os
 * dois faceplates têm `tag_id` na projeção e assinam `opc_values`. `ts_seconds: 1` +
 * `multiplier: 5` dão Ts_mpc = 5 s: qualquer atualização de PV mais rápida que isso só pode
 * vir do canal OPC.
 */

let ambiente: AmbienteE2E;
let flowId: number;
let quadrosOpcValues = 0;

const BLOCK_ID = "mpc1";
const TS_FLOW_S = 1;

function grafoMpc(
  tagId: number,
  faixas: { mvZero?: number; mvSpan?: number; cvZero?: number; cvSpan?: number } = {},
) {
  return {
    nodes: [
      {
        id: "leitura",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 1, tag_id: tagId },
      },
      {
        id: BLOCK_ID,
        type: "mpc",
        position: { x: 0, y: 0 },
        data: {
          exec_order: 2,
          name: "MPC faceplate",
          multiplier: 5,
          variables: {
            mvs: [
              {
                id: "mv_1",
                name: "Abertura",
                eu: "%",
                zero: faixas.mvZero ?? 0,
                span: faixas.mvSpan ?? 100,
                limits: { min: 0, max: 100 },
                max_rate: 5,
                initial_value: 0,
                readback_tag_id: tagId,
              },
            ],
            cvs: [
              {
                id: "cv_1",
                name: "Nivel",
                eu: "%",
                zero: faixas.cvZero ?? 0,
                span: faixas.cvSpan ?? 100,
                kind: "selfreg",
                tss: 60,
                weight: 1,
                sp_limits: { min: 0, max: 100 },
              },
            ],
            constraints: [],
            dvs: [],
          },
          models: { cv_1: { mv_1: { enabled: true, params: { K: 1, tau1: 2, tau2: 0.5, theta: 0 } } } },
        },
      },
    ],
    edges: [
      { id: "e1", source: "leitura", sourceHandle: "out", target: BLOCK_ID, targetHandle: "cv_1" },
    ],
  };
}

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "faceplate",
    tags: [{ chave: "sine", nodeId: NODES.sine, direcao: "r" }],
  });
  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: "Flow faceplate E2E", ts_seconds: TS_FLOW_S },
  });
  if (!criado.ok()) throw new Error(`criação do flow: HTTP ${criado.status()}`);
  flowId = ((await criado.json()) as { id: number }).id;
  const salvo = await ambiente.api.put(`/api/flows/${String(flowId)}`, {
    data: { graph_json: grafoMpc(ambiente.tags["sine"]) },
  });
  if (!salvo.ok()) {
    throw new Error(`salvar grafo: HTTP ${salvo.status()} — ${await salvo.text()}`);
  }
  const deploy = await ambiente.api.post(`/api/flows/${String(flowId)}/deploy`);
  if (deploy.status() !== 202) throw new Error(`deploy: HTTP ${deploy.status()}`);
  await expect
    .poll(
      async () =>
        ((await (await ambiente.api.get(`/api/flows/${String(flowId)}`)).json()) as {
          desired_state: string;
        }).desired_state,
      { message: "flow running", timeout: 15_000 },
    )
    .toBe("running");
});

test.afterAll(async () => {
  await ambiente.api.post(`/api/flows/${String(flowId)}/stop`);
  await expect
    .poll(
      async () =>
        ((await (await ambiente.api.get(`/api/flows/${String(flowId)}`)).json()) as {
          desired_state: string;
        }).desired_state,
      { message: "flow stopped", timeout: 15_000 },
    )
    .toBe("stopped");
  await ambiente.api.delete(`/api/flows/${String(flowId)}`);
  await ambiente.encerrar();
});

test.beforeEach(async ({ page }) => {
  // O /ws abre no login: o listener de quadros `opc.values` precisa ser registrado ANTES
  // do `entrarNoShell`, ou ele nunca vê o socket. Os frames só fluem quando a página de
  // operação assina as tags — o contador é zerado no início do PW-FC-01 por higiene.
  page.on("websocket", (ws) => {
    if (!ws.url().includes("/ws")) return;
    ws.on("framereceived", (frame) => {
      const payload = frame.payload;
      // O fanout usa json.dumps padrão do Python — `"channel": "opc.values.…"` com espaço.
      if (typeof payload === "string" && payload.includes('"channel": "opc.values.')) {
        quadrosOpcValues += 1;
      }
    });
  });
  await entrarNoShell(page);
});

test.describe("Faceplates na taxa OPC", () => {
  test("PW-FC-01: o /ws recebe quadros opc.values para as tags assinadas", async ({ page }) => {
    quadrosOpcValues = 0;
    await page.goto(`/operacao/${String(flowId)}/${BLOCK_ID}`);
    await expect(page.getByTestId("operate-page")).toBeVisible();
    await expect
      .poll(() => quadrosOpcValues, { message: "quadros opc.values em 4 s", timeout: 6_000 })
      .toBeGreaterThanOrEqual(2);
  });

  test("PW-FC-02: PV do faceplate atualiza mais rápido que o Ts_mpc (5 s)", async ({ page }) => {
    await page.goto(`/operacao/${String(flowId)}/${BLOCK_ID}`);
    const pv = page.getByTestId("faceplate-pv-mv_1");
    await expect(pv).toBeVisible();

    // 6 leituras a cada 500 ms (3 s de janela < Ts_mpc): o sine do opcsim varre rápido, e o
    // flush de 250 ms do provider publica cada leitura nova — ≥2 valores distintos provam a
    // taxa OPC (pelo `mpc.state` o PV só mudaria a cada 5 s).
    const leituras = new Set<string>();
    for (let i = 0; i < 6; i++) {
      leituras.add((await pv.textContent()) ?? "");
      await page.waitForTimeout(500);
    }
    expect(leituras.size).toBeGreaterThanOrEqual(2);
  });

  test("PW-FC-03: escala da barra é a faixa de instrumento (zero/span), nunca 0..100 cego", async ({
    page,
  }) => {
    // Seed dedicado: MV zero=20/span=50 com limits 0..100, CV zero=10/span=40 com
    // sp_limits 0..100 — a barra mostra 20..70 e 10..50, nunca os limites de engenharia.
    const criado = await ambiente.api.post("/api/flows", {
      data: { project_id: ambiente.projectId, name: "Flow faceplate faixa E2E", ts_seconds: TS_FLOW_S },
    });
    if (!criado.ok()) throw new Error(`criação do flow: HTTP ${criado.status()}`);
    const id = ((await criado.json()) as { id: number }).id;
    const salvo = await ambiente.api.put(`/api/flows/${String(id)}`, {
      data: {
        graph_json: grafoMpc(ambiente.tags["sine"], {
          mvZero: 20,
          mvSpan: 50,
          cvZero: 10,
          cvSpan: 40,
        }),
      },
    });
    if (!salvo.ok()) throw new Error(`salvar grafo: HTTP ${salvo.status()} — ${await salvo.text()}`);

    try {
      await page.goto(`/operacao/${String(id)}/${BLOCK_ID}`);
      await expect(page.getByTestId("operate-page")).toBeVisible();
      await expect(page.getByTestId("faceplate-escala-mv_1-topo")).toHaveText("70.00");
      await expect(page.getByTestId("faceplate-escala-mv_1-base")).toHaveText("20.00");
      await expect(page.getByTestId("faceplate-escala-cv_1-topo")).toHaveText("50.00");
      await expect(page.getByTestId("faceplate-escala-cv_1-base")).toHaveText("10.00");
    } finally {
      // Sem deploy neste flow: apagar direto não esbarra no 409 de flow rodando.
      await ambiente.api.delete(`/api/flows/${String(id)}`);
    }
  });
});
