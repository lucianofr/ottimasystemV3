import { expect, test, type Page } from "@playwright/test";

import {
  criarAmbiente,
  entrarNoShell,
  escalaXDoGrafico,
  NODES,
  type AmbienteE2E,
} from "./fixtures";

/**
 * PW-FZ-01..05 — página FUZZY OPERATE (ADR-030): combobox de blocos fuzzy do projeto ativo,
 * painéis de função de pertinência por variável (entrada e saída), badges das normas do rule
 * block, tabela de regras e trend das portas do bloco (escala Y por variável, eixo Y por foco,
 * valor no cursor e zoom — os mesmos recursos do trend de engenharia).
 *
 * Grafo mínimo: 1 `opc_read` alimentando `IN1` de DOIS blocos `fuzzy` independentes (mesmo
 * padrão de `operate-mpc-select.spec.ts`) — sem deploy, então nada é publicado no canal
 * `fuzzy.state.*` e o spec exercita só o que vem da introspecção do FLL (`GET /api/operate/
 * fuzzy…`), nunca valores ao vivo. A animação por execução é coberta pela L2
 * (`tests/e2e/test_fuzzy.py::test_e2e_fz_03_canal_fuzzy_state_publica_estado_do_motor`), que
 * tem stack real com flow rodando.
 *
 * O FLL é o mínimo do repo (1 entrada com 2 termos Triangle, 1 saída Centroid, 2 regras) —
 * geometria conhecida, independente da paleta default, que pode mudar.
 */

let ambiente: AmbienteE2E;
let flowId: number;

const BLOCK_A = "fz-a";
const BLOCK_B = "fz-b";

/** Janela default do trend fuzzy (`JANELA_DEFAULT_SEGUNDOS`, `TrendFuzzy.tsx`). */
const JANELA_30M_S = 1800;

/** Histórico interceptado: este flow nunca é deployado, então `fuzzy_samples` está vazio e
 *  sem dado o uPlot não tem o que recortar nem o que ler no cursor. Pena `i` vale `10·(i+1)`
 *  em 85 carimbos de 5 s terminando 3 min atrás. */
async function interceptarHistoricoFuzzy(page: Page): Promise<void> {
  await page.route("**/api/history/fuzzy?*", async (rota) => {
    const url = new URL(rota.request().url());
    const ids = (url.searchParams.get("var_ids") ?? "")
      .split(",")
      .filter((texto) => texto !== "");
    const fim = Date.now() - 3 * 60_000;
    const carimbos = Array.from({ length: 85 }, (_, i) =>
      new Date(fim - (84 - i) * 5000).toISOString(),
    );
    await rota.fulfill({
      json: {
        mode: "raw",
        start: url.searchParams.get("start"),
        end: url.searchParams.get("end"),
        series: ids.map((varId, indice) => ({
          t: carimbos,
          v: carimbos.map(() => 10 * (indice + 1)),
          var_id: varId,
        })),
      },
    });
  });
}

const FLL = `Engine: minimo
InputVariable: Nivel
  enabled: true
  range: 0.000 100.000
  lock-range: false
  term: baixo Triangle 0.000 0.000 100.000
  term: alto Triangle 0.000 100.000 100.000
OutputVariable: Abertura
  enabled: true
  range: 0.000 100.000
  lock-range: false
  aggregation: Maximum
  defuzzifier: Centroid 200
  default: 0.000
  lock-previous: false
  term: fecha Triangle 0.000 0.000 100.000
  term: abre Triangle 0.000 100.000 100.000
RuleBlock: rb1
  enabled: true
  conjunction: none
  disjunction: none
  implication: Minimum
  activation: General
  rule: if Nivel is baixo then Abertura is fecha
  rule: if Nivel is alto then Abertura is abre`;

function grafo(tagLeituraId: number) {
  function blocoFuzzy(id: string, execOrder: number) {
    return {
      id,
      type: "fuzzy",
      position: { x: 0, y: 0 },
      data: {
        exec_order: execOrder,
        fll: FLL,
        n_inputs: 1,
        n_outputs: 1,
        output_eu: { OUT1: "%" },
      },
    };
  }

  return {
    nodes: [
      {
        id: "leitura",
        type: "opc_read",
        position: { x: 0, y: 0 },
        data: { exec_order: 1, tag_id: tagLeituraId },
      },
      blocoFuzzy(BLOCK_A, 2),
      blocoFuzzy(BLOCK_B, 3),
    ],
    edges: [
      { id: "e1", source: "leitura", sourceHandle: "out", target: BLOCK_A, targetHandle: "IN1" },
      { id: "e2", source: "leitura", sourceHandle: "out", target: BLOCK_B, targetHandle: "IN1" },
    ],
  };
}

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "fuzzy-operate",
    tags: [{ chave: "sine", nodeId: NODES.sine, direcao: "r", tipo: "float" }],
  });

  const criado = await ambiente.api.post("/api/flows", {
    data: { project_id: ambiente.projectId, name: "Flow Fuzzy E2E", ts_seconds: 1 },
  });
  if (!criado.ok()) throw new Error(`criação do flow: HTTP ${criado.status()}`);
  const corpo = (await criado.json()) as { id: number };
  flowId = corpo.id;

  const salvo = await ambiente.api.put(`/api/flows/${String(flowId)}`, {
    data: { graph_json: grafo(ambiente.tags["sine"]) },
  });
  if (!salvo.ok()) {
    throw new Error(`salvar grafo do flow: HTTP ${salvo.status()} — ${await salvo.text()}`);
  }
});

test.afterAll(async () => {
  // Sem deploy nesta suíte: o flow nunca chega a "running", então apagar direto não esbarra
  // no 409 de flow rodando (mesmo contrato de `operate-mpc-select.spec.ts`).
  await ambiente.api.delete(`/api/flows/${String(flowId)}`);
  await ambiente.encerrar();
});

test.beforeEach(async ({ page }) => {
  await entrarNoShell(page);
  await page.goto("/operacao/fuzzy");
  await expect(page.getByTestId("fuzzy-operate-page")).toBeVisible();
});

test.describe("Página FUZZY OPERATE", () => {
  test("PW-FZ-01: desenha pertinências, normas e regras do bloco selecionado", async ({
    page,
  }) => {
    // Combobox lista os dois blocos fuzzy do projeto ativo, rotulados `<flow> · <bloco>`.
    const seletor = page.getByTestId("fuzzy-select-bloco");
    await expect(seletor).toBeVisible();
    const opcoes = seletor.locator("option");
    await expect(opcoes).toHaveCount(2);
    await expect(opcoes.nth(0)).toHaveText(new RegExp(`Flow Fuzzy E2E · ${BLOCK_A}`));
    await expect(opcoes.nth(1)).toHaveText(new RegExp(`Flow Fuzzy E2E · ${BLOCK_B}`));

    // Um painel por variável, com o nome vindo do FLL (o frontend nunca parseia FLL).
    const painelEntrada = page.getByTestId("fuzzy-painel-IN1");
    const painelSaida = page.getByTestId("fuzzy-painel-OUT1");
    await expect(painelEntrada).toContainText("Nivel");
    await expect(painelSaida).toContainText("Abertura");
    // Uma curva por termo declarado (2 na entrada, 2 na saída).
    await expect(painelEntrada.locator("polyline")).toHaveCount(2);
    await expect(painelSaida.locator("polyline")).toHaveCount(2);
    // Normas: implicação/ativação do rule block e o defuzzificador da saída.
    await expect(page.getByTestId("fuzzy-badges-rule-block")).toContainText("Minimum");
    await expect(page.getByTestId("fuzzy-badges-rule-block")).toContainText("General");
    await expect(painelSaida.getByTestId("fuzzy-badge-defuzzifier")).toContainText("Centroid");
    await expect(painelSaida.getByTestId("fuzzy-badge-aggregation")).toContainText("Maximum");

    // Regras verbatim do FLL, na ordem de declaração; sem execução, nenhuma domina.
    const linhas = page.getByTestId("fuzzy-regra-linha");
    await expect(linhas).toHaveCount(2);
    await expect(linhas.nth(0)).toContainText("if Nivel is baixo then Abertura is fecha");
    await expect(linhas.nth(1)).toContainText("if Nivel is alto then Abertura is abre");
    await expect(page.getByTestId("fuzzy-regras-ativas")).toContainText("0/2");

    // Trocar de bloco no combobox mantém a página e reflete na URL (`?flow=&bloco=`).
    await seletor.selectOption({ index: 1 });
    await expect(page).toHaveURL(new RegExp(`bloco=${BLOCK_B}`));
    await expect(page.getByTestId("fuzzy-painel-IN1")).toContainText("Nivel");
  });

  test("PW-FZ-02: trend do bloco lista as portas IN/OUT como penas selecionáveis", async ({
    page,
  }) => {
    const trend = page.getByTestId("fuzzy-trend");
    await expect(trend).toBeVisible();
    await expect(trend).toContainText("IN1 — Nivel");
    // EU em coluna própria no seletor (paridade com o trend de engenharia), fora do rótulo.
    const opcaoOut1 = trend.locator('[data-testid="fuzzy-trend-option"][data-var-port="OUT1"]');
    await expect(opcaoOut1).toContainText("OUT1 — Abertura");
    await expect(opcaoOut1).toContainText("%");
    await expect(opcaoOut1).not.toContainText("(%)");
  });

  test("PW-FZ-03: escala Y da grade é manual por variável, persiste por bloco e o reset limpa", async ({
    page,
  }) => {
    // Sem deploy não há amostra, mas a grade tem uma linha por pena selecionada (SEM DADO):
    // o editor de escala é o que o operador toca, e ele existe mesmo sem valor.
    await expect(page).toHaveURL(new RegExp(`bloco=${BLOCK_A}`));
    await expect(page.getByTestId("fuzzy-trend-legend-item")).toHaveCount(2);
    const chave = `ottima.fuzzy.escalas.v1:${String(flowId)}/${BLOCK_A}`;
    const lerChave = () => page.evaluate((k) => window.localStorage.getItem(k), chave);

    const primeiraAuto = page.getByTestId("fuzzy-trend-escala-auto").first();
    const primeiraMin = page.getByTestId("fuzzy-trend-escala-min").first();
    const primeiraMax = page.getByTestId("fuzzy-trend-escala-max").first();
    await expect(primeiraAuto).toBeChecked();
    await expect(primeiraMin).toBeDisabled();

    await primeiraAuto.uncheck();
    await primeiraMin.fill("0");
    await primeiraMax.fill("100");
    // Independência: fixar a faixa de IN1 não tira OUT1 do autoscale.
    await expect(page.getByTestId("fuzzy-trend-escala-auto").nth(1)).toBeChecked();
    await expect.poll(lerChave).not.toBeNull();

    await page.reload();
    await expect(page.getByTestId("fuzzy-trend-escala-auto").first()).not.toBeChecked();
    await expect(page.getByTestId("fuzzy-trend-escala-min").first()).toHaveValue("0");
    await expect(page.getByTestId("fuzzy-trend-escala-max").first()).toHaveValue("100");

    // Outro bloco é outra grandeza: não herda a escala de fz-a.
    await page.getByTestId("fuzzy-select-bloco").selectOption({ index: 1 });
    await expect(page).toHaveURL(new RegExp(`bloco=${BLOCK_B}`));
    await expect(page.getByTestId("fuzzy-trend-escala-auto").first()).toBeChecked();
    await page.getByTestId("fuzzy-select-bloco").selectOption({ index: 0 });
    await expect(page.getByTestId("fuzzy-trend-escala-auto").first()).not.toBeChecked();

    await page.getByTestId("fuzzy-trend-janela-reset").click();
    await expect(page.getByTestId("fuzzy-trend-escala-auto").first()).toBeChecked();
    await expect(page.getByTestId("fuzzy-trend-escala-min").first()).toBeDisabled();
    await expect.poll(lerChave).toBeNull();
  });

  test("PW-FZ-04: zoom por arrasto no trend fuzzy volta pelo Reset layout da própria tela", async ({
    page,
  }) => {
    // Regressão: o `TrendChart` é compartilhado pelas três telas de trend e rastreia o recorte
    // do arrasto num ref próprio; o aviso manda usar "Reset layout". Sem o `resetZoom` no
    // handler desta tela, o recorte ficava preso para sempre.
    await interceptarHistoricoFuzzy(page);
    await page.reload();

    const tela = page.getByTestId("trend-chart").locator(".u-over");
    await expect(tela).toBeVisible();
    const caixa = await tela.boundingBox();
    if (caixa === null) throw new Error("área de interação do trend fuzzy sem caixa");
    const meioY = caixa.y + caixa.height / 2;

    await page.mouse.move(caixa.x + caixa.width * 0.3, meioY);
    await page.mouse.down();
    await page.mouse.move(caixa.x + caixa.width * 0.6, meioY, { steps: 10 });
    await page.mouse.up();
    await expect(page.getByTestId("trend-zoom")).toBeVisible();
    const recorte = await escalaXDoGrafico(page, "trend-chart");
    expect(recorte.max - recorte.min).toBeLessThan(JANELA_30M_S / 2);

    await page.getByTestId("fuzzy-trend-janela-reset").click();
    await expect(page.getByTestId("trend-zoom")).toHaveCount(0);
    const solto = await escalaXDoGrafico(page, "trend-chart");
    expect(Math.round(solto.max - solto.min)).toBe(JANELA_30M_S);
  });

  test("PW-FZ-05: eixo Y único por foco na grade e valor no cursor, como no trend de engenharia", async ({
    page,
  }) => {
    await interceptarHistoricoFuzzy(page);
    await page.reload();

    const linha = (porta: string) =>
      page.locator(`[data-testid="fuzzy-trend-legend-item"][data-var-port="${porta}"]`);
    const eixoDe = (porta: string) => linha(porta).getByRole("button");
    // A primeira porta pré-selecionada nasce dona do eixo.
    await expect(eixoDe("IN1")).toHaveAttribute("aria-current", "true");
    await expect(eixoDe("OUT1")).not.toHaveAttribute("aria-current");

    // Clicar no nome traz o eixo sem tirar a pena do gráfico.
    await eixoDe("OUT1").click();
    await expect(eixoDe("OUT1")).toHaveAttribute("aria-current", "true");
    await expect(eixoDe("IN1")).not.toHaveAttribute("aria-current");
    await expect(page.getByTestId("fuzzy-trend-legend-item")).toHaveCount(2);

    // Desmarcar a dona passa o eixo para a porta que sobrou.
    await page.locator('[data-testid="fuzzy-trend-option"][data-var-port="OUT1"] input').uncheck();
    await expect(eixoDe("IN1")).toHaveAttribute("aria-current", "true");

    // Leitura no cursor: o histórico interceptado vale 10 na IN1 em toda a janela com dado.
    const tela = page.getByTestId("trend-chart").locator(".u-over");
    const caixa = await tela.boundingBox();
    if (caixa === null) throw new Error("área de interação do trend fuzzy sem caixa");
    await page.mouse.move(caixa.x + caixa.width * 0.8, caixa.y + caixa.height / 2);
    await expect(page.getByTestId("fuzzy-trend-legend-valor-cursor").first()).toHaveText("10");
  });
});
