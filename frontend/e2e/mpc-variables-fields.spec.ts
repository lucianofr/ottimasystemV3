import { expect, test, type Page } from "@playwright/test";

import { criarAmbiente, entrarNoShell, NODES, type AmbienteE2E } from "./fixtures";

/**
 * PW-VF-01..08 — campos novos do modal MPC (RF-609..615): zero/span nos 4 tipos,
 * description ≤14, trajetória τ / track SP / prioridade / faixa do SP / SP remoto na CV,
 * max_rate no lugar de du_max na MV, fail actions com timeout condicional e modo local no
 * shed — com round-trip de persistência.
 *
 * Grafo seed no padrão de `mpc-objective.spec.ts`: 2 `opc_read` (sine) alimentando CV e
 * Restrição de 1 bloco `mpc` com 1 MV direta. Sem deploy. O select de SP remoto precisa de
 * uma tag W além das R para provar o filtro por direção.
 */

let ambiente: AmbienteE2E;
let flowId: number;

const BLOCK_ID = "mpc1";
const PUT_FLOW = (id: number) => `/api/flows/${String(id)}`;

function grafo(tagR: number, tagW: number) {
  return {
    nodes: [
      {
        id: "leitura",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 1, tag_id: tagR },
      },
      {
        id: "leitura2",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 2, tag_id: tagR },
      },
      {
        id: "leitura3",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 3, tag_id: tagR },
      },
      {
        id: "escrita",
        type: "opc_write",
        position: { x: 0, y: 0 },
        data: { exec_order: 4, tag_id: tagW },
      },
      {
        id: BLOCK_ID,
        type: "mpc",
        position: { x: 0, y: 0 },
        data: {
          exec_order: 5,
          name: "MPC campos",
          multiplier: 2,
          variables: {
            mvs: [
              {
                id: "mv_1",
                name: "Abertura",
                eu: "%",
                limits: { min: 0, max: 100 },
                max_rate: 2.5,
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
            constraints: [
              {
                id: "co_1",
                name: "Pressao",
                eu: "bar",
                kind: "selfreg",
                tss: 10,
                range: { low: 0, high: 10 },
                priority: 1,
              },
            ],
            dvs: [{ id: "dv_1", name: "Carga", eu: "m3/h" }],
          },
          models: {
            cv_1: {
              mv_1: { enabled: true, params: { K: 1, tau1: 2, tau2: 0.5, theta: 0 } },
              dv_1: { enabled: true, params: { K: 0.1, tau1: 2, tau2: 0.5, theta: 0 } },
            },
            co_1: { mv_1: { enabled: true, params: { K: 1, tau1: 2, tau2: 0.5, theta: 0 } } },
          },
        },
      },
    ],
    edges: [
      { id: "e1", source: "leitura", sourceHandle: "out", target: BLOCK_ID, targetHandle: "cv_1" },
      { id: "e2", source: "leitura2", sourceHandle: "out", target: BLOCK_ID, targetHandle: "co_1" },
      { id: "e4", source: "leitura3", sourceHandle: "out", target: BLOCK_ID, targetHandle: "dv_1" },
      { id: "e3", source: BLOCK_ID, sourceHandle: "mv_1", target: "escrita", targetHandle: "in" },
    ],
  };
}

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "mpc-campos",
    tags: [
      { chave: "sine", nodeId: NODES.sine, direcao: "r" },
      { chave: "escrita", nodeId: NODES.wFloat, direcao: "w" },
    ],
  });
  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: "Flow campos MPC E2E", ts_seconds: 1 },
  });
  if (!criado.ok()) throw new Error(`criação do flow: HTTP ${criado.status()}`);
  flowId = ((await criado.json()) as { id: number }).id;
  const salvo = await ambiente.api.put(PUT_FLOW(flowId), {
    data: { graph_json: grafo(ambiente.tags["sine"], ambiente.tags["escrita"]) },
  });
  if (!salvo.ok()) throw new Error(`salvar grafo: HTTP ${salvo.status()} — ${await salvo.text()}`);
});

test.afterAll(async () => {
  await ambiente.api.delete(PUT_FLOW(flowId));
  await ambiente.encerrar();
});

test.beforeEach(async ({ page }) => {
  await entrarNoShell(page);
});

/** Abre o modal do bloco na aba Variáveis e expande as seções Avançado das 4 linhas. */
async function abrirModal(page: Page): Promise<void> {
  await page.goto(`/engenharia/flows/${String(flowId)}`);
  await page.getByTestId(`rf__node-${BLOCK_ID}`).dblclick();
  await expect(page.getByTestId("mpc-modal")).toBeVisible();
  await page.getByTestId("mpc-tab-variaveis").click();
}

async function abrirAvancado(page: Page, varId: string): Promise<void> {
  await page.locator(`[data-testid="mpc-var-row-${varId}"] summary`).click();
}

test.describe("Campos novos do modal MPC", () => {
  test("PW-VF-01: zero/span presentes nos 4 tipos com defaults 0/100", async ({ page }) => {
    await abrirModal(page);
    for (const prefixo of ["mpc-mv", "mpc-cv", "mpc-restricao", "mpc-dv"]) {
      await expect(page.getByTestId(`${prefixo}-zero`)).toHaveValue("0");
      await expect(page.getByTestId(`${prefixo}-span`)).toHaveValue("100");
    }
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-VF-02: span 0 ou negativo bloqueia o Aplicar; PUT direto leva 422", async ({
    page,
  }) => {
    await abrirModal(page);
    await page.getByTestId("mpc-cv-span").fill("0");
    await page.getByTestId("config-aplicar").click();

    // O aplicar navega para o Resumo em erro (nunca clicar mpc-tab-resumo — testid colide).
    await expect(page.getByTestId("mpc-modal")).toBeVisible();
    await expect(page.getByTestId("mpc-resumo-erros")).toContainText("span maior que zero");

    // Espelho REST (PW-MO-05): span 0 no config direto leva 422 do Pydantic.
    const invalido = grafo(ambiente.tags["sine"], ambiente.tags["escrita"]);
    const bloco = invalido.nodes.find((no) => no.id === BLOCK_ID);
    if (bloco === undefined) throw new Error("nó mpc1 ausente no grafo de teste");
    const dados = bloco.data as { variables: { cvs: Record<string, unknown>[] } };
    dados.variables.cvs[0] = { ...dados.variables.cvs[0], span: 0 };
    const resposta = await ambiente.api.put(PUT_FLOW(flowId), {
      data: { graph_json: invalido },
    });
    expect(resposta.status()).toBe(422);
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-VF-03: description com maxlength 14, trajetória τ e track SP default ligado", async ({
    page,
  }) => {
    await abrirModal(page);
    const descricao = page.getByTestId("mpc-cv-description");
    await expect(descricao).toHaveAttribute("maxlength", "14");
    await descricao.fill("123456789012345678901234567"); // 27 chars
    await expect(descricao).toHaveValue("12345678901234"); // trunca em 14

    await expect(page.getByTestId("mpc-cv-traj-tau")).toHaveValue("0");
    await expect(page.getByTestId("mpc-cv-track-sp")).toBeChecked();
    await expect(page.getByTestId("mpc-cv-priority")).toHaveValue("1");
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-VF-04: CV avançado — 5 ações de falha, timeout condicional, faixa do SP e SP remoto só R", async ({
    page,
  }) => {
    await abrirModal(page);
    await abrirAvancado(page, "cv_1");

    const acao = page.getByTestId("mpc-cv-fail-action");
    await expect(acao.locator("option")).toHaveText([
      "Sem ação",
      "Shed p/ local",
      "Manual",
      "Simular→Manual",
      "Simular→Local",
    ]);
    await expect(acao).toHaveValue("no_action");
    await expect(page.getByTestId("mpc-cv-fail-timeout")).toHaveCount(0);

    await acao.selectOption("simulate_manual");
    await expect(page.getByTestId("mpc-cv-fail-timeout")).toBeVisible();
    await expect(page.getByTestId("mpc-cv-fail-timeout")).toHaveValue("60");

    await expect(page.getByTestId("mpc-cv-sp-range-pct")).toHaveValue("");

    const spRemoto = page.getByTestId("mpc-cv-remote-sp-tag");
    const opcoes = await spRemoto.locator("option").allTextContents();
    // 1 placeholder + a tag R (sine); a tag W (escrita) NÃO pode aparecer.
    expect(opcoes).toHaveLength(2);
    expect(opcoes.join()).toContain("sine");
    expect(opcoes.join()).not.toContain("escrita");
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-VF-05: MV — du_max sumiu, max_rate presente, 3 ações, modo local no shed condicional", async ({
    page,
  }) => {
    await abrirModal(page);
    await expect(page.getByTestId("mpc-mv-du-max")).toHaveCount(0);
    await expect(page.getByTestId("mpc-mv-max-rate")).toHaveValue("2.5");

    await abrirAvancado(page, "mv_1");
    const acao = page.getByTestId("mpc-mv-fail-action");
    await expect(acao.locator("option")).toHaveText(["Sem ação", "Shed p/ local", "Manual"]);
    await expect(page.getByTestId("mpc-mv-local-shed-mode")).toHaveCount(0);

    // MV sem PID: o campo aparece com shed_local, mas desabilitado (servidor: 422).
    await acao.selectOption("shed_local");
    const shed = page.getByTestId("mpc-mv-local-shed-mode");
    await expect(shed).toBeVisible();
    await expect(shed).toBeDisabled();
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-VF-06: Restrição — avançado com ação de falha e timeout condicional", async ({
    page,
  }) => {
    await abrirModal(page);
    await abrirAvancado(page, "co_1");
    const acao = page.getByTestId("mpc-restricao-fail-action");
    await expect(acao.locator("option")).toHaveText([
      "Sem ação",
      "Shed p/ local",
      "Manual",
      "Simular→Manual",
      "Simular→Local",
    ]);
    await expect(page.getByTestId("mpc-restricao-fail-timeout")).toHaveCount(0);
    await acao.selectOption("manual");
    await expect(page.getByTestId("mpc-restricao-fail-timeout")).toBeVisible();
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-VF-07: DV tem zero/span e NÃO tem description nem fail action", async ({ page }) => {
    await abrirModal(page);
    await expect(page.getByTestId("mpc-dv-zero")).toHaveValue("0");
    await expect(page.getByTestId("mpc-dv-span")).toHaveValue("100");
    await expect(page.getByTestId("mpc-dv-description")).toHaveCount(0);
    await expect(page.getByTestId("mpc-dv-fail-action")).toHaveCount(0);
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-VF-08: round-trip — campos novos sobrevivem a salvar e recarregar", async ({
    page,
  }) => {
    await abrirModal(page);
    await page.getByTestId("mpc-mv-zero").fill("20");
    await page.getByTestId("mpc-mv-span").fill("50");
    await page.getByTestId("mpc-mv-description").fill("aquecedor");
    await page.getByTestId("mpc-cv-traj-tau").fill("30");
    await page.getByTestId("mpc-cv-track-sp").uncheck();

    await abrirAvancado(page, "cv_1");
    await page.getByTestId("mpc-cv-fail-action").selectOption("simulate_shed_local");
    await page.getByTestId("mpc-cv-fail-timeout").fill("90");
    await page.getByTestId("mpc-cv-sp-range-pct").fill("10");

    await page.getByTestId("config-aplicar").click();
    await expect(page.getByTestId("mpc-modal")).toBeHidden();
    const salvamento = page.waitForResponse(
      (resposta) => resposta.url().includes(PUT_FLOW(flowId)) && resposta.request().method() === "PUT",
    );
    await page.getByTestId("flow-salvar").click();
    expect((await salvamento).status()).toBe(200);

    await page.reload();
    await page.getByTestId(`rf__node-${BLOCK_ID}`).dblclick();
    await expect(page.getByTestId("mpc-modal")).toBeVisible();
    await page.getByTestId("mpc-tab-variaveis").click();

    await expect(page.getByTestId("mpc-mv-zero")).toHaveValue("20");
    await expect(page.getByTestId("mpc-mv-span")).toHaveValue("50");
    await expect(page.getByTestId("mpc-mv-description")).toHaveValue("aquecedor");
    await expect(page.getByTestId("mpc-cv-traj-tau")).toHaveValue("30");
    await expect(page.getByTestId("mpc-cv-track-sp")).not.toBeChecked();
    await abrirAvancado(page, "cv_1");
    await expect(page.getByTestId("mpc-cv-fail-action")).toHaveValue("simulate_shed_local");
    await expect(page.getByTestId("mpc-cv-fail-timeout")).toHaveValue("90");
    await expect(page.getByTestId("mpc-cv-sp-range-pct")).toHaveValue("10");
    await page.getByTestId("config-cancelar").click();
  });
});
