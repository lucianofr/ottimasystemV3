import { expect, test, type APIRequestContext } from "@playwright/test";

import { adminApi, entrarNoShell, RUN_ID } from "./fixtures";

/**
 * PW-FL-05 — a paleta de blocos não pode extrapolar a moldura do editor: a lista ganha
 * barra de rolagem própria quando o conteúdo é mais alto que o quadro (regressão: com
 * 13 blocos o Card crescia além do contêiner flex e os últimos itens ficavam
 * inalcançáveis, sem scroll).
 *
 * Não precisa do opcsim: a paleta é estática — basta projeto + flow parado (modo default
 * do editor é "edit", `FlowEditorPage.tsx:349`).
 */

interface RecursoCriado {
  readonly id: number;
}

let api: APIRequestContext;
let projectId: number;
let flowId: number;

test.beforeAll(async ({ baseURL }) => {
  api = await adminApi(baseURL!);
  const projeto = await api.post("/api/projects", { data: { name: `E2E paleta ${RUN_ID}` } });
  if (!projeto.ok()) throw new Error(`criação do projeto: HTTP ${projeto.status()}`);
  projectId = ((await projeto.json()) as RecursoCriado).id;

  const flow = await api.post("/api/flows", {
    data: { project_id: projectId, name: `Paleta Scroll ${RUN_ID}`, ts_seconds: 1 },
  });
  if (!flow.ok()) throw new Error(`criação do flow: HTTP ${flow.status()}`);
  flowId = ((await flow.json()) as RecursoCriado).id;
});

test.afterAll(async () => {
  await api.delete(`/api/flows/${String(flowId)}`);
  await api.delete(`/api/projects/${String(projectId)}`);
  await api.dispose();
});

test("PW-FL-05: paleta cabe na moldura e a lista rola até o último bloco", async ({ page }) => {
  // Viewport curto: o transbordo dos 14 blocos fica garantido por construção,
  // não herdado do viewport 1920x1080 do config.
  await page.setViewportSize({ width: 1280, height: 640 });
  await entrarNoShell(page);
  await page.goto(`/engenharia/flows/${String(flowId)}`);

  const primeiro = page.getByTestId("paleta-opc_read");
  await expect(primeiro).toBeVisible();

  const card = page.getByTestId("paleta");
  const lista = page.getByTestId("paleta-lista");

  // 1) A lista tem scroll próprio e conteúdo de fato além da área visível.
  const rolagem = await lista.evaluate((el) => ({
    overflowY: getComputedStyle(el).overflowY,
    transborda: el.scrollHeight > el.clientHeight,
  }));
  expect(rolagem.overflowY, "lista da paleta sem scroll vertical").toMatch(/^(auto|scroll)$/);
  expect(rolagem.transborda, "lista deveria ter conteúdo além da área visível").toBe(true);

  // 2) Rolando até o fim, o último bloco fica alcançável DENTRO da caixa da paleta —
  //    o defeito desenhava os últimos itens fora da borda do Card, sem scroll.
  const ultimo = page.getByTestId("paleta-integrator");
  await ultimo.scrollIntoViewIfNeeded();
  await expect(ultimo).toBeInViewport();

  const cb = await card.boundingBox();
  const ub = await ultimo.boundingBox();
  expect(cb, "paleta sem bounding box").toBeTruthy();
  expect(ub, "último bloco sem bounding box").toBeTruthy();
  expect(ub!.y + ub!.height, "último bloco fora da caixa da paleta").toBeLessThanOrEqual(
    cb!.y + cb!.height + 1,
  );

  // 3) O último bloco é utilizável: o clique insere o bloco no canvas.
  await ultimo.click();
  await expect(page.locator(".react-flow__node")).toHaveCount(1);
});
