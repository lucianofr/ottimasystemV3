import { expect, test } from "@playwright/test";

import { criarAmbiente, entrarNoShell, NODES, type AmbienteE2E } from "./fixtures";

/**
 * PW-OP-05 — seletor de MPC na tela de Operação: um flow pode ter mais de um bloco `mpc`
 * (pedido do usuário — "cada flow pode ter um ou mais blocos MPCs dentro"). A tela de um MPC
 * aberto (`/operacao/:flowId/:blockId`) ganha um combobox pra trocar de bloco sem voltar ao
 * seletor de `/operacao` — mesmo rótulo `"<flow> · <mpc>"` já usado lá (`rotuloMpc`).
 *
 * Grafo mínimo: 1 `opc_read` alimentando a CV de DOIS blocos `mpc` independentes (mesmo
 * padrão de bloco único de `operate-trend.spec.ts`, duplicado) — sem deploy, então nasce em
 * LOCAL e a projeção `/api/operate/mpcs` já inclui os dois blocos.
 */

let ambiente: AmbienteE2E;
let flowId: number;

const BLOCK_A = "mpc-a";
const BLOCK_B = "mpc-b";

function grafo(tagLeituraId: number) {
  function blocoMpc(id: string, nome: string, execOrder: number) {
    return {
      id,
      type: "mpc",
      position: { x: 0, y: 0 },
      data: {
        exec_order: execOrder,
        name: nome,
        multiplier: 2,
        variables: {
          mvs: [
            {
              id: "mv_1",
              name: "Abertura",
              eu: "%",
              limits: { min: 0, max: 100 },
              max_rate: 2.5, // EU/s (ts_mpc=2 s -> 5 EU/ciclo, como antes)
              initial_value: 0,
            },
          ],
          cvs: [
            {
              id: "cv_1",
              name: "Nivel",
              eu: "%",
              kind: "selfreg",
              tss: 10,
              weight: 1,
              sp_limits: { min: 0, max: 100 },
            },
          ],
          constraints: [],
          dvs: [],
        },
        models: { cv_1: { mv_1: { enabled: true, params: { K: 1, tau1: 2, tau2: 0.5, theta: 0 } } } },
      },
    };
  }

  return {
    nodes: [
      {
        id: "leitura",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 1, tag_id: tagLeituraId },
      },
      blocoMpc(BLOCK_A, "MPC Alpha", 2),
      blocoMpc(BLOCK_B, "MPC Beta", 3),
    ],
    edges: [
      { id: "e1", source: "leitura", sourceHandle: "out", target: BLOCK_A, targetHandle: "cv_1" },
      { id: "e2", source: "leitura", sourceHandle: "out", target: BLOCK_B, targetHandle: "cv_1" },
    ],
  };
}

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "operate-mpc-select",
    tags: [{ chave: "sine", nodeId: NODES.sine, direcao: "r" }],
  });

  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: "Flow 2 MPCs E2E", ts_seconds: 1 },
  });
  if (!criado.ok()) throw new Error(`criação do flow: HTTP ${criado.status()}`);
  const corpo = (await criado.json()) as { id: number };
  flowId = corpo.id;

  const salvo = await ambiente.api.put(`/api/flows/${String(flowId)}`, {
    data: { graph_json: grafo(ambiente.tags["sine"]) },
  });
  if (!salvo.ok()) {
    throw new Error(`salvar grafo do flow: HTTP ${salvo.status()} — ${await salvo.text()}`);
  }
});

test.afterAll(async () => {
  // Sem deploy nesta suíte: nunca chega a "running", então apagar direto não esbarra no 409
  // de flow rodando (mesmo contrato de `operate-trend.spec.ts`).
  await ambiente.api.delete(`/api/flows/${String(flowId)}`);
  await ambiente.encerrar();
});

test.beforeEach(async ({ page }) => {
  await entrarNoShell(page);
  await page.goto(`/operacao/${String(flowId)}/${BLOCK_A}`);
  await expect(page.getByTestId("operate-page")).toBeVisible();
});

test.describe("Seletor de MPC na tela de Operação", () => {
  test("PW-OP-05: lista os MPCs do flow e troca ao selecionar, sem passar pelo seletor", async ({
    page,
  }) => {
    const seletor = page.getByTestId("operate-mpc-select");
    await expect(seletor).toBeVisible();
    await expect(page.getByTestId("faceplate-plaqueta")).toContainText("MPC Alpha");

    const opcoes = seletor.locator("option");
    await expect(opcoes).toHaveCount(2);
    await expect(opcoes.nth(0)).toHaveText(/MPC Alpha/);
    await expect(opcoes.nth(1)).toHaveText(/MPC Beta/);

    await seletor.selectOption({ index: 1 });
    await expect(page).toHaveURL(new RegExp(`/operacao/${String(flowId)}/${BLOCK_B}$`));
    await expect(page.getByTestId("faceplate-plaqueta")).toContainText("MPC Beta");
    await expect(seletor).toHaveValue("1");

    await seletor.selectOption({ index: 0 });
    await expect(page).toHaveURL(new RegExp(`/operacao/${String(flowId)}/${BLOCK_A}$`));
    await expect(page.getByTestId("faceplate-plaqueta")).toContainText("MPC Alpha");
  });
});
