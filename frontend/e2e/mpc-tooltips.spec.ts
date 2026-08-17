import { expect, test, type Page } from "@playwright/test";

import { criarAmbiente, entrarNoShell, NODES, type AmbienteE2E } from "./fixtures";

/**
 * PW-TT-01..05 — tooltip de ajuda (descrição + exemplo) nos campos do modal MPC.
 *
 * Cobre o mecanismo (hover mostra, sai fecha, foco por teclado mostra, Esc fecha só o
 * tooltip) e os 3 bugs achados/corrigidos na revisão desta tarefa — não o texto de cada uma
 * das ~50 entradas de `ajudaMpc.ts` (isso é conteúdo, não comportamento; mudaria a cada
 * ajuste de copy sem quebrar nada de fato). Grafo seed mínimo: 1 MV (só a suficiente pra
 * testar o checkbox "MV com PID"), sem CV/Restrição/DV — este spec não precisa deles.
 */

let ambiente: AmbienteE2E;
let flowId: number;

const BLOCK_ID = "mpc1";

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "tooltips",
    tags: [{ chave: "sine", nodeId: NODES.sine, direcao: "r" }],
  });
  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: "Flow tooltips MPC E2E", ts_seconds: 1 },
  });
  if (!criado.ok()) throw new Error(`criação do flow: HTTP ${criado.status()}`);
  const flowCriado = (await criado.json()) as { id: number };
  flowId = flowCriado.id;
  const grafo = {
    nodes: [
      {
        id: "leitura",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 1, tag_id: ambiente.tags["sine"] },
      },
      {
        id: BLOCK_ID,
        type: "mpc",
        position: { x: 0, y: 0 },
        data: {
          exec_order: 2,
          name: "",
          multiplier: 1,
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
            constraints: [],
            dvs: [],
          },
          models: {
            cv_1: { mv_1: { enabled: true, params: { K: 1, tau1: 2, tau2: 0.5, theta: 0 } } },
          },
        },
      },
    ],
    edges: [
      { id: "e1", source: "leitura", sourceHandle: "out", target: BLOCK_ID, targetHandle: "cv_1" },
    ],
  };
  const salvo = await ambiente.api.put(`/api/flows/${String(flowId)}`, { data: { graph_json: grafo } });
  if (!salvo.ok()) throw new Error(`salvar grafo: HTTP ${salvo.status()} — ${await salvo.text()}`);
});

test.afterAll(async () => {
  await ambiente.encerrar();
});

test.beforeEach(async ({ page }) => {
  await entrarNoShell(page);
});

/** Abre o modal e espera o estado inicial assentar (foco no Rótulo, nenhum tooltip aberto)
 *  antes de seguir — sem isso, o ciclo foco→blur→timer de 150 ms do tooltip do Rótulo
 *  (aberto e fechado de novo pelo StrictMode/dev) ainda pode estar pendente quando o teste
 *  interage com outro campo, deixando dois tooltips visíveis ao mesmo tempo (nunca
 *  acontece na prática: um usuário real leva bem mais que 150 ms entre abrir o modal e a
 *  próxima interação — só um teste automatizado interage rápido o bastante pra pegar essa
 *  janela). `toHaveCount(0)` faz Playwright esperar (com retry) o timer terminar, em vez de
 *  um `waitForTimeout` arbitrário. */
async function abrirModal(page: Page): Promise<void> {
  await page.goto(`/engenharia/flows/${String(flowId)}`);
  await page.getByTestId(`rf__node-${BLOCK_ID}`).dblclick();
  await expect(page.getByTestId("mpc-modal")).toBeVisible();
  await expect(page.getByTestId("config-label")).toBeFocused();
  await expect(page.getByRole("tooltip")).toHaveCount(0);
}

test.describe("Tooltip de ajuda no modal MPC", () => {
  test("PW-TT-01: abrir o modal foca o campo Rótulo, não o gatilho do tooltip (regressão)", async ({
    page,
  }) => {
    await abrirModal(page);

    // `showModal()` foca o primeiro elemento focável em ordem do DOM: sem o foco explícito
    // (MpcModal.tsx), o gatilho do tooltip do Rótulo (span com tabIndex=0, que precede o
    // <Input> na árvore) venceria essa corrida e abriria um tooltip indesejado ao abrir.
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-TT-02: hover no rótulo mostra descrição+exemplo; tirar o mouse fecha", async ({ page }) => {
    await abrirModal(page);

    const gatilho = page.getByText("Multiplicador", { exact: true });
    await gatilho.hover();
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toContainText("RF-606");
    await expect(tooltip).toContainText("Ex.:");
    // "Ex.: Ex.:" seria o bug de prefixo duplicado (achado/corrigido nesta revisão).
    await expect(tooltip).not.toContainText("Ex.: Ex.:");

    await page.mouse.move(10, 10);
    await expect(tooltip).toBeHidden();
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-TT-03: foco por teclado mostra o tooltip; Esc fecha só o tooltip, não o modal (regressão)", async ({
    page,
  }) => {
    await abrirModal(page);

    const gatilho = page.getByText("Multiplicador", { exact: true });
    await gatilho.focus();
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip).toBeVisible();

    // O <dialog> nativo fecha em Esc por padrão (evento "cancel") — sem
    // preventDefault/stopPropagation no handler do tooltip, o Esc que devia fechar só o
    // tooltip derrubava o modal inteiro junto (achado/corrigido nesta revisão).
    await page.keyboard.press("Escape");
    await expect(tooltip).toBeHidden();
    await expect(page.getByTestId("mpc-modal")).toBeVisible();
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-TT-04: clicar o texto do tooltip de 'MV com PID' não marca o checkbox (regressão)", async ({
    page,
  }) => {
    await abrirModal(page);
    await page.getByTestId("mpc-tab-variaveis").click();

    const checkbox = page.getByTestId("mpc-pid-toggle-mv_1");
    await expect(checkbox).not.toBeChecked();

    // O gatilho mora DENTRO do <label> do checkbox (associação por aninhamento, não
    // htmlFor) — sem `stopClick` no Tooltip, clicar o texto do gatilho encaminha um clique
    // nativo pro checkbox e marca "MV com PID" sem o usuário ter pedido isso (achado/
    // corrigido nesta revisão).
    await page.getByText("MV com PID (RF-604)", { exact: false }).click();
    await expect(checkbox).not.toBeChecked();

    // Clicar o checkbox em si continua funcionando normalmente.
    await checkbox.check();
    await expect(checkbox).toBeChecked();
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-TT-05: campo com testid próprio (Δu mínimo) também tem tooltip", async ({ page }) => {
    await abrirModal(page);
    await page.getByTestId("mpc-tab-variaveis").click();

    const gatilho = page.getByText("Δu mínimo", { exact: true });
    await gatilho.hover();
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toContainText("TD-007");
    await page.getByTestId("config-cancelar").click();
  });
});
