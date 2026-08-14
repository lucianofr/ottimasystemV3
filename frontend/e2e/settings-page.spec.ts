import { expect, test } from "@playwright/test";

import { criarAmbiente, ensureOperator, entrarNoShell, OPERATOR, type AmbienteE2E } from "./fixtures";

/**
 * PW-CFG-01..06 — página Configurações (RF-805): retenções de variáveis (1–120 d) e de
 * eventos (1–90 d), nível de log dos serviços (PUT no onChange), e o RBAC (admin-only;
 * operador não vê o item de nav, é redirecionado pela rota e leva 403 no PUT direto).
 *
 * Os testes MUTAM configurações globais do stack e2e e restauram os defaults no `afterAll`
 * (30 dias / INFO) para não envenenar os specs seguintes — nunca descem a retenção abaixo
 * de 30 dias aqui (o `drop_chunks` imediato apagaria histórico compartilhado); a fronteira
 * de 3 dias com chunk antigo é coberta pelo pytest `test_settings_events_retention.py`,
 * que isola o próprio dado.
 */

let ambiente: AmbienteE2E;

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, { sufixo: "settings", tags: [] });
  await ensureOperator(baseURL!);
});

test.afterAll(async () => {
  // Restaura os defaults globais (30/30 dias, INFO) antes de soltar o stack.
  await ambiente.api.put("/api/history-retention", {
    data: { retention_days: 30, events_retention_days: 30 },
  });
  await ambiente.api.put("/api/system-settings", { data: { log_level: "INFO" } });
  await ambiente.encerrar();
});

test.describe("Página Configurações", () => {
  test("PW-CFG-01: admin vê o item de nav e a página com as três seções", async ({ page }) => {
    await entrarNoShell(page);
    await expect(page.getByTestId("nav-configuracoes")).toBeVisible();
    await page.getByTestId("nav-configuracoes").click();
    await expect(page).toHaveURL(/\/configuracoes$/);

    await expect(page.getByTestId("config-retencao-amostras")).toBeVisible();
    await expect(page.getByTestId("config-retencao-eventos")).toBeVisible();
    const logLevel = page.getByTestId("config-log-level");
    await expect(logLevel).toBeVisible();
    await expect(logLevel.locator("option")).toHaveText([
      "DEBUG",
      "INFO",
      "WARNING",
      "ERROR",
      "CRITICAL",
    ]);
    await expect(logLevel).toHaveValue("INFO");
  });

  test("PW-CFG-02: retenção de eventos salva, persiste e valida a faixa 1–90", async ({
    page,
  }) => {
    await entrarNoShell(page);
    await page.goto("/configuracoes");
    const campo = page.getByTestId("config-retencao-eventos");
    const salvar = page.getByTestId("config-retencao-eventos-salvar");
    await expect(campo).toBeVisible();

    // Fora da faixa: o botão desabilita no espelho client-side…
    await campo.fill("0");
    await expect(salvar).toBeDisabled();
    await campo.fill("91");
    await expect(salvar).toBeDisabled();
    // …e o PUT direto leva 422 (PW-MO-05: espelho REST de todo erro 4xx da UI).
    const invalido = await ambiente.api.put("/api/history-retention", {
      data: { events_retention_days: 91 },
    });
    expect(invalido.status()).toBe(422);

    const salvo = page.waitForResponse(
      (resposta) =>
        resposta.url().includes("/api/history-retention") &&
        resposta.request().method() === "PUT",
    );
    await campo.fill("45");
    await expect(salvar).toBeEnabled();
    await salvar.click();
    expect((await salvo).status()).toBe(200);

    await page.reload();
    await expect(page.getByTestId("config-retencao-eventos")).toHaveValue("45");
  });

  test("PW-CFG-03: retenção de amostras (movida do trend) salva e persiste", async ({
    page,
  }) => {
    await entrarNoShell(page);
    await page.goto("/configuracoes");
    const campo = page.getByTestId("config-retencao-amostras");
    const salvar = page.getByTestId("config-retencao-amostras-salvar");
    await expect(campo).toBeVisible();

    const salvo = page.waitForResponse(
      (resposta) =>
        resposta.url().includes("/api/history-retention") &&
        resposta.request().method() === "PUT",
    );
    await campo.fill("60");
    await salvar.click();
    expect((await salvo).status()).toBe(200);

    await page.reload();
    await expect(page.getByTestId("config-retencao-amostras")).toHaveValue("60");
  });

  test("PW-CFG-04: nível de log dispara o PUT no onChange (sem botão) e persiste", async ({
    page,
  }) => {
    await entrarNoShell(page);
    await page.goto("/configuracoes");
    const seletor = page.getByTestId("config-log-level");
    await expect(seletor).toHaveValue("INFO");

    const salvo = page.waitForResponse(
      (resposta) =>
        resposta.url().includes("/api/system-settings") &&
        resposta.request().method() === "PUT",
    );
    await seletor.selectOption("DEBUG");
    expect((await salvo).status()).toBe(200);

    await page.reload();
    await expect(page.getByTestId("config-log-level")).toHaveValue("DEBUG");

    const invalido = await ambiente.api.put("/api/system-settings", {
      data: { log_level: "TRACE" },
    });
    expect(invalido.status()).toBe(422);
  });

  test("PW-CFG-05: operador não vê o item, é redirecionado e leva 403 no PUT", async ({
    page,
  }) => {
    await entrarNoShell(page, OPERATOR.username, OPERATOR.password);
    await expect(page.getByTestId("nav-configuracoes")).toHaveCount(0);

    await page.goto("/configuracoes");
    await expect(page).toHaveURL(/\/$/);
  });

  test("PW-CFG-06: PUT com token de operador é 403 (espelho REST do RBAC)", async () => {
    const login = await ambiente.api.post("/api/auth/login", {
      data: { username: OPERATOR.username, password: OPERATOR.password },
    });
    const { access_token: token } = (await login.json()) as { access_token: string };

    const get = await ambiente.api.get("/api/system-settings", {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(get.status()).toBe(200);

    const put = await ambiente.api.put("/api/system-settings", {
      data: { log_level: "ERROR" },
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(put.status()).toBe(403);
  });
});
