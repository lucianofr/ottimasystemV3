import { type APIRequestContext, type Page, request } from "@playwright/test";

export const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? "admin",
  password: process.env.E2E_ADMIN_PASSWORD ?? "",
};

/** Operador de teste: nome fixo e recriação tolerante a 409 — o banco do stack é persistente. */
export const OPERATOR = { username: "operador-e2e", password: "operador-12345" };

/** Sufixo único por execução: nada criado por um run colide com o do run anterior. */
export const RUN_ID = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

export async function adminToken(baseURL: string): Promise<string> {
  const ctx = await request.newContext({ baseURL });
  const res = await ctx.post("/api/auth/login", {
    data: { username: ADMIN.username, password: ADMIN.password },
  });
  if (!res.ok()) throw new Error(`login do admin falhou: HTTP ${res.status()}`);
  const body = (await res.json()) as { access_token: string };
  await ctx.dispose();
  return body.access_token;
}

/** Contexto REST já autenticado como admin — quem chama é responsável pelo `dispose()`. */
export async function adminApi(baseURL: string): Promise<APIRequestContext> {
  const token = await adminToken(baseURL);
  return request.newContext({
    baseURL,
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  });
}

export async function ensureOperator(baseURL: string): Promise<void> {
  const ctx = await adminApi(baseURL);
  const res = await ctx.post("/api/users", {
    data: {
      username: OPERATOR.username,
      name: "Operador E2E",
      password: OPERATOR.password,
      role: "operator",
    },
  });
  if (!res.ok() && res.status() !== 409) {
    throw new Error(`criação do operador falhou: HTTP ${res.status()}`);
  }
  await ctx.dispose();
}

/** Login pela UI (o gate exige o caminho real do usuário, não injeção de token). */
export async function fazerLogin(page: Page, username: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-username").fill(username);
  await page.getByTestId("login-password").fill(password);
  await page.getByTestId("login-submit").click();
}
