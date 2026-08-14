import { expect, test, type Page } from "@playwright/test";

import { criarAmbiente, entrarNoShell, NODES, RUN_ID, type AmbienteE2E } from "./fixtures";

/**
 * PW-FL-01..04 — editor de Flows: modo EDIT/ONLINE, propriedades (Ts), diálogo de impacto
 * no MPC (TD-006) e Deploy direto do editor.
 *
 * Um flow por cenário (nomes únicos por `RUN_ID`), todos com o mesmo grafo mínimo (leitura
 * OPC alimentando a CV de um MPC de uma MV direta — mesmo molde do contrato compartilhado):
 * o bastante para o comutador de modo ter valor de porta pra mostrar e para o diálogo de
 * impacto ter um bloco MPC pra listar. `flowParado` fica sem deploy no `beforeAll` — é o
 * cenário "flow PARADO" do PW-FL-04.
 */

interface FlowIdOut {
  readonly id: number;
}

interface FlowEstadoOut {
  readonly desired_state: "running" | "stopped";
}

interface FlowTsOut {
  readonly ts_seconds: number;
}

let ambiente: AmbienteE2E;
let flowOnline: number;
let flowProps: number;
let flowImpacto: number;
let flowParado: number;
const nomeFlowParado = `Editor Deploy ${RUN_ID}`;

function grafoMpc(tagId: number): unknown {
  return {
    nodes: [
      {
        id: "leitura",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 1, tag_id: tagId },
      },
      {
        id: "mpc1",
        type: "mpc",
        position: { x: 320, y: 0 },
        data: {
          exec_order: 2,
          name: "MPC da tela",
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
          models: {
            cv_1: { mv_1: { enabled: true, params: { K: 1, tau1: 2, tau2: 0.5, theta: 0 } } },
          },
        },
      },
    ],
    edges: [{ id: "e1", source: "leitura", sourceHandle: "out", target: "mpc1", targetHandle: "cv_1" }],
  };
}

async function criarFlow(nome: string, tagId: number): Promise<number> {
  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: nome, ts_seconds: 1 },
  });
  if (!criado.ok()) throw new Error(`criação do flow ${nome}: HTTP ${criado.status()}`);
  const corpo: FlowIdOut = await criado.json();
  const salvo = await ambiente.api.put(`/api/flows/${String(corpo.id)}`, {
    data: { graph_json: grafoMpc(tagId) },
  });
  if (!salvo.ok()) throw new Error(`PUT do grafo do flow ${nome}: HTTP ${salvo.status()}`);
  return corpo.id;
}

async function desiredState(id: number): Promise<FlowEstadoOut["desired_state"]> {
  const res = await ambiente.api.get(`/api/flows/${String(id)}`);
  const corpo: FlowEstadoOut = await res.json();
  return corpo.desired_state;
}

async function aguardarDesiredState(id: number, estado: "running" | "stopped"): Promise<void> {
  await expect
    .poll(async () => desiredState(id), {
      message: `desired_state do flow ${String(id)}`,
      timeout: 15_000,
    })
    .toBe(estado);
}

async function deployEAguardar(id: number): Promise<void> {
  const deploy = await ambiente.api.post(`/api/flows/${String(id)}/deploy`);
  if (deploy.status() !== 202) throw new Error(`deploy do flow ${String(id)}: HTTP ${deploy.status()}`);
  await aguardarDesiredState(id, "running");
}

/** Para de graça em flow já parado (idempotente) — usado no teardown para os quatro flows,
 *  independente de terem sido deployados durante o teste (PW-FL-04). Excluir um flow com
 *  `desired_state == "running"` é 409 (`services/api/.../routers/flows.py`). */
async function pararEApagar(id: number): Promise<void> {
  await ambiente.api.post(`/api/flows/${String(id)}/stop`);
  await aguardarDesiredState(id, "stopped");
  const excluido = await ambiente.api.delete(`/api/flows/${String(id)}`);
  if (excluido.status() !== 204) throw new Error(`exclusão do flow ${String(id)}: HTTP ${excluido.status()}`);
}

async function arrastarNo(page: Page, testid: string, dx: number, dy: number): Promise<void> {
  const no = page.getByTestId(testid);
  const caixa = await no.boundingBox();
  if (caixa === null) throw new Error(`nó '${testid}' sem caixa delimitadora`);
  const cx = caixa.x + caixa.width / 2;
  const cy = caixa.y + caixa.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + dx, cy + dy, { steps: 10 });
  await page.mouse.up();
}

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "flows-editor",
    tags: [{ chave: "r", nodeId: NODES.sine, direcao: "r" }],
  });
  const tagId = ambiente.tags["r"];
  flowOnline = await criarFlow(`Editor Online ${RUN_ID}`, tagId);
  flowProps = await criarFlow(`Editor Props ${RUN_ID}`, tagId);
  flowImpacto = await criarFlow(`Editor Impacto ${RUN_ID}`, tagId);
  flowParado = await criarFlow(nomeFlowParado, tagId);
  await deployEAguardar(flowOnline);
  await deployEAguardar(flowProps);
  await deployEAguardar(flowImpacto);
  // flowParado fica sem deploy: é o "flow PARADO" que o PW-FL-04 sobe pelo editor.
});

test.afterAll(async () => {
  for (const id of [flowOnline, flowProps, flowImpacto, flowParado]) {
    await pararEApagar(id);
  }
  await ambiente.encerrar();
});

test.beforeEach(async ({ page }) => {
  await entrarNoShell(page);
});

test.describe("Editor de Flows", () => {
  test("PW-FL-01: modo default ONLINE mostra valor ao vivo; EDIT libera paleta e Salvar", async ({
    page,
  }) => {
    await page.goto(`/engenharia/flows/${String(flowOnline)}`);

    // Flow rodando: o modo default é ONLINE. Valor de porta visível (opcsim publica `sine`
    // continuamente — basta esperar o locator), paleta e Salvar ocultos.
    await expect(page.getByTestId("flow-modo-online")).toHaveAttribute("aria-pressed", "true", {
      timeout: 20_000,
    });
    await expect(page.getByTestId("porta-valor").first()).toBeVisible();
    await expect(page.getByTestId("paleta-opc_read")).toHaveCount(0);
    await expect(page.getByTestId("flow-salvar")).toHaveCount(0);

    await page.getByTestId("flow-modo-edit").click();

    // EDIT desliga os valores ao vivo (o bloco some do DOM, não só fica invisível) e libera
    // paleta e Salvar.
    await expect(page.getByTestId("porta-valor")).toHaveCount(0);
    await expect(page.getByTestId("paleta-opc_read")).toBeVisible();
    await expect(page.getByTestId("flow-salvar")).toBeVisible();
  });

  test("PW-FL-02: mudar Ts com flow rodando avisa e reinicia; header reflete o Ts novo", async ({
    page,
  }) => {
    await page.goto(`/engenharia/flows/${String(flowProps)}`);

    await page.getByTestId("flow-props-abrir").click();
    await expect(page.getByTestId("flow-props-modal")).toBeVisible();

    await page.getByTestId("flow-props-ts").selectOption("2");
    // Com o flow rodando, "Aplicar" não aplica direto: troca o rodapé pelo passo de
    // confirmação, porque trocar o Ts reconstrói todos os blocos e derruba o MPC a LOCAL.
    await page.getByTestId("flow-props-aplicar").click();
    await expect(page.getByTestId("flow-props-aviso")).toContainText(
      "Alterar o Ts reinicia todos os blocos do flow",
    );

    await page.getByTestId("flow-props-confirmar").click();
    await expect(page.getByTestId("flow-props-modal")).toBeHidden();

    await expect(page.getByTestId("flow-header-ts")).toHaveText("2");
    await expect
      .poll(
        async () => {
          const res = await ambiente.api.get(`/api/flows/${String(flowProps)}`);
          const corpo: FlowTsOut = await res.json();
          return corpo.ts_seconds;
        },
        { message: "ts_seconds do flow após confirmar propriedades" },
      )
      .toBe(2);
  });

  test("PW-FL-03: salvar sintonia do MPC abre o diálogo de impacto; salvar sem mexer não abre", async ({
    page,
  }) => {
    await page.goto(`/engenharia/flows/${String(flowImpacto)}`);

    // Flow rodando: modo default ONLINE. Força EDIT para poder arrastar/configurar blocos.
    await expect(page.getByTestId("flow-modo-online")).toHaveAttribute("aria-pressed", "true", {
      timeout: 20_000,
    });
    await page.getByTestId("flow-modo-edit").click();
    await expect(page.getByTestId("flow-salvar")).toBeVisible();

    // Caso "sem diálogo": só a posição muda — a config funcional do MPC (TD-006) é a mesma,
    // então nenhum bloco tem efeito diferente de "preservado" e o diálogo não abre.
    // `rf__node-<id>` é o testid que o próprio @xyflow/react grava no wrapper do nó
    // (`NodeWrapper`); `BlocoChapa`/`NoMpc` não expõem um testid de aplicação para o nó.
    await arrastarNo(page, "rf__node-leitura", 80, 60);
    await page.getByTestId("flow-salvar").click();
    // A região de mensagens só aparece depois do primeiro save bem-sucedido (avisosServidor
    // deixa de ser null) — sinal de conclusão sem precisar de `waitForTimeout`.
    await expect(page.getByTestId("editor-mensagens")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("flow-impacto-dialog")).toHaveCount(0);

    // Caso "com diálogo": mudar o peso da CV preserva o conjunto de MVs -> rearme bumpless
    // (TD-006).
    await page.getByTestId("rf__node-mpc1").dblclick();
    await expect(page.getByTestId("mpc-modal")).toBeVisible();
    await page.getByTestId("mpc-tab-variaveis").click();
    await page.getByTestId("mpc-cv-weight").first().fill("5");
    await page.getByTestId("config-aplicar").click();
    await expect(page.getByTestId("mpc-modal")).toBeHidden();

    await page.getByTestId("flow-salvar").click();
    await expect(page.getByTestId("flow-impacto-dialog")).toBeVisible();
    await expect(page.getByTestId("flow-impacto-dialog")).toContainText(
      "modo preservado; MV segura o último valor por ~1 ciclo",
    );
    await page.getByTestId("flow-impacto-confirmar").click();
    await expect(page.getByTestId("flow-impacto-dialog")).toHaveCount(0);
  });

  test("PW-FL-04: Deploy no editor de um flow parado leva o flow a rodando", async ({ page }) => {
    await page.goto(`/engenharia/flows/${String(flowParado)}`);

    // Flow nunca rodou: sem status publicado, o modo cai no default "edit" (`modoEfetivo =
    // modo ?? "edit"`) — o botão de Deploy já está visível sem precisar trocar de modo.
    await expect(page.getByTestId("flow-deploy-editor")).toBeVisible();
    await page.getByTestId("flow-deploy-editor").click();

    await expect
      .poll(async () => desiredState(flowParado), {
        message: "desired_state do flow após Deploy no editor",
        timeout: 15_000,
      })
      .toBe("running");

    await page.goto("/engenharia/flows");
    const linha = page.getByTestId("flow-row").filter({ hasText: nomeFlowParado });
    await expect(linha.getByTestId("flow-last-state")).toHaveText(/Rodando/, { timeout: 30_000 });
  });
});
