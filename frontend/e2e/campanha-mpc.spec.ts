import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { entrarNoShell } from "./fixtures";

/**
 * Capturador de evidência da campanha de comissionamento do MPC (planta debutanizadora,
 * projeto 1 / flow 1 / bloco `mpc1`, ao vivo — ver CONTEXT do assignment). NÃO é um teste de
 * regressão: não afirma modo, nem presença de predição, nem valor de nenhuma variável de
 * processo — só que a tela carrega e os elementos existem. Rodado várias vezes pelo Main ao
 * longo da campanha, uma vez por etapa, cada rodada gravando em seu próprio diretório
 * (`artifacts/campanha/<etapa>/`) via `CAMPANHA_ETAPA`.
 *
 * Somente leitura: nunca clica em `faceplate-modo-*` (comutadores de modo do bloco mpc1) —
 * só no select da janela do trend e nos botões de navegação da própria tela de tendência.
 */

const FLOW_ID = 1;
const BLOCK_ID = "mpc1";

const ETAPA = process.env.CAMPANHA_ETAPA ?? "sem-etapa";
const DIR_ESTE_ARQUIVO = path.dirname(fileURLToPath(import.meta.url));
const DIR_SAIDA = path.resolve(DIR_ESTE_ARQUIVO, "..", "artifacts", "campanha", ETAPA);

/** Lê a posição ativa de um `Comutador` (`aria-pressed="true"` no segmento exibido) — `null`
 *  quando o comutador nem está montado (MAN/AUTO só existe em REMOTO, ADR-010). */
async function lerPosicaoComutador(page: Page, testid: string): Promise<string | null> {
  const raiz = page.getByTestId(testid);
  if ((await raiz.count()) === 0) return null;
  const segmentos = raiz.locator("button");
  const total = await segmentos.count();
  for (let i = 0; i < total; i++) {
    const segmento = segmentos.nth(i);
    if ((await segmento.getAttribute("aria-pressed")) === "true") {
      return (await segmento.textContent())?.trim() ?? null;
    }
  }
  return null;
}

async function textoOu(locator: Locator, rotulo: string): Promise<string> {
  return (await locator.textContent())?.trim() ?? `<${rotulo} ausente>`;
}

test("registra a tendencia da planta sob MPC", async ({ page }) => {
  // O canal ao vivo (`CanalAoVivo.tsx`) nunca reenvia um snapshot retido ao assinar — o
  // primeiro `mpc_state` do bloco só chega na próxima publicação, cadenciada por `Ts_mpc`
  // (até 120s neste bloco). O timeout do teste precisa cobrir essa espera.
  test.setTimeout(180_000);
  mkdirSync(DIR_SAIDA, { recursive: true });

  await entrarNoShell(page);
  await page.goto(`/operacao/${String(FLOW_ID)}/${BLOCK_ID}`);

  const paginaOperacao = page.getByTestId("operate-page");
  const faceplate = page.getByTestId("faceplate-principal");
  await expect(paginaOperacao).toBeVisible();
  await expect(faceplate).toBeVisible();

  // Espera o primeiro `mpc_state` chegar pelo canal ao vivo antes de ler qualquer valor
  // dependente dele (lâmpadas, modos, overruns, last_solve_ms, seções do trend): sem esta
  // espera, a leitura captura só o placeholder pré-hidratação ("—"/LOCAL/Ocioso), não o
  // estado real do processo — o que já produziu evidência falsa numa rodada anterior. Não é
  // uma asserção de modo: só espera existir QUALQUER estado publicado, tolerante ao que ele
  // for. Se não chegar dentro do prazo, a captura segue mesmo assim (registrado no resumo).
  const overrunsLocator = page.getByTestId("faceplate-overruns");
  let mpcStateHidratado = true;
  try {
    await expect
      .poll(async () => (await overrunsLocator.textContent())?.trim(), {
        message: "aguardando o primeiro mpc.state publicado no canal ao vivo",
        timeout: 150_000,
      })
      .not.toBe("—");
  } catch {
    mpcStateHidratado = false;
  }
  console.log(`CAMPANHA: mpc_state_hidratado=${String(mpcStateHidratado)}`);

  const plaqueta = await textoOu(page.getByTestId("faceplate-plaqueta"), "plaqueta");
  const tsMpc = await textoOu(page.getByTestId("faceplate-ts-mpc"), "ts-mpc");
  const horizontes = await textoOu(page.getByTestId("faceplate-horizontes"), "horizontes");
  const overruns = await textoOu(page.getByTestId("faceplate-overruns"), "overruns");
  const lastSolveMs = await textoOu(page.getByTestId("faceplate-last-solve-ms"), "last-solve-ms");
  const lampadaFlow = await textoOu(page.getByTestId("faceplate-lampada-flow"), "lampada-flow");
  const lampadaSolver = await textoOu(page.getByTestId("faceplate-lampada-solver"), "lampada-solver");
  const lampadaInputValido = await textoOu(
    page.getByTestId("faceplate-lampada-input-valido"),
    "lampada-input-valido",
  );
  const modoLocalRemoto = await lerPosicaoComutador(page, "faceplate-modo-local-remoto");
  const modoManAuto = await lerPosicaoComutador(page, "faceplate-modo-man-auto");

  console.log(`CAMPANHA: etapa=${ETAPA}`);
  console.log(`CAMPANHA: plaqueta=${plaqueta}`);
  console.log(`CAMPANHA: ts_mpc=${tsMpc}`);
  console.log(`CAMPANHA: horizontes=${horizontes}`);
  console.log(`CAMPANHA: modo_local_remoto=${modoLocalRemoto ?? "ausente"}`);
  console.log(`CAMPANHA: modo_man_auto=${modoManAuto ?? "ausente (fora de REMOTO)"}`);
  console.log(`CAMPANHA: overruns=${overruns}`);
  console.log(`CAMPANHA: last_solve_ms=${lastSolveMs}`);
  console.log(`CAMPANHA: lampada_flow=${lampadaFlow}`);
  console.log(`CAMPANHA: lampada_solver=${lampadaSolver}`);
  console.log(`CAMPANHA: lampada_input_valido=${lampadaInputValido}`);

  // Janela de maior alcance disponível: lê as opções do próprio select em vez de assumir a
  // ordem (`JANELAS_OPERACAO` — cresce da esquerda para a direita hoje, mas o select é a
  // fonte real).
  const seletorJanela = page.getByTestId("operate-trend-window");
  const opcoesJanela = await seletorJanela.locator("option").allTextContents();
  const ultimaOpcao = opcoesJanela.at(-1);
  if (ultimaOpcao === undefined) throw new Error("operate-trend-window sem opções");
  await seletorJanela.selectOption({ label: ultimaOpcao });
  console.log(`CAMPANHA: janela_selecionada=${ultimaOpcao}`);

  const trendChart = page.getByTestId("operate-trend-chart");
  await expect(trendChart).toBeVisible();
  const itensLegenda = page.getByTestId("operate-trend-legend-item");
  await expect
    .poll(async () => itensLegenda.count(), { message: "legenda com variáveis", timeout: 15_000 })
    .toBeGreaterThanOrEqual(4);

  const idsLegenda = await itensLegenda.evaluateAll((elementos) =>
    elementos.map((elemento) => elemento.getAttribute("data-var-id")),
  );
  console.log(`CAMPANHA: ids_legenda=${idsLegenda.join(",")}`);
  console.log(`CAMPANHA: legenda_contagem=${String(idsLegenda.length)}`);

  const secaoFuturaVisivel = await page.getByTestId("operate-trend-secao-futura").isVisible();
  const semPredicaoVisivel = await page.getByTestId("operate-trend-sem-predicao").isVisible();
  console.log(`CAMPANHA: secao_futura_visivel=${String(secaoFuturaVisivel)}`);
  console.log(`CAMPANHA: sem_predicao_visivel=${String(semPredicaoVisivel)}`);

  // Relógio avança: dois reads diferentes (`RelogioAgora`, tique de 1s) — único invariante de
  // "tempo real" que este spec afirma.
  const relogio = page.getByTestId("faceplate-relogio");
  const leituraInicial = await relogio.textContent();
  await expect
    .poll(() => relogio.textContent(), { message: "relógio de 1s avança" })
    .not.toBe(leituraInicial);
  const leituraFinal = await relogio.textContent();
  console.log(`CAMPANHA: relogio_inicial=${leituraInicial ?? ""}`);
  console.log(`CAMPANHA: relogio_final=${leituraFinal ?? ""}`);

  await page.screenshot({ path: path.join(DIR_SAIDA, "pagina.png"), fullPage: true });
  await faceplate.screenshot({ path: path.join(DIR_SAIDA, "faceplate.png") });
  await trendChart.screenshot({ path: path.join(DIR_SAIDA, "trend.png") });
  await page.getByTestId("operate-trend-legend").screenshot({ path: path.join(DIR_SAIDA, "legenda.png") });

  const resumo = {
    etapa: ETAPA,
    capturado_em: new Date().toISOString(),
    mpc_state_hidratado: mpcStateHidratado,
    plaqueta,
    ts_mpc: tsMpc,
    horizontes,
    modos: { local_remote: modoLocalRemoto, man_auto: modoManAuto },
    overruns,
    last_solve_ms: lastSolveMs,
    lampadas: { flow: lampadaFlow, solver: lampadaSolver, input_valido: lampadaInputValido },
    janela_selecionada: ultimaOpcao,
    legenda_ids: idsLegenda,
    legenda_contagem: idsLegenda.length,
    secao_futura_visivel: secaoFuturaVisivel,
    sem_predicao_visivel: semPredicaoVisivel,
    relogio: { inicial: leituraInicial, final: leituraFinal },
  };
  writeFileSync(path.join(DIR_SAIDA, "resumo.json"), JSON.stringify(resumo, null, 2));
});
