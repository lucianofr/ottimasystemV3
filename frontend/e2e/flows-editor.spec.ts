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
let flowRealimenta: number;
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

/** Malha PID↔TFS (ADR-040): a planta realimenta a PV por aresta de realimentação, que é o
 *  que torna o ciclo aceitável. `y2`/`sp` ficam livres — é o par que o PW-FL-05 liga no
 *  arraste para provocar o diálogo sem precisar desfazer nada antes. */
function grafoPidTfs(): unknown {
  const desligado = {
    enabled: false,
    kind: "sopdt",
    params: { K: 1, tau1: 1, tau2: 0, theta: 0 },
  };
  return {
    nodes: [
      {
        id: "pid",
        type: "pid",
        position: { x: 0, y: 0 },
        data: {
          exec_order: 1,
          kc: 2,
          ti_seconds: 10,
          td_seconds: 0,
          setpoint: 50,
          output_min: 0,
          output_max: 100,
          auto_mode: true,
          proportional_on_measurement: false,
          differential_on_measurement: false,
          starting_output: 0,
        },
      },
      {
        id: "tfs",
        type: "tfs",
        position: { x: 420, y: 0 },
        data: {
          exec_order: 2,
          matrix: [
            [{ enabled: true, kind: "sopdt", params: { K: 1, tau1: 5, tau2: 0, theta: 0 } }, desligado],
            [desligado, desligado],
          ],
          y0: [0, 0],
        },
      },
    ],
    edges: [
      { id: "e1", source: "pid", sourceHandle: "out", target: "tfs", targetHandle: "u1" },
      {
        id: "e2",
        source: "tfs",
        sourceHandle: "y1",
        target: "pid",
        targetHandle: "pv",
        feedback_init: 0,
      },
    ],
  };
}

async function criarFlow(nome: string, tagId: number, grafo?: unknown): Promise<number> {
  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: nome, ts_seconds: 1 },
  });
  if (!criado.ok()) throw new Error(`criação do flow ${nome}: HTTP ${criado.status()}`);
  const corpo: FlowIdOut = await criado.json();
  const salvo = await ambiente.api.put(`/api/flows/${String(corpo.id)}`, {
    data: { graph_json: grafo ?? grafoMpc(tagId) },
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
  flowRealimenta = await criarFlow(`Editor Realimentacao ${RUN_ID}`, tagId, grafoPidTfs());
  await deployEAguardar(flowOnline);
  await deployEAguardar(flowProps);
  await deployEAguardar(flowImpacto);
  // flowParado fica sem deploy: é o "flow PARADO" que o PW-FL-04 sobe pelo editor.
});

test.afterAll(async () => {
  for (const id of [flowOnline, flowProps, flowImpacto, flowParado, flowRealimenta]) {
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

  test("PW-FL-05: ligação que fecha ciclo pede realimentação e salva com feedback_init", async ({
    page,
  }) => {
    await page.goto(`/engenharia/flows/${String(flowRealimenta)}`);
    // Flow nunca deployado: o modo cai em "edit", com paleta e Salvar já disponíveis.
    await expect(page.getByTestId("flow-salvar")).toBeVisible();

    // A aresta de realimentação salva (`TFS.y1 -> PID.pv`) nasce tracejada já em edição:
    // o tracejado é estrutural (ADR-040 D5), não vem do dado ao vivo.
    await expect(page.locator('.react-flow__edge[data-id="e2"]')).toHaveClass(/aresta-retorno/);

    // `TFS.y2 -> PID.sp` fecha o MESMO ciclo por um par de portas livres: o ciclo é o único
    // impedimento, então em vez de recusar o editor pede a condição inicial.
    //
    // A caixa dos handles é lida DEPOIS de a grade assentar (medir durante o `fitView`
    // devolve coordenada velha, o `mouse.down` cai no corpo do nó e o gesto vira arraste de
    // bloco — sem conexão, sem diálogo, acusando a feature errada). A mira vai para a
    // metade INTERNA do handle: o card do bloco tem `overflow-hidden`, então a metade que
    // sobra para fora da borda é recortada e o centro geométrico da caixa cai no card.
    // `elementFromPoint` confirma o alvo antes de apertar o botão.
    const pontoDoHandle = async (
      seletor: string,
      dx: number,
    ): Promise<{ x: number; y: number }> => {
      const caixa = await page.locator(seletor).boundingBox();
      if (caixa === null) throw new Error(`handle '${seletor}' sem caixa delimitadora`);
      const ponto = { x: caixa.x + caixa.width / 2 + dx, y: caixa.y + caixa.height / 2 };
      const alvo = await page.evaluate(
        ({ x, y }) => document.elementFromPoint(x, y)?.className ?? "",
        ponto,
      );
      if (!String(alvo).includes("react-flow__handle")) {
        throw new Error(`ponto (${String(ponto.x)}, ${String(ponto.y)}) não é o handle: '${String(alvo)}'`);
      }
      return ponto;
    };
    await expect(page.locator('.react-flow__node[data-id="tfs"]')).toBeVisible();
    await page.waitForTimeout(1_000); // fitView do React Flow é animado
    // saída fica na borda direita (interior à esquerda); entrada, na esquerda (interior à direita)
    const de = await pontoDoHandle('.react-flow__node[data-id="tfs"] .react-flow__handle[data-handleid="y2"]', -3);
    const para = await pontoDoHandle('.react-flow__node[data-id="pid"] .react-flow__handle[data-handleid="sp"]', 3);
    await page.mouse.move(de.x, de.y);
    await page.mouse.down();
    await page.mouse.move(de.x, de.y + 120, { steps: 8 });
    await page.mouse.move(para.x, para.y, { steps: 12 });
    await page.mouse.up();

    await expect(page.getByTestId("flow-realimentacao-dialog")).toBeVisible();
    await page.getByTestId("flow-realimentacao-valor").fill("25");
    await page.getByTestId("flow-realimentacao-confirmar").click();
    await expect(page.getByTestId("flow-realimentacao-dialog")).toHaveCount(0);

    const nova = page.locator('.react-flow__edge[data-id="tfs.y2->pid.sp"]');
    await expect(nova).toHaveClass(/aresta-retorno/);

    await page.getByTestId("flow-salvar").click();
    await expect
      .poll(
        async () => {
          const res = await ambiente.api.get(`/api/flows/${String(flowRealimenta)}`);
          const corpo = (await res.json()) as {
            readonly graph_json: { readonly edges: readonly { readonly id: string; readonly feedback_init?: number }[] };
          };
          return corpo.graph_json.edges.find((e) => e.id === "tfs.y2->pid.sp")?.feedback_init;
        },
        { message: "feedback_init da aresta nova no grafo salvo", timeout: 15_000 },
      )
      .toBe(25);
  });
});
