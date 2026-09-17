import { expect, test, type Page } from "@playwright/test";

import {
  criarAmbiente,
  entrarNoShell,
  escalaXDoGrafico,
  NODES,
  type AmbienteE2E,
} from "./fixtures";

/**
 * PW-TR-01/02 — trend de engenharia: escala Y por variável e janela deslizante.
 *
 * O eixo por tag é desenhado no canvas do uPlot, não no DOM, então a prova estrutural
 * ("uma escala e um eixo por tag") é do check unitário `trendTheme.check.ts::montarEixosValor`.
 * Aqui prova-se o que o engenheiro toca: a área de plotagem encolhe quando um eixo entra, o
 * editor de escala é independente por linha e sobrevive ao reload, e o pan desliga o polling.
 */

const JANELA_30M_S = 1800;

let ambiente: AmbienteE2E;

test.beforeAll(async ({ baseURL }) => {
  ambiente = await criarAmbiente(baseURL!, {
    sufixo: "trend",
    tags: [
      { chave: "sine", nodeId: NODES.sine, direcao: "r" },
      { chave: "static", nodeId: NODES.static, direcao: "r" },
    ],
  });
});

test.afterAll(async () => {
  await ambiente.encerrar();
});

test.beforeEach(async ({ page }) => {
  // Nada de `addInitScript` para limpar as escalas: ele reexecuta a CADA navegação, inclusive
  // no `page.reload()` do PW-TR-01, e apagaria justamente a preferência que aquele teste
  // acabou de gravar. O isolamento já vem do Playwright — cada teste recebe um contexto novo,
  // e o `playwright.config.ts` não define `storageState`, então o localStorage nasce vazio.
  await entrarNoShell(page);
  await page.goto("/engenharia/trend");
});

async function marcarTag(page: Page, tagId: number): Promise<void> {
  await page
    .locator(`[data-testid="trend-tag-option"][data-tag-id="${String(tagId)}"] input`)
    .check();
}

test.describe("Trend de engenharia", () => {
  test("PW-TR-01: escala Y é editável e independente por variável, e persiste", async ({
    page,
  }) => {
    await marcarTag(page, ambiente.tags["sine"]);
    await expect(page.getByTestId("trend-legend-item")).toHaveCount(1);

    await marcarTag(page, ambiente.tags["static"]);
    await expect(page.getByTestId("trend-legend-item")).toHaveCount(2);
    // O eixo Y por tag é desenhado NO CANVAS (o uPlot não cria nó DOM por eixo — não existe
    // `.u-axis` na lib), e o espaço que ele ocupa depende de a tag já ter amostra gravada.
    // Contar eixo por aqui vira gate que reprova quando o recorder ainda não gravou nada: a
    // estrutura (uma escala e um eixo por tag, com a cor da pena) é provada de forma
    // determinística pelo check unitário `trendTheme.check.ts::montarEixosValor`. O que este
    // cenário prova é o que o engenheiro TOCA — e que o gráfico sobrevive à segunda pena.
    await expect(page.getByTestId("trend-chart")).toBeVisible();

    const primeiraAuto = page.getByTestId("trend-escala-auto").first();
    const primeiraMin = page.getByTestId("trend-escala-min").first();
    const primeiraMax = page.getByTestId("trend-escala-max").first();
    const segundaMin = page.getByTestId("trend-escala-min").nth(1);

    await expect(primeiraAuto).toBeChecked();
    await expect(primeiraMin).toBeDisabled();

    await primeiraAuto.uncheck();
    await expect(primeiraMin).toBeEnabled();
    await primeiraMin.fill("0");
    await primeiraMax.fill("100");

    // Independência: fixar a faixa de uma variável não tira a outra do autoscale.
    await expect(page.getByTestId("trend-escala-auto").nth(1)).toBeChecked();
    await expect(segundaMin).toBeDisabled();

    await page.reload();
    await expect(page.getByTestId("trend-legend-item")).toHaveCount(0);
    await marcarTag(page, ambiente.tags["sine"]);
    await expect(page.getByTestId("trend-legend-item")).toHaveCount(1);

    // Persistência por navegador: a faixa fixada volta com o reload.
    await expect(page.getByTestId("trend-escala-auto").first()).not.toBeChecked();
    await expect(page.getByTestId("trend-escala-min").first()).toHaveValue("0");
    await expect(page.getByTestId("trend-escala-max").first()).toHaveValue("100");
  });

  test("PW-TR-02: voltar congela a janela e desliga o polling; reset volta ao vivo", async ({
    page,
  }) => {
    const consultas: URL[] = [];
    page.on("request", (requisicao) => {
      const url = new URL(requisicao.url());
      if (url.pathname === "/api/history") consultas.push(url);
    });

    await marcarTag(page, ambiente.tags["sine"]);
    await expect(page.getByTestId("trend-legend-item")).toHaveCount(1);

    // Ao vivo, `avancar` não tem o que fazer; `reset` fica HABILITADO ao vivo desde o lote
    // do reset completo (zera zoom X + escalas Y — o zoom manual do uPlot é independente de
    // `aoVivo`, então o botão morto ao vivo era exatamente quando ele era preciso).
    await expect(page.getByTestId("trend-janela-avancar")).toBeDisabled();
    await expect(page.getByTestId("trend-janela-reset")).toBeEnabled();

    await page.getByTestId("trend-janela-voltar").click();
    await page.getByTestId("trend-janela-voltar").click();
    await expect(page.getByTestId("trend-janela-avancar")).toBeEnabled();

    await expect
      .poll(() => consultas.length, { message: "consulta da janela deslizada" })
      .toBeGreaterThan(1);
    const deslizada = consultas.at(-1)!;
    const fim = Date.parse(deslizada.searchParams.get("end") ?? "");
    const inicio = Date.parse(deslizada.searchParams.get("start") ?? "");
    // Dois cliques = uma janela inteira para trás.
    expect(Date.now() - fim).toBeGreaterThan((JANELA_30M_S / 2) * 1000);
    expect(Math.round((fim - inicio) / 1000)).toBe(JANELA_30M_S);

    // Polling desligado: a vista congelada não pode continuar puxando `end = agora`.
    const antes = consultas.length;
    await page.waitForTimeout(7000);
    expect(consultas.length, "polling deveria estar pausado na vista congelada").toBe(antes);

    await page.getByTestId("trend-janela-reset").click();
    // O reset não tem mais estado desabilitado: ao vivo ele continua clicável (idempotente).
    await expect(page.getByTestId("trend-janela-reset")).toBeEnabled();
    await expect(page.getByTestId("trend-janela-avancar")).toBeDisabled();
    await expect
      .poll(() => consultas.length, { message: "consulta ao voltar para o modo ao vivo" })
      .toBeGreaterThan(antes);
    const aoVivo = consultas.at(-1)!;
    expect(Date.now() - Date.parse(aoVivo.searchParams.get("end") ?? "")).toBeLessThan(30_000);
  });

  test("PW-TR-03: reset ao vivo zera a escala Y fixada e limpa a preferência persistida", async ({
    page,
  }) => {
    await marcarTag(page, ambiente.tags["sine"]);
    await expect(page.getByTestId("trend-legend-item")).toHaveCount(1);

    const auto = page.getByTestId("trend-escala-auto").first();
    const min = page.getByTestId("trend-escala-min").first();
    await auto.uncheck();
    await min.fill("0");
    await page.getByTestId("trend-escala-max").first().fill("100");
    await expect
      .poll(async () =>
        page.evaluate(() => window.localStorage.getItem("ottima.trend.escalas.v1")),
      )
      .not.toBeNull();

    // Reset AO VIVO (o botão não tem mais estado desabilitado): escala volta a auto e a
    // chave some do localStorage — o reload não pode ressuscitar a escala apagada.
    await page.getByTestId("trend-janela-reset").click();
    await expect(page.getByTestId("trend-escala-auto").first()).toBeChecked();
    await expect(page.getByTestId("trend-escala-min").first()).toBeDisabled();
    await expect
      .poll(async () =>
        page.evaluate(() => window.localStorage.getItem("ottima.trend.escalas.v1")),
      )
      .toBeNull();

    await page.reload();
    await marcarTag(page, ambiente.tags["sine"]);
    await expect(page.getByTestId("trend-escala-auto").first()).toBeChecked();
  });

  test("PW-TR-04: janela por valor + unidade, granularidade livre (90 s, 24 min)", async ({
    page,
  }) => {
    await expect(page.getByTestId("trend-window")).toHaveCount(0);
    const valor = page.getByTestId("trend-janela-valor");
    const unidade = page.getByTestId("trend-janela-unidade");
    await expect(valor).toHaveValue("30");
    await expect(unidade).toHaveValue("min");
    await expect(valor).toHaveAttribute("min", "1");

    // Listener ANTES de marcar a tag: a consulta inicial dispara no check e o refetch ao
    // vivo pode demorar mais que o timeout default do poll.
    const consultas: URL[] = [];
    page.on("request", (requisicao) => {
      const url = new URL(requisicao.url());
      if (url.pathname === "/api/history") consultas.push(url);
    });
    await marcarTag(page, ambiente.tags["sine"]);
    await expect.poll(() => consultas.length).toBeGreaterThan(0);

    await valor.fill("90");
    await unidade.selectOption("seg");
    await expect
      .poll(() => consultas.length, { message: "consulta com janela de 90 s" })
      .toBeGreaterThan(1);
    let ultima = consultas.at(-1)!;
    let janelaS =
      (Date.parse(ultima.searchParams.get("end") ?? "") -
        Date.parse(ultima.searchParams.get("start") ?? "")) / 1000;
    expect(Math.round(janelaS)).toBe(90);

    // 24 min não existia no enum antigo de presets — prova a granularidade livre.
    await valor.fill("24");
    await unidade.selectOption("min");
    await expect
      .poll(() => consultas.length, { message: "consulta com janela de 24 min" })
      .toBeGreaterThan(2);
    ultima = consultas.at(-1)!;
    janelaS =
      (Date.parse(ultima.searchParams.get("end") ?? "") -
        Date.parse(ultima.searchParams.get("start") ?? "")) / 1000;
    expect(Math.round(janelaS)).toBe(1440);
  });

  test("PW-TR-05: leitura no cursor, vista seguindo o relógio e zoom que congela até o duplo-clique", async ({
    page,
  }) => {
    // Histórico DETERMINADO por interceptação: o valor no cursor é a entrega central desta
    // tela e não pode depender de o recorder já ter gravado dado bom (e muito menos do
    // opcsim). Duas penas com valores constantes e DISJUNTOS provam também o mapeamento
    // pena→coluna: a pena `indice` desenha a coluna `indice + 1`, e uma troca de coluna
    // apareceria como 93,5 na linha da primeira pena.
    const VALOR_PENA = [41.25, 93.5] as const;
    // Bloco de amostras encerrado 3 min antes de agora: fica longe da borda viva do WS, então
    // o carimbo sob o ponteiro é sempre um ponto interceptado, nunca um ponto vivo.
    const FIM_BLOCO_MS = 3 * 60_000;
    await page.route("**/api/history?*", async (rota) => {
      const url = new URL(rota.request().url());
      const ids = (url.searchParams.get("tag_ids") ?? "")
        .split(",")
        .filter((texto) => texto !== "")
        .map(Number);
      const fim = Date.now() - FIM_BLOCO_MS;
      // 7 min a cada 5 s: abaixo do teto de carry-forward do modo bruto (20 s), então nenhuma
      // marca de silêncio cai DENTRO do bloco (elas são `null` por construção e esvaziariam a
      // coluna do cursor sem que nada estivesse errado).
      const carimbos = Array.from({ length: 85 }, (_, i) =>
        new Date(fim - (84 - i) * 5000).toISOString(),
      );
      await rota.fulfill({
        json: {
          mode: "raw",
          start: url.searchParams.get("start"),
          end: url.searchParams.get("end"),
          series: ids.map((tagId, indice) => ({
            tag_id: tagId,
            t: carimbos,
            v: carimbos.map(() => VALOR_PENA[indice] ?? 0),
            q: carimbos.map(() => 0),
          })),
        },
      });
    });

    await marcarTag(page, ambiente.tags["sine"]);
    await marcarTag(page, ambiente.tags["static"]);
    await expect(page.getByTestId("trend-legend-item")).toHaveCount(2);

    // `.u-over` é a camada de interação do uPlot (o canvas inclui os eixos, e `page.mouse` não
    // rola a página sozinho como o `click` de um locator faz).
    const tela = page.getByTestId("trend-chart").locator(".u-over");
    await expect(tela).toBeVisible();
    const caixa = await tela.boundingBox();
    if (caixa === null) throw new Error("área de interação do trend sem caixa delimitadora");
    const meioY = caixa.y + caixa.height / 2;
    const carimboEm = async (fracao: number): Promise<string | null> => {
      // Dois movimentos: o uPlot só reemite `setCursor` quando o ponteiro muda de posição.
      await page.mouse.move(caixa.x + caixa.width * (fracao - 0.01), meioY);
      await page.mouse.move(caixa.x + caixa.width * fracao, meioY);
      return page.getByTestId("trend-cursor-hora").textContent();
    };

    // Hover em 0,8 da janela de 30 min ≈ agora − 6 min: dentro do bloco interceptado.
    const chips = page.getByTestId("trend-legend-valor-cursor");
    await expect.poll(async () => carimboEm(0.8)).toMatch(/^\d{2}:\d{2}:\d{2}$/);
    await expect(chips.nth(0)).toHaveText("41,25");
    await expect(chips.nth(1)).toHaveText("93,5");
    // Ponteiro fora da área de plotagem: a coluna do cursor esvazia (o valor corrente fica).
    await page.mouse.move(caixa.x + caixa.width / 2, caixa.y + caixa.height + 150);
    await expect(page.getByTestId("trend-cursor-hora")).toHaveCount(0);
    await expect(chips.nth(0)).toBeEmpty();
    await expect(chips.nth(1)).toBeEmpty();

    // Ao vivo a janela é a ESCOLHIDA no seletor e anda com o relógio — não é a extensão do
    // dado (o defeito: com `range` automático, uma janela de 30 min sobre 5 min de histórico
    // desenhava 5 min esticados, e a borda direita só mexia quando chegava amostra).
    const escala = async () => escalaXDoGrafico(page, "trend-chart");
    const aoVivo = await escala();
    expect(Math.round(aoVivo.max - aoVivo.min)).toBe(JANELA_30M_S);
    await expect
      .poll(async () => (await escala()).max, { message: "borda direita seguindo o relógio" })
      .toBeGreaterThan(aoVivo.max);

    // Zoom por arrasto: recorta o eixo de verdade (o aviso sozinho não provaria nada) e a
    // vista congela — dado novo do polling não pode piscar de volta para a janela cheia.
    await page.mouse.move(caixa.x + caixa.width * 0.3, meioY);
    await page.mouse.down();
    await page.mouse.move(caixa.x + caixa.width * 0.6, meioY, { steps: 10 });
    await page.mouse.up();
    await expect(page.getByTestId("trend-zoom")).toBeVisible();
    const recorte = await escala();
    expect(recorte.max - recorte.min).toBeLessThan(JANELA_30M_S / 2);
    await page.waitForTimeout(6000);
    expect(await escala()).toEqual(recorte);

    // Duplo-clique solta o recorte e a vista volta a seguir o relógio.
    await page.mouse.dblclick(caixa.x + caixa.width / 2, meioY);
    await expect(page.getByTestId("trend-zoom")).toHaveCount(0);
    const solto = await escala();
    expect(Math.round(solto.max - solto.min)).toBe(JANELA_30M_S);
    expect(solto.max).toBeGreaterThan(recorte.max);
  });
});
