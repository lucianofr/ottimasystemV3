import { expect, test, type Locator, type Page } from "@playwright/test";

import { criarAmbiente, entrarNoShell, NODES, type AmbienteE2E } from "./fixtures";

/**
 * PW-MO-01..07 — combobox "Função objetivo" no modal do bloco MPC (ADR-027 §9 estendido).
 *
 * Cada variável (MV/CV/Restrição) ganha um `<Select>` com o leque exato de opções do seu
 * tipo; PSV de MV abre o campo de valor preferido; as três regras do servidor (equalize,
 * PSV nos limites, linha integradora) bloqueiam o Aplicar no espelho client-side com as
 * MESMAS mensagens pt-BR do 422.
 *
 * Grafo seed (padrão de `operate-mpc-select.spec.ts`, duplicado): 1 `opc_read` alimentando a
 * CV de 1 bloco `mpc` com 1 MV direta + 1 CV selfreg + 1 Restrição selfreg (cobre os três
 * leques). Nenhum flow é deployado — o editor entra direto em EDIT e salva sem o diálogo de
 * impacto.
 */

let ambiente: AmbienteE2E;

const BLOCK_ID = "mpc1";
const PUT_FLOW = (id: number) => `/api/flows/${String(id)}`;

function grafo(tagLeituraId: number) {
  return {
    nodes: [
      {
        id: "leitura",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 1, tag_id: tagLeituraId },
      },
      {
        id: "leitura2",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 2, tag_id: tagLeituraId },
      },
      {
        id: BLOCK_ID,
        type: "mpc",
        position: { x: 0, y: 0 },
        data: {
          exec_order: 3,
          name: "MPC objetivo",
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
            constraints: [
              {
                id: "co_1",
                name: "Pressao",
                eu: "bar",
                kind: "selfreg",
                tss: 10,
                range: { low: 0, high: 10 },
                priority: 1,
              },
            ],
            dvs: [],
          },
          models: {
            cv_1: { mv_1: { enabled: true, params: { K: 1, tau1: 2, tau2: 0.5, theta: 0 } } },
            co_1: { mv_1: { enabled: true, params: { K: 1, tau1: 2, tau2: 0.5, theta: 0 } } },
          },
        },
      },
    ],
    edges: [
      { id: "e1", source: "leitura", sourceHandle: "out", target: BLOCK_ID, targetHandle: "cv_1" },
      { id: "e2", source: "leitura2", sourceHandle: "out", target: BLOCK_ID, targetHandle: "co_1" },
    ],
  };
}

/** Monta um flow (sem deploy) com o grafo seed. Devolve o id. */
async function criarFlow(nome: string): Promise<number> {
  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: nome, ts_seconds: 1 },
  });
  if (!criado.ok()) throw new Error(`criação do flow: HTTP ${criado.status()}`);
  const corpo = (await criado.json()) as { id: number };
  const salvo = await ambiente.api.put(PUT_FLOW(corpo.id), {
    data: { graph_json: grafo(ambiente.tags["sine"]) },
  });
  if (!salvo.ok()) throw new Error(`salvar grafo: HTTP ${salvo.status()} — ${await salvo.text()}`);
  return corpo.id;
}

/** Abre o editor do flow no modal do bloco, já na aba Variáveis. */
async function abrirVariaveis(page: Page, flowId: number): Promise<void> {
  await page.goto(`/engenharia/flows/${String(flowId)}`);
  await page.getByTestId(`rf__node-${BLOCK_ID}`).dblclick();
  await expect(page.getByTestId("mpc-modal")).toBeVisible();
  await page.getByTestId("mpc-tab-variaveis").click();
}

let flowBase: number;
let flowPersistPsv: number;
let flowRoundTrip: number;

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "mpc-objective",
    tags: [{ chave: "sine", nodeId: NODES.sine, direcao: "r" }],
  });
  flowBase = await criarFlow(`MO Base ${ambiente.projectId}`);
  flowPersistPsv = await criarFlow(`MO Psv ${ambiente.projectId}`);
  flowRoundTrip = await criarFlow(`MO RoundTrip ${ambiente.projectId}`);
});

test.afterAll(async () => {
  // Sem deploy nesta suíte: apagar direto não esbarra no 409 de flow rodando.
  for (const id of [flowBase, flowPersistPsv, flowRoundTrip]) {
    await ambiente.api.delete(`/api/flows/${String(id)}`);
  }
  await ambiente.encerrar();
});

test.beforeEach(async ({ page }) => {
  await entrarNoShell(page);
});

test.describe("Combobox de função objetivo no modal do bloco MPC", () => {
  test("PW-MO-01: selects presentes com o leque exato por tipo, default Nenhuma", async ({
    page,
  }) => {
    await abrirVariaveis(page, flowBase);

    const selectMv = page.getByTestId("mpc-objective-mv_1");
    const selectCv = page.getByTestId("mpc-objective-cv_1");
    const selectCo = page.getByTestId("mpc-objective-co_1");
    await expect(selectMv).toHaveValue("none");
    await expect(selectCv).toHaveValue("none");
    await expect(selectCo).toHaveValue("none");

    async function mapaDe(seletor: Locator): Promise<Map<string, string>> {
      const pares = (await seletor
        .locator("option")
        .evaluateAll((ops) => ops.map((op) => [op.getAttribute("value"), op.textContent ?? ""]))) as [
        string,
        string,
      ][];
      return new Map(pares);
    }

    expect(await mapaDe(selectMv)).toEqual(
      new Map([
        ["none", "Nenhuma"],
        ["maximize", "Maximizar"],
        ["minimize", "Minimizar"],
        ["psv", "PSV (valor preferido)"],
        ["equalize", "Equalizar"],
      ]),
    );
    expect(await mapaDe(selectCv)).toEqual(
      new Map([
        ["none", "Nenhuma"],
        ["maximize", "Maximizar"],
        ["minimize", "Minimizar"],
        ["observe_limit", "Observar limites"],
        ["target", "Alvo (Target)"],
        ["psv", "PSV (valor preferido)"],
      ]),
    );
    expect(await mapaDe(selectCo)).toEqual(
      new Map([
        ["none", "Nenhuma"],
        ["maximize", "Maximizar"],
        ["minimize", "Minimizar"],
      ]),
    );

    await page.getByTestId("config-cancelar").click();
  });

  test("PW-MO-02: CV kind=integrating desabilita o select de objetivo e reseta para none", async ({
    page,
  }) => {
    await abrirVariaveis(page, flowBase);

    const selectObjetivo = page.getByTestId("mpc-objective-cv_1");
    await selectObjetivo.selectOption("maximize");
    await expect(selectObjetivo).toHaveValue("maximize");

    await page.getByTestId("mpc-kind-cv_1").selectOption("integrating");
    await expect(selectObjetivo).toBeDisabled();
    await expect(selectObjetivo).toHaveValue("none");

    await page.getByTestId("config-cancelar").click();
  });

  test("PW-MO-03: campo PSV só aparece com objective=psv; persiste após salvar e reabrir", async ({
    page,
  }) => {
    await abrirVariaveis(page, flowPersistPsv);

    await expect(page.getByTestId("mpc-mv-psv")).toHaveCount(0);
    await page.getByTestId("mpc-objective-mv_1").selectOption("psv");
    await expect(page.getByTestId("mpc-mv-psv")).toBeVisible();
    await page.getByTestId("mpc-mv-psv").fill("42");
    await page.getByTestId("config-aplicar").click();
    await expect(page.getByTestId("mpc-modal")).toBeHidden();

    const salvamento = page.waitForResponse(
      (resposta) => resposta.url().includes(PUT_FLOW(flowPersistPsv)) && resposta.request().method() === "PUT",
    );
    await page.getByTestId("flow-salvar").click();
    const resposta = await salvamento;
    expect(resposta.status()).toBe(200);

    await page.reload();
    await page.getByTestId(`rf__node-${BLOCK_ID}`).dblclick();
    await expect(page.getByTestId("mpc-modal")).toBeVisible();
    await page.getByTestId("mpc-tab-variaveis").click();

    await expect(page.getByTestId("mpc-objective-mv_1")).toHaveValue("psv");
    await expect(page.getByTestId("mpc-mv-psv")).toHaveValue("42");
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-MO-04: equalize com só 1 MV bloqueia Aplicar com a mensagem exata", async ({ page }) => {
    await abrirVariaveis(page, flowBase);

    await page.getByTestId("mpc-objective-mv_1").selectOption("equalize");
    await page.getByTestId("config-aplicar").click();

    // O próprio aplicar() navega para a aba Resumo em erro — nunca clicar `mpc-tab-resumo`
    // (testid colide entre o botão da aba e o <div> de conteúdo).
    await expect(page.getByTestId("mpc-modal")).toBeVisible();
    await expect(page.getByTestId("mpc-resumo-erros")).toContainText(
      "Equalize exige pelo menos duas MVs com esse objetivo",
    );

    await page.getByTestId("config-cancelar").click();
  });

  test("PW-MO-05: PSV fora dos limites bloqueia Aplicar; 422 do backend com a mesma mensagem", async ({
    page,
  }) => {
    await abrirVariaveis(page, flowBase);

    await page.getByTestId("mpc-objective-mv_1").selectOption("psv");
    await page.getByTestId("mpc-mv-psv").fill("150");
    await page.getByTestId("config-aplicar").click();

    await expect(page.getByTestId("mpc-modal")).toBeVisible();
    await expect(page.getByTestId("mpc-resumo-erros")).toContainText(
      "PSV exige um valor preferido dentro dos limites da MV",
    );

    // Prova de que o backend concorda (mesmo teste): PUT direto com a config inválida.
    const invalido = grafo(ambiente.tags["sine"]);
    const bloco = invalido.nodes.find((no) => no.id === BLOCK_ID);
    if (bloco === undefined) throw new Error("bloco mpc ausente no seed");
    bloco.data.variables.mvs[0] = {
      ...bloco.data.variables.mvs[0],
      objective: "psv",
      psv: 150,
    };
    const resposta = await ambiente.api.put(PUT_FLOW(flowBase), {
      data: { graph_json: invalido },
    });
    expect(resposta.status()).toBe(422);
    const detalhe = JSON.stringify(await resposta.json());
    expect(detalhe).toContain("PSV exige um valor preferido dentro dos limites da MV");

    await page.getByTestId("config-cancelar").click();
  });

  test("PW-MO-06: round-trip — MV maximize + CV target + CNSTR minimize sobrevivem a salvar/recarregar", async ({
    page,
  }) => {
    await abrirVariaveis(page, flowRoundTrip);

    await page.getByTestId("mpc-objective-mv_1").selectOption("maximize");
    await page.getByTestId("mpc-objective-cv_1").selectOption("target");
    await page.getByTestId("mpc-objective-co_1").selectOption("minimize");
    await page.getByTestId("config-aplicar").click();
    await expect(page.getByTestId("mpc-modal")).toBeHidden();

    const salvamento = page.waitForResponse(
      (resposta) => resposta.url().includes(PUT_FLOW(flowRoundTrip)) && resposta.request().method() === "PUT",
    );
    await page.getByTestId("flow-salvar").click();
    const resposta = await salvamento;
    expect(resposta.status()).toBe(200);

    await page.reload();
    await page.getByTestId(`rf__node-${BLOCK_ID}`).dblclick();
    await expect(page.getByTestId("mpc-modal")).toBeVisible();
    await page.getByTestId("mpc-tab-variaveis").click();

    await expect(page.getByTestId("mpc-objective-mv_1")).toHaveValue("maximize");
    await expect(page.getByTestId("mpc-objective-cv_1")).toHaveValue("target");
    await expect(page.getByTestId("mpc-objective-co_1")).toHaveValue("minimize");
    await page.getByTestId("config-cancelar").click();
  });

  test("PW-MO-07: retrocompat — flow salvo sem o campo objective lê como Nenhuma", async ({
    page,
  }) => {
    // flowBase intocado (PW-MO-01/02/04 cancelam; PW-MO-05 só gera PUT rejeitado 422).
    await abrirVariaveis(page, flowBase);

    await expect(page.getByTestId("mpc-objective-mv_1")).toHaveValue("none");
    await expect(page.getByTestId("mpc-objective-cv_1")).toHaveValue("none");
    await expect(page.getByTestId("mpc-objective-co_1")).toHaveValue("none");
    await expect(page.getByTestId("mpc-mv-psv")).toHaveCount(0);

    await page.getByTestId("config-cancelar").click();
  });
});
