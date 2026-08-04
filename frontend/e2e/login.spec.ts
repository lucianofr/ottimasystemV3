import { expect, test } from "@playwright/test";

import { ADMIN, ensureOperator, fazerLogin, OPERATOR } from "./fixtures";

test.describe("Login e sessão", () => {
  test("E2E-05: admin entra e vê o shell", async ({ page }) => {
    await fazerLogin(page, ADMIN.username, ADMIN.password);
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId("current-user")).toContainText("admin");
  });

  test("E2E-06: credencial errada mostra erro pt-BR e não navega", async ({ page }) => {
    await fazerLogin(page, ADMIN.username, "senha-errada-x1");
    await expect(page.getByTestId("login-error")).toContainText("Usuário ou senha inválidos");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("E2E-07: rota protegida sem sessão redireciona para /login", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("E2E-08: sessão sobrevive a reload (token + /auth/me)", async ({ page }) => {
    await fazerLogin(page, ADMIN.username, ADMIN.password);
    await expect(page).toHaveURL(/\/$/);
    await page.reload();
    await expect(page.getByTestId("current-user")).toContainText("admin");
  });

  test("E2E-09: sair encerra a sessão", async ({ page }) => {
    await fazerLogin(page, ADMIN.username, ADMIN.password);
    await expect(page).toHaveURL(/\/$/);
    await page.getByTestId("logout").click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/); // token limpo
  });

  test("E2E-10: operador criado via API entra pela UI", async ({ page, baseURL }) => {
    await ensureOperator(baseURL!);
    await fazerLogin(page, OPERATOR.username, OPERATOR.password);
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId("current-user")).toContainText("operador");
  });
});
