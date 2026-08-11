import { expect, test, type Page } from "@playwright/test";

import { criarAmbiente, entrarNoShell, NODES, RUN_ID, type AmbienteE2E } from "./fixtures";

/**
 * PW-FT-01 — blocos de filtro no editor (ADR-026/TD-012): configurar `first_order` (`tau`)
 * e `kalman` (`measurement_noise`/`process_noise`) pelo modal e confirmar que o Save persiste
 * os dois valores, round-trip via reload.
 *
 * Arquivo próprio, e não mais um `test(...)` em `flows-editor.spec.ts`: mesmo critério do
 * `filtros.check.ts` (separado de `graph.check.ts` no próprio cabeçalho) — assunto isolado
 * dos dois blocos de filtro, sem crescer um arquivo que já cobre outra fatia do editor
 * (modo EDIT/ONLINE, propriedades do flow, diálogo de impacto do MPC, Deploy).
 *
 * `tau` novo fica bem acima de `Ts/DIRECT_PASS_RATIO` (Ts=1s aqui, limiar=0,1s — TD-011):
 * o cenário é sobre o round-trip da config, não sobre o rótulo de borda "passagem direta".
 */

interface FlowIdOut {
  readonly id: number;
}

interface FlowGraphOut {
  readonly graph_json: {
    readonly nodes: readonly { readonly id: string; readonly data: Record<string, unknown> }[];
  };
}

let ambiente: AmbienteE2E;
let flowId: number;

const TAU_INICIAL = 0.5;
const TAU_NOVO = 8;
const MEASUREMENT_NOISE_INICIAL = 1;
const MEASUREMENT_NOISE_NOVO = 4.5;
const PROCESS_NOISE_INICIAL = 0.1;
const PROCESS_NOISE_NOVO = 0.75;

function grafoFiltros(tagLeitura: number, tagEscrita: number): unknown {
  return {
    nodes: [
      {
        id: "leitura",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 1, label: "", tag_id: tagLeitura },
      },
      {
        id: "fo",
        type: "first_order",
        position: { x: 320, y: 0 },
        data: { exec_order: 2, label: "", tau: TAU_INICIAL },
      },
      {
        id: "kf",
        type: "kalman",
        position: { x: 640, y: 0 },
        data: {
          exec_order: 3,
          label: "",
          measurement_noise: MEASUREMENT_NOISE_INICIAL,
          process_noise: PROCESS_NOISE_INICIAL,
        },
      },
      {
        id: "escrita",
        type: "opc_write",
        position: { x: 960, y: 0 },
        data: { exec_order: 4, label: "", tag_id: tagEscrita },
      },
    ],
    edges: [
      { id: "e1", source: "leitura", sourceHandle: "out", target: "fo", targetHandle: "in" },
      { id: "e2", source: "fo", sourceHandle: "out", target: "kf", targetHandle: "in" },
      { id: "e3", source: "kf", sourceHandle: "out", target: "escrita", targetHandle: "in" },
    ],
  };
}

async function configurarBloco(
  page: Page,
  testidNo: string,
  preencher: () => Promise<void>,
): Promise<void> {
  await page.getByTestId(testidNo).dblclick();
  await expect(page.getByTestId("config-modal")).toBeVisible();
  await preencher();
  await page.getByTestId("config-aplicar").click();
  await expect(page.getByTestId("config-modal")).toBeHidden();
}

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "filtros",
    tags: [
      { chave: "r", nodeId: NODES.sine, direcao: "r" },
      { chave: "w", nodeId: NODES.wFloat, direcao: "w" },
    ],
  });
  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: `Editor Filtros ${RUN_ID}`, ts_seconds: 1 },
  });
  if (!criado.ok()) throw new Error(`criação do flow: HTTP ${criado.status()}`);
  const corpo: FlowIdOut = await criado.json();
  flowId = corpo.id;

  const salvo = await ambiente.api.put(`/api/flows/${String(flowId)}`, {
    data: { graph_json: grafoFiltros(ambiente.tags["r"], ambiente.tags["w"]) },
  });
  if (!salvo.ok()) {
    throw new Error(`PUT do grafo do flow: HTTP ${salvo.status()} — ${await salvo.text()}`);
  }
  // Nunca deployado de propósito: sem status publicado, o editor abre em EDIT por padrão
  // (mesmo caminho do PW-FL-04) — paleta e Salvar já visíveis, sem trocar de modo antes.
});

test.afterAll(async () => {
  const excluido = await ambiente.api.delete(`/api/flows/${String(flowId)}`);
  if (excluido.status() !== 204) throw new Error(`exclusão do flow: HTTP ${excluido.status()}`);
  await ambiente.encerrar();
});

test.beforeEach(async ({ page }) => {
  await entrarNoShell(page);
});

test.describe("Blocos de filtro no editor", () => {
  test("PW-FT-01: configurar 1ª ordem e Kalman pelo modal persiste os dois pelo Save (round-trip)", async ({
    page,
  }) => {
    await page.goto(`/engenharia/flows/${String(flowId)}`);
    await expect(page.getByTestId("flow-salvar")).toBeVisible();

    await configurarBloco(page, "rf__node-fo", async () => {
      await page.getByTestId("config-tau").fill(String(TAU_NOVO));
    });
    await configurarBloco(page, "rf__node-kf", async () => {
      await page.getByTestId("config-measurement-noise").fill(String(MEASUREMENT_NOISE_NOVO));
      await page.getByTestId("config-process-noise").fill(String(PROCESS_NOISE_NOVO));
    });

    await page.getByTestId("flow-salvar").click();
    // A região de mensagens só aparece depois do 1º save bem-sucedido (mesmo sinal usado em
    // PW-FL-03) — dispensa esperar por tempo fixo.
    await expect(page.getByTestId("editor-mensagens")).toBeVisible({ timeout: 15_000 });

    // Round-trip: recarrega o editor do zero e reabre os dois modais — os valores têm de vir
    // do `graph_json` persistido pelo PUT do Save, não de estado do React sobrevivendo ao reload.
    await page.reload();
    await expect(page.getByTestId("flow-salvar")).toBeVisible();

    await page.getByTestId("rf__node-fo").dblclick();
    await expect(page.getByTestId("config-modal")).toBeVisible();
    await expect(page.getByTestId("config-tau")).toHaveValue(String(TAU_NOVO));
    await page.getByTestId("config-cancelar").click();
    await expect(page.getByTestId("config-modal")).toBeHidden();

    await page.getByTestId("rf__node-kf").dblclick();
    await expect(page.getByTestId("config-modal")).toBeVisible();
    await expect(page.getByTestId("config-measurement-noise")).toHaveValue(
      String(MEASUREMENT_NOISE_NOVO),
    );
    await expect(page.getByTestId("config-process-noise")).toHaveValue(String(PROCESS_NOISE_NOVO));
    await page.getByTestId("config-cancelar").click();
    await expect(page.getByTestId("config-modal")).toBeHidden();

    // Confere também contra a API: a fonte de verdade é o `graph_json` persistido, não só o
    // que o modal reabriu (que poderia estar lendo estado do React, não o servidor).
    const res = await ambiente.api.get(`/api/flows/${String(flowId)}`);
    const corpo: FlowGraphOut = await res.json();
    const fo = corpo.graph_json.nodes.find((no) => no.id === "fo");
    const kf = corpo.graph_json.nodes.find((no) => no.id === "kf");
    expect(fo?.data.tau).toBe(TAU_NOVO);
    expect(kf?.data.measurement_noise).toBe(MEASUREMENT_NOISE_NOVO);
    expect(kf?.data.process_noise).toBe(PROCESS_NOISE_NOVO);
  });
});
