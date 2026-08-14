import { expect, test, type Page } from "@playwright/test";

import { criarAmbiente, entrarNoShell, NODES, type AmbienteE2E } from "./fixtures";

/**
 * PW-WD-01..04 — timeout do watchdog configurável por flow (RF-206 revisado): o campo
 * `watchdog_timeout_s` (2–120 s, default 10, ≥ 2× o período) nas propriedades do flow, com
 * a regra de 2× no espelho client-side e no servidor, persistência e a fronteira exata.
 *
 * Sem deploy: as propriedades são gravadas por PUT, sem flow rodando. O grafo é vazio — o
 * modal de propriedades não toca o desenho.
 */

let ambiente: AmbienteE2E;
let flowId: number;

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "wd-timeout",
    tags: [
      { chave: "wdFrom", nodeId: NODES.wdFrom, direcao: "r", tipo: "bool" },
      { chave: "wdTo", nodeId: NODES.wdTo, direcao: "w", tipo: "bool" },
    ],
  });
  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: "Flow watchdog timeout E2E", ts_seconds: 1 },
  });
  if (!criado.ok()) throw new Error(`criação do flow: HTTP ${criado.status()}`);
  flowId = ((await criado.json()) as { id: number }).id;
  const configurado = await ambiente.api.put(`/api/flows/${String(flowId)}`, {
    data: {
      watchdog_enabled: true,
      watchdog_connection_id: ambiente.connId,
      watchdog_read_node_id: NODES.wdFrom,
      watchdog_write_node_id: NODES.wdTo,
      watchdog_period_ms: 1000,
    },
  });
  if (!configurado.ok()) {
    throw new Error(`configurar watchdog: HTTP ${configurado.status()} — ${await configurado.text()}`);
  }
});

test.afterAll(async () => {
  await ambiente.api.delete(`/api/flows/${String(flowId)}`);
  await ambiente.encerrar();
});

async function abrirPropriedades(page: Page): Promise<void> {
  await entrarNoShell(page);
  await page.goto(`/engenharia/flows/${String(flowId)}`);
  await page.getByTestId("flow-props-abrir").click();
  await expect(page.getByTestId("flow-props-modal")).toBeVisible();
}

test.describe("Timeout do watchdog por flow", () => {
  test("PW-WD-01: campo visível só com watchdog ligado, default 10, min 2, max 120", async ({
    page,
  }) => {
    await abrirPropriedades(page);
    const campo = page.getByTestId("flow-props-wd-timeout");
    await expect(page.getByTestId("flow-props-wd-enabled")).toBeChecked();
    await expect(campo).toBeVisible();
    await expect(campo).toHaveValue("10");
    await expect(campo).toHaveAttribute("min", "2");
    await expect(campo).toHaveAttribute("max", "120");

    await page.getByTestId("flow-props-wd-enabled").uncheck();
    await expect(page.getByTestId("flow-props-wd-timeout")).toHaveCount(0);
    await page.getByTestId("flow-props-wd-enabled").check();
    await expect(campo).toBeVisible();
    await page.getByTestId("flow-props-fechar").click();
  });

  test("PW-WD-02: timeout < 2× período bloqueia no espelho e no servidor (422/400)", async ({
    page,
  }) => {
    // Com período 1000 ms a regra 2× é inalcançável na UI (qualquer timeout ≥ 2 s passa):
    // sobe o período para 5000 ms (2× = 10 s) e tenta 5 s — passa no min/max do input e
    // cai na regra de domínio do espelho client-side.
    await abrirPropriedades(page);
    await page.getByTestId("flow-props-wd-period").fill("5000");
    await page.getByTestId("flow-props-wd-timeout").fill("5");
    await page.getByTestId("flow-props-aplicar").click();

    // Modal permanece aberto com a mensagem pt-BR da regra.
    await expect(page.getByTestId("flow-props-modal")).toBeVisible();
    await expect(page.getByTestId("flow-props-erro")).toHaveText(
      "timeout do watchdog deve ser ao menos 2x o período",
    );
    await page.getByTestId("flow-props-fechar").click();

    // Espelho REST: fora de 2–120 o Pydantic responde 422 sem nem chegar à regra.
    const invalido = await ambiente.api.put(`/api/flows/${String(flowId)}`, {
      data: { watchdog_timeout_s: 1 },
    });
    expect(invalido.status()).toBe(422);
    // Regra de domínio (400): período 5000 ms ⇒ 2× = 10 s; timeout 5 s é reprovado com a
    // mensagem pt-BR. Depois o período volta a 1000 ms para os demais testes.
    const periodo = await ambiente.api.put(`/api/flows/${String(flowId)}`, {
      data: { watchdog_period_ms: 5000, watchdog_timeout_s: 10 },
    });
    expect(periodo.status()).toBe(200);
    const curto = await ambiente.api.put(`/api/flows/${String(flowId)}`, {
      data: { watchdog_timeout_s: 5 },
    });
    expect(curto.status()).toBe(422);
    expect(await curto.text()).toContain("timeout do watchdog deve ser ao menos 2x o período");
    await ambiente.api.put(`/api/flows/${String(flowId)}`, { data: { watchdog_period_ms: 1000 } });
  });

  test("PW-WD-03: timeout 20 salva e persiste após reload", async ({ page }) => {
    await abrirPropriedades(page);
    await page.getByTestId("flow-props-wd-timeout").fill("20");
    await page.getByTestId("flow-props-aplicar").click();
    await expect(page.getByTestId("flow-props-modal")).toBeHidden();

    const detalhe = await ambiente.api.get(`/api/flows/${String(flowId)}`);
    const corpo = (await detalhe.json()) as { watchdog_timeout_s: number };
    expect(corpo.watchdog_timeout_s).toBe(20);

    await page.reload();
    await page.getByTestId("flow-props-abrir").click();
    await expect(page.getByTestId("flow-props-wd-timeout")).toHaveValue("20");
    await page.getByTestId("flow-props-fechar").click();
  });

  test("PW-WD-04: fronteira exata (timeout = 2× período) é aceita", async ({ page }) => {
    await abrirPropriedades(page);
    await page.getByTestId("flow-props-wd-timeout").fill("2");
    await page.getByTestId("flow-props-aplicar").click();
    await expect(page.getByTestId("flow-props-modal")).toBeHidden();

    const detalhe = await ambiente.api.get(`/api/flows/${String(flowId)}`);
    const corpo = (await detalhe.json()) as { watchdog_timeout_s: number };
    expect(corpo.watchdog_timeout_s).toBe(2);

    // Restaura o default para não deixar a fronteira gravada para outros cenários.
    await ambiente.api.put(`/api/flows/${String(flowId)}`, { data: { watchdog_timeout_s: 10 } });
  });
});
