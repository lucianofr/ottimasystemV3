import { expect, test } from "@playwright/test";

import { criarAmbiente, entrarNoShell, NODES, type AmbienteE2E } from "./fixtures";

/**
 * PW-OP-01..04 — tela de Operação: seção futura sempre visível (mesmo sem predição), escala
 * manual por linha da legenda, janela deslizante `<`/`>`/Reset e o card principal (Ts MPC,
 * horizontes e relógio).
 *
 * Grafo MPC mínimo (plano de melhorias, "Contract — grafo MPC mínimo válido"): 1 `opc_read`
 * alimentando a CV de um bloco `mpc` com 1 MV direta. `ts_seconds: 1` + `multiplier: 2` e
 * `tss: 10` derivam horizontes DETERMINÍSTICOS no servidor — `ts_mpc = 2`, `np = ceil(10/2) =
 * 5`, `nc = max(2, ceil(5/4)) = 2` —, usados nas asserções de PW-OP-04. Sem deploy: a
 * projeção `/api/operate/mpcs` inclui o bloco independentemente do flow estar rodando, e o
 * MPC nasce em LOCAL (`mpc.state` nunca publicado) — exatamente o cenário de PW-OP-01, onde
 * a predição vem vazia mas as duas seções do trend (Histórico | Previsão) continuam ali.
 *
 * Diferente de `trend-eng.spec.ts`, este spec não usa `addInitScript` para zerar o
 * localStorage de escalas: cada teste já recebe um `context`/`page` novo do Playwright (sem
 * `storageState` configurado em `playwright.config.ts`), o que já isola a chave por execução
 * — e um `addInitScript` de limpeza dispararia de novo no `page.reload()` de PW-OP-02,
 * apagando a escala recém-persistida antes do bootstrap da página relida (verificado com um
 * probe local de `addInitScript` + `reload()`).
 */

const JANELA_PADRAO_S = 1800; // "30 min" (JANELAS_OPERACAO, trendOperacao.ts) — default da tela.

let ambiente: AmbienteE2E;
let flowId: number;

const BLOCK_ID = "mpc1";

function grafoMpc(tagLeituraId: number) {
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
          models: { cv_1: { mv_1: { enabled: true, params: { K: 1, tau1: 2, tau2: 0.5, theta: 0 } } } },
        },
      },
    ],
    edges: [{ id: "e1", source: "leitura", sourceHandle: "out", target: BLOCK_ID, targetHandle: "cv_1" }],
  };
}

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "operate",
    tags: [{ chave: "sine", nodeId: NODES.sine, direcao: "r" }],
  });

  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: "Flow operação E2E", ts_seconds: 1 },
  });
  if (!criado.ok()) throw new Error(`criação do flow: HTTP ${criado.status()}`);
  const corpo = (await criado.json()) as { id: number };
  flowId = corpo.id;

  const salvo = await ambiente.api.put(`/api/flows/${String(flowId)}`, {
    data: { graph_json: grafoMpc(ambiente.tags["sine"]) },
  });
  if (!salvo.ok()) {
    throw new Error(`salvar grafo do flow: HTTP ${salvo.status()} — ${await salvo.text()}`);
  }
});

test.afterAll(async () => {
  // Sem deploy nesta suíte: nunca chega a "running", então apagar direto não esbarra no 409
  // de flow rodando (plano, "Contract — grafo MPC mínimo válido").
  await ambiente.api.delete(`/api/flows/${String(flowId)}`);
  await ambiente.encerrar();
});

test.beforeEach(async ({ page }) => {
  await entrarNoShell(page);
  // Navegação direta pela URL (`/operacao/:flowId/:blockId`, router.tsx) — o MPC criado no
  // `beforeAll` é o único do projeto, então o seletor (`/operacao`) redirecionaria pro mesmo
  // lugar; ir direto evita depender do tempo do redirect.
  await page.goto(`/operacao/${String(flowId)}/${BLOCK_ID}`);
  await expect(page.getByTestId("operate-trend")).toBeVisible();
});

test.describe("Tela de Operação", () => {
  test("PW-OP-01: as duas seções do trend existem mesmo com o MPC em LOCAL", async ({ page }) => {
    await expect(page.getByTestId("operate-trend-chart")).toBeVisible();
    // O ponto do cenário: histórico E previsão convivem no cabeçalho mesmo sem predição —
    // era isso que sumia antes da tarefa 2.2 (a seção futura só existia quando havia dado).
    await expect(page.getByTestId("operate-trend-secao-futura")).toHaveText("Previsão");
    await expect(page.getByTestId("operate-trend-sem-predicao")).toHaveText(
      "Sem predição — MPC fora de AUTO",
    );
  });

  test("PW-OP-02: cada variável listada tem escala Y na própria linha, independente", async ({
    page,
  }) => {
    const linhas = page.getByTestId("operate-trend-legend-item");
    const linha = (varId: string) =>
      page.locator(`[data-testid="operate-trend-legend-item"][data-var-id="${varId}"]`);
    const linhaCv = linha("cv_1");
    const linhaMv = linha("mv_1");

    // O ponto do cenário: o controle de escala (min/max + AUTOSCALE) mora na LINHA de cada
    // variável listada, não num bloco único acima da lista — inclusive nas linhas de pena
    // desligada (`mv_1`), cuja faixa passa a valer no instante em que a pena é ligada.
    await expect(page.getByTestId("operate-escala-auto")).toHaveCount(await linhas.count());
    await expect(linhaCv.getByTestId("operate-escala-auto")).toBeChecked();
    await expect(linhaMv.getByTestId("operate-escala-auto")).toBeChecked();

    await linhaCv.getByTestId("operate-escala-auto").uncheck();
    await expect(linhaCv.getByTestId("operate-escala-min")).toBeEnabled();
    await linhaCv.getByTestId("operate-escala-min").fill("0");
    await linhaCv.getByTestId("operate-escala-max").fill("100");

    // Independência: fixar a faixa de uma variável não tira a outra do autoscale.
    await expect(linhaMv.getByTestId("operate-escala-auto")).toBeChecked();
    await expect(linhaMv.getByTestId("operate-escala-min")).toBeDisabled();

    // Editar a escala pela linha não pode alternar a pena da linha (o clique é do controle,
    // não da legenda) — sem isso o operador desligaria a variável ao ajustar a faixa dela.
    await expect(linhaCv.getByRole("checkbox").first()).toBeChecked();

    await page.reload();
    await expect(page.getByTestId("operate-trend")).toBeVisible();

    await expect(linhaCv.getByTestId("operate-escala-auto")).not.toBeChecked();
    await expect(linhaCv.getByTestId("operate-escala-min")).toHaveValue("0");
    await expect(linhaCv.getByTestId("operate-escala-max")).toHaveValue("100");
    await expect(linhaMv.getByTestId("operate-escala-auto")).toBeChecked();
  });

  test("PW-OP-03: janela deslizante pausa/retoma o polling do histórico", async ({ page }) => {
    const consultas: URL[] = [];
    page.on("request", (requisicao) => {
      const url = new URL(requisicao.url());
      if (url.pathname === "/api/history/mpc") consultas.push(url);
    });

    // O `beforeEach` já carregou a tela, então a PRIMEIRA consulta saiu antes deste listener
    // existir. Recarregar com o listener no ar dá um ponto de partida observável, em vez de
    // depender de o polling de 5 s cair dentro da janela do `poll`.
    await page.reload();
    await expect(page.getByTestId("operate-trend")).toBeVisible();
    await expect
      .poll(() => consultas.length, { message: "consulta inicial ao vivo" })
      .toBeGreaterThan(0);
    await expect(page.getByTestId("operate-janela-avancar")).toBeDisabled();

    const antesDeVoltar = consultas.length;
    await page.getByTestId("operate-janela-voltar").click();
    await page.getByTestId("operate-janela-voltar").click();
    await expect(page.getByTestId("operate-janela-avancar")).toBeEnabled();
    await expect
      .poll(() => consultas.length, { message: "consulta da janela deslizada" })
      .toBeGreaterThan(antesDeVoltar);

    const deslizada = consultas.at(-1)!;
    const fim = Date.parse(deslizada.searchParams.get("end") ?? "");
    const inicio = Date.parse(deslizada.searchParams.get("start") ?? "");
    // Dois cliques = meia janela cada = uma janela inteira para trás.
    expect(Date.now() - fim).toBeGreaterThan((JANELA_PADRAO_S / 2) * 1000);
    expect(Math.round((fim - inicio) / 1000)).toBe(JANELA_PADRAO_S);

    // Polling desligado: a vista congelada não pode continuar puxando `end = agora` sozinha.
    // Único `waitForTimeout` aceitável — prova AUSÊNCIA de atividade, não sincroniza nada.
    const contagemPausada = consultas.length;
    await page.waitForTimeout(7000);
    expect(consultas.length, "polling deveria estar pausado na vista congelada").toBe(
      contagemPausada,
    );

    // Avançar até alcançar o presente: o botão desabilita e a vista retoma ao vivo sozinha.
    for (let tentativa = 0; tentativa < 5; tentativa++) {
      if (await page.getByTestId("operate-janela-avancar").isDisabled()) break;
      await page.getByTestId("operate-janela-avancar").click();
    }
    await expect(page.getByTestId("operate-janela-avancar")).toBeDisabled();
    await expect
      .poll(() => consultas.length, { message: "consulta ao voltar ao vivo por avançar" })
      .toBeGreaterThan(contagemPausada);
    expect(Date.now() - Date.parse(consultas.at(-1)!.searchParams.get("end") ?? "")).toBeLessThan(
      30_000,
    );

    // Reset layout: mesmo contrato de "volta ao vivo e o polling retoma", a partir de uma
    // vista deslizada de novo (o botão de reset da operação não tem estado desabilitado —
    // diferente do trend de engenharia, `TrendOperacao.tsx` nunca liga `disabled` a ele).
    await page.getByTestId("operate-janela-voltar").click();
    await expect(page.getByTestId("operate-janela-avancar")).toBeEnabled();
    const antesDoReset = consultas.length;
    await page.getByTestId("operate-janela-reset").click();
    await expect(page.getByTestId("operate-janela-avancar")).toBeDisabled();
    await expect
      .poll(() => consultas.length, { message: "consulta ao voltar ao vivo pelo reset" })
      .toBeGreaterThan(antesDoReset);
    expect(Date.now() - Date.parse(consultas.at(-1)!.searchParams.get("end") ?? "")).toBeLessThan(
      30_000,
    );
  });

  test("PW-OP-04: card principal mostra Ts/horizontes derivados e o relógio avança", async ({
    page,
  }) => {
    // Horizontes deterministicos do grafo mínimo (ver comentário do topo do arquivo):
    // ts_mpc=2, np=5, nc=2 — calculados pelo servidor (0.2), não pelo cliente.
    await expect(page.getByTestId("faceplate-ts-mpc")).toContainText("Ts MPC 2 s");
    await expect(page.getByTestId("faceplate-horizontes")).toContainText("Np 5");
    await expect(page.getByTestId("faceplate-horizontes")).toContainText("Nc 2");

    const relogio = page.getByTestId("faceplate-relogio");
    const leituraInicial = await relogio.textContent();
    await expect
      .poll(() => relogio.textContent(), { message: "relógio de 1s avança" })
      .not.toBe(leituraInicial);
  });

  test("PW-OP-06: combobox de MPC aparece mesmo com um único bloco no projeto", async ({
    page,
  }) => {
    const seletor = page.getByTestId("operate-mpc-select");
    await expect(seletor).toBeVisible();
    await expect(seletor.locator("option")).toHaveCount(1);
    await expect(seletor.locator("option").first()).toHaveText(/MPC da tela/);
  });

  test("PW-OP-07: linha 'agora' anda no relógio de parede, mesmo sem dado novo", async ({
    page,
  }) => {
    // Sem deploy nesta suíte: nenhum dado novo chega — dois ticks consecutivos do canvas
    // dentro da janela de 5 s do polling provam a cadência própria de 1 s da linha. O hash
    // cobre TODAS as camadas do uPlot (a linha "agora" é desenhada na camada "over").
    const container = page.getByTestId("operate-trend-chart");
    await expect(container.locator("canvas").first()).toBeVisible();
    const hash = async () =>
      container.locator("canvas").evaluateAll((cs) =>
        cs.map((c: HTMLCanvasElement) => c.toDataURL().length + c.toDataURL().slice(-32)).join("|"),
      );
    const quadro0 = await hash();
    await page.waitForTimeout(3000);
    const quadro1 = await hash();
    expect(quadro1, "a linha 'agora' deveria ter andado em 3 s sem dado novo").not.toBe(quadro0);
    await page.waitForTimeout(1200);
    const quadro2 = await hash();
    expect(quadro2, "o tique é de ~1 s — 1,2 s depois já difere de novo").not.toBe(quadro1);
  });

  test("PW-OP-08: reset layout zera a escala Y fixada e remove a preferência persistida", async ({
    page,
  }) => {
    const chaveStorage = `ottima.operate.escalas.v1:${String(flowId)}/${BLOCK_ID}`;
    const linhaCv = page.locator(
      '[data-testid="operate-trend-legend-item"][data-var-id="cv_1"]',
    );

    await linhaCv.getByTestId("operate-escala-auto").uncheck();
    await linhaCv.getByTestId("operate-escala-min").fill("10");
    await linhaCv.getByTestId("operate-escala-max").fill("90");
    await expect
      .poll(async () =>
        page.evaluate(
          (chave) => window.localStorage.getItem(chave),
          chaveStorage,
        ),
      )
      .toContain('"cv_1"');

    // Desliza para trás (vista congelada) e reseta: volta ao vivo, escala auto, storage limpo.
    await page.getByTestId("operate-janela-voltar").click();
    await expect(page.getByTestId("operate-janela-avancar")).toBeEnabled();
    await page.getByTestId("operate-janela-reset").click();

    await expect(linhaCv.getByTestId("operate-escala-auto")).toBeChecked();
    await expect(linhaCv.getByTestId("operate-escala-min")).toBeDisabled();
    await expect(page.getByTestId("operate-janela-avancar")).toBeDisabled();
    await expect
      .poll(async () => page.evaluate((chave) => window.localStorage.getItem(chave), chaveStorage))
      .toBeNull();
  });

  test("PW-OP-09: janela por valor + unidade (segundos/minutos) dirige a consulta de histórico", async ({
    page,
  }) => {
    await expect(page.getByTestId("operate-trend-window")).toHaveCount(0);

    const valor = page.getByTestId("operate-janela-valor");
    const unidade = page.getByTestId("operate-janela-unidade");
    await expect(valor).toHaveValue("30");
    await expect(unidade).toHaveValue("min");
    await expect(valor).toHaveAttribute("min", "1");

    const consultas: URL[] = [];
    page.on("request", (requisicao) => {
      const url = new URL(requisicao.url());
      if (url.pathname === "/api/history/mpc") consultas.push(url);
    });

    await valor.fill("45");
    await unidade.selectOption("seg");
    await expect
      .poll(() => consultas.length, { message: "consulta com janela de 45 s" })
      .toBeGreaterThan(0);
    let ultima = consultas.at(-1)!;
    let janelaS =
      (Date.parse(ultima.searchParams.get("end") ?? "") -
        Date.parse(ultima.searchParams.get("start") ?? "")) / 1000;
    expect(Math.round(janelaS)).toBe(45);

    await valor.fill("2");
    await unidade.selectOption("min");
    await expect
      .poll(() => consultas.length, { message: "consulta com janela de 2 min" })
      .toBeGreaterThan(1);
    ultima = consultas.at(-1)!;
    janelaS =
      (Date.parse(ultima.searchParams.get("end") ?? "") -
        Date.parse(ultima.searchParams.get("start") ?? "")) / 1000;
    expect(Math.round(janelaS)).toBe(120);
  });
});
