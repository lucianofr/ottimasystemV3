import { type APIRequestContext, expect, test } from "@playwright/test";

import { ADMIN, adminApi, fazerLogin, RUN_ID } from "./fixtures";

type Projeto = { id: number; name: string; is_active: boolean };

/** A API não expõe "desativar" (só `activate`) e excluir o ativo dá 409: para devolver o sistema
 * ao estado inicial quando não havia projeto ativo, o E2E-16 reativa esta sentinela estável em vez
 * de deixar um projeto descartável novo a cada execução. Mesmo nome usado no L2 (tests/e2e). */
const SENTINELA = "E2E sentinela (não excluir)";

async function listarProjetos(api: APIRequestContext): Promise<Projeto[]> {
  const res = await api.get("/api/projects");
  expect(res.status(), "listagem de projetos").toBe(200);
  return (await res.json()) as Projeto[];
}

async function garantirSentinela(api: APIRequestContext): Promise<Projeto> {
  const res = await api.post("/api/projects", { data: { name: SENTINELA } });
  if (res.ok()) return (await res.json()) as Projeto;
  if (res.status() !== 409) throw new Error(`criação da sentinela falhou: HTTP ${res.status()}`);
  const existente = (await listarProjetos(api)).find((p) => p.name === SENTINELA);
  if (!existente) throw new Error("sentinela reportada como duplicada mas ausente na listagem");
  return existente;
}

test.describe("Shell autenticado", () => {
  test("E2E-17: faixa anunciadora colapsada presente", async ({ page }) => {
    await fazerLogin(page, ADMIN.username, ADMIN.password);
    await expect(page.getByTestId("annunciator")).toContainText("Sem alarmes ativos");
  });

  test("E2E-16: projeto ativado via API aparece como projeto ativo", async ({ page, baseURL }) => {
    const api = await adminApi(baseURL!);
    const anterior = (await listarProjetos(api)).find((p) => p.is_active) ?? null;
    const nome = `Planta E2E ${RUN_ID}`;
    const criado = (await (await api.post("/api/projects", { data: { name: nome } })).json()) as {
      id: number;
    };
    try {
      expect((await api.post(`/api/projects/${criado.id}/activate`)).status()).toBe(200);

      await fazerLogin(page, ADMIN.username, ADMIN.password);
      await expect(page.getByTestId("active-project")).toHaveText(nome);
    } finally {
      // Estado ao fim == estado inicial: reativa o projeto anterior (ou a sentinela, se não havia
      // nenhum ativo) e só então exclui o projeto desta execução.
      const restaurar = anterior ?? (await garantirSentinela(api));
      expect((await api.post(`/api/projects/${restaurar.id}/activate`)).status()).toBe(200);
      expect((await api.delete(`/api/projects/${criado.id}`)).status()).toBe(204);
      await api.dispose();
    }
  });
});
