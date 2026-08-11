import { expect, test } from "@playwright/test";

import { criarAmbiente, entrarNoShell, NODES, type AmbienteE2E } from "./fixtures";

/**
 * PW-OS-01..04 — card "Otimizador" na tela de Operação (ADR-027 §9 estendido): ausente sem
 * variável otimizada; "aguardando" antes da primeira execução; status/atual/alvo numéricos
 * com o MPC armado em REMOTO→AUTO; cold-start via `GET /api/history/ssto/last` no reload.
 *
 * Grafo seed (padrão de `operate-mpc-select.spec.ts`, duplicado): 1 `opc_read` alimentando a
 * CV de 1 bloco `mpc` com 1 MV direta + 1 CV selfreg — sp_limits largos e SOPDT K=1 para o
 * LP sair trivialmente `optimal` (PW-OS-03). `flowRodando` é deployado no `beforeAll` e
 * armado pelos comutadores reais da UI dentro de PW-OS-03 (o SSTO só publica em AUTO).
 *
 * Watchdog por flow (ADR-009 revisado): qualquer bloco MPC num flow sem watchdog recusa o
 * arme REMOTO com `write_target_sem_watchdog` — os três flows nascem com o watchdog do
 * opcsim armado (`NODES.wdFrom`/`wdTo`), mesmo padrão de `tests/e2e/f3_support.py`.
 */

let ambiente: AmbienteE2E;

const BLOCK_ID = "mpc1";

function grafo(tagLeituraId: number, objetivoCv?: string) {
  const cv = {
    id: "cv_1",
    name: "Nivel",
    eu: "%",
    kind: "selfreg",
    tss: 10,
    weight: 1,
    sp_limits: { min: 0, max: 1000 },
    ...(objetivoCv === undefined ? {} : { objective: objetivoCv }),
  };
  return {
    nodes: [
      {
        id: "leitura",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 1, tag_id: tagLeituraId },
      },
      {
        id: BLOCK_ID,
        type: "mpc",
        position: { x: 0, y: 0 },
        data: {
          exec_order: 2,
          name: "MPC otimizador",
          multiplier: 2,
          variables: {
            mvs: [
              {
                id: "mv_1",
                name: "Abertura",
                eu: "%",
                limits: { min: 0, max: 100 },
                du_max: 5,
                initial_value: 0,
              },
            ],
            cvs: [cv],
            constraints: [],
            dvs: [],
          },
          models: { cv_1: { mv_1: { enabled: true, params: { K: 1, tau1: 2, tau2: 0.5, theta: 0 } } } },
        },
      },
    ],
    edges: [
      { id: "e1", source: "leitura", sourceHandle: "out", target: BLOCK_ID, targetHandle: "cv_1" },
    ],
  };
}

async function criarFlow(nome: string, objetivoCv?: string): Promise<number> {
  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: nome, ts_seconds: 1 },
  });
  if (!criado.ok()) throw new Error(`criação do flow: HTTP ${criado.status()}`);
  const corpo = (await criado.json()) as { id: number };
  const salvo = await ambiente.api.put(`/api/flows/${String(corpo.id)}`, {
    data: { graph_json: grafo(ambiente.tags["sine"], objetivoCv) },
  });
  if (!salvo.ok()) throw new Error(`salvar grafo: HTTP ${salvo.status()} — ${await salvo.text()}`);
  // ADR-009 revisado: watchdog é por flow — sem ele o arme REMOTO do MPC é recusado
  // (`write_target_sem_watchdog`). Mesmo padrão de `tests/e2e/f3_support.py`.
  const watchdog = await ambiente.api.put(`/api/flows/${String(corpo.id)}`, {
    data: {
      watchdog_enabled: true,
      watchdog_connection_id: ambiente.connId,
      watchdog_read_node_id: NODES.wdTo,
      watchdog_write_node_id: NODES.wdFrom,
      watchdog_period_ms: 1000,
    },
  });
  if (!watchdog.ok()) throw new Error(`watchdog do flow: HTTP ${watchdog.status()} — ${await watchdog.text()}`);
  return corpo.id;
}

async function desiredState(id: number): Promise<string> {
  const resposta = await ambiente.api.get(`/api/flows/${String(id)}`);
  if (!resposta.ok()) throw new Error(`GET flow ${String(id)}: HTTP ${resposta.status()}`);
  const corpo: { desired_state: string } = await resposta.json();
  return corpo.desired_state;
}

let flowSemObjetivo: number;
let flowAguardando: number;
let flowRodando: number;

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "optimizer-summary",
    tags: [{ chave: "sine", nodeId: NODES.sine, direcao: "r" }],
  });
  flowSemObjetivo = await criarFlow(`OS SemObj ${ambiente.projectId}`);
  flowAguardando = await criarFlow(`OS Aguardando ${ambiente.projectId}`, "maximize");
  flowRodando = await criarFlow(`OS Rodando ${ambiente.projectId}`, "maximize");

  const deploy = await ambiente.api.post(`/api/flows/${String(flowRodando)}/deploy`);
  if (deploy.status() !== 202) throw new Error(`deploy: HTTP ${deploy.status()}`);
  await expect.poll(async () => desiredState(flowRodando), { timeout: 15_000 }).toBe("running");
});

test.afterAll(async () => {
  await ambiente.api.post(`/api/flows/${String(flowRodando)}/stop`);
  await expect.poll(async () => desiredState(flowRodando), { timeout: 15_000 }).toBe("stopped");
  for (const id of [flowSemObjetivo, flowAguardando, flowRodando]) {
    await ambiente.api.delete(`/api/flows/${String(id)}`);
  }
  await ambiente.encerrar();
});

test.beforeEach(async ({ page }) => {
  await entrarNoShell(page);
});

test.describe("Card Otimizador na tela de Operação", () => {
  test("PW-OS-01: card ausente quando nenhuma variável está otimizada", async ({ page }) => {
    await page.goto(`/operacao/${String(flowSemObjetivo)}/${BLOCK_ID}`);

    await expect(page.getByTestId("faceplate-principal")).toBeVisible();
    await expect(page.getByTestId("resumo-otimizador")).toHaveCount(0);
  });

  test("PW-OS-02: aguardando primeira execução antes de qualquer execução do SSTO", async ({
    page,
  }) => {
    await page.goto(`/operacao/${String(flowAguardando)}/${BLOCK_ID}`);

    const card = page.getByTestId("resumo-otimizador");
    await expect(card).toBeVisible();
    await expect(card).toContainText("Aguardando primeira execução do otimizador");

    // Estado "aguardando" fundado em backend: nenhuma execução registrada para este bloco.
    const resposta = await ambiente.api.get(
      `/api/history/ssto/last?flow_id=${String(flowAguardando)}&block_id=${BLOCK_ID}`,
    );
    expect(resposta.status()).toBe(200);
    expect(await resposta.json()).toBeNull();
  });

  test("PW-OS-03: armado REMOTO→AUTO — card com status/atual/alvo; objetivo chega à API de operate", async ({
    page,
  }) => {
    await page.goto(`/operacao/${String(flowRodando)}/${BLOCK_ID}`);

    // Armar pelos comutadores reais: MAN/AUTO só renderiza com local_remote === "remote"
    // CONFIRMADO pelo estado publicado.
    await page.getByTestId("faceplate-modo-local-remoto-remote").click();
    await expect(page.getByTestId("faceplate-modo-man-auto")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("faceplate-modo-man-auto-auto").click();
    await expect(page.getByTestId("faceplate-modo-man-auto-auto")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // A confirmação real do arme é o conteúdo do card: o SSTO só publica rodando em AUTO.
    const card = page.getByTestId("resumo-otimizador");
    await expect(card).not.toContainText("Aguardando primeira execução do otimizador", {
      timeout: 20_000,
    });
    await expect(card).toContainText("Ótimo", { timeout: 20_000 });
    await expect(card).toContainText("Maximizar");
    await expect(card).not.toContainText("—");

    // `objective` chega à projeção de operate deste flow.
    const resposta = await ambiente.api.get("/api/operate/mpcs");
    expect(resposta.status()).toBe(200);
    const blocos = (await resposta.json()) as {
      flow_id: number;
      block_id: string;
      variables: { cvs: { id: string; objective: string }[] };
    }[];
    const bloco = blocos.find((b) => b.flow_id === flowRodando && b.block_id === BLOCK_ID);
    expect(bloco?.variables.cvs.find((cv) => cv.id === "cv_1")?.objective).toBe("maximize");
  });

  test("PW-OS-04: cold-start — reload popula o card via /api/history/ssto/last sem novo ciclo", async ({
    page,
  }) => {
    // Roda após PW-OS-03 (workers: 1, ordem serial): flowRodando segue deployado/armado.
    // A requisição do cold-start dispara no boot da página (react-query monta o hook
    // junto do card) — capturar a resposta DELA prova o contrato sem depender de corrida
    // contra a navegação do reload (que invalida o corpo de uma resposta ainda pendente).
    const respostaPrometida = page.waitForResponse(
      (resposta) =>
        resposta.url().includes("/api/history/ssto/last") && resposta.request().method() === "GET",
    );
    await page.goto(`/operacao/${String(flowRodando)}/${BLOCK_ID}`);
    const resposta = await respostaPrometida;

    expect(resposta.status()).toBe(200);
    const corpo: { run: { status: string } } | null = await resposta.json();
    expect(corpo).not.toBeNull();
    if (corpo === null) throw new Error("cold-start devolveu null");

    // O rótulo do status gravado já aparece populado do REST — sem esperar um quadro WS
    // novo com `ssto` (o runtime publica a execução uma vez por ciclo, Ts_mpc = 2 s aqui,
    // mas o gate não pode depender desse timing).
    const ROTULO: Record<string, string> = {
      optimal: "Ótimo",
      relaxed: "Relaxado",
      infeasible: "Inviável",
      unbounded: "Ilimitado",
      error: "Erro",
    };
    await expect(page.getByTestId("resumo-otimizador")).toContainText(
      ROTULO[corpo.run.status],
      { timeout: 3_000 },
    );

    // Reload: o mesmo caminho REST popula de novo (agora com o WS já assinado do 1º load,
    // o que reforça que nenhuma das duas fontes depende do outro).
    await page.reload();
    await expect(page.getByTestId("resumo-otimizador")).toContainText(
      ROTULO[corpo.run.status],
      { timeout: 3_000 },
    );
  });
});
