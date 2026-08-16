import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import type { MpcHistoryResponse } from "../../lib/api";
import type { MpcPrediction } from "../../lib/contracts.gen";
import {
  CUSTO_PENAS,
  OPCOES_DEGRAU_MV,
  TETO_PENAS_OPERACAO,
  TOKENS_PENA_OPERACAO,
  TRACO_SP,
  alinharNoEixo,
  atribuirCoresPenas,
  dividirSpPorAuto,
  emendarPlanoNoDivisor,
  faixaPontilhadaSp,
  idPenaSp,
  mesclarSeriesVivas,
  montarOverlayPrevisao,
  selecionarPenasDefault,
  tetoCarryForwardOperacaoS,
  tracoPenaSp,
  ultimoCarimboHistorico,
  type AmostraViva,
} from "./trendOperacao";
import { chaveHistoricoOperacao } from "./useHistoryMpc";

/** Base arbitrária: só os deslocamentos em segundos importam (mesmo padrão de useHistory.check.ts). */
const T0 = Date.parse("2026-01-01T12:00:00Z") / 1000;

function carimbo(deslocamentoS: number): string {
  return new Date((T0 + deslocamentoS) * 1000).toISOString();
}

interface Ponto {
  readonly d: number;
  readonly v: number;
  readonly sp: number | null;
  readonly auto: boolean;
}

function historico(varId: string, pontos: readonly Ponto[]): MpcHistoryResponse {
  return {
    mode: "raw",
    start: carimbo(0),
    end: carimbo(pontos[pontos.length - 1]?.d ?? 0),
    series: [
      {
        var_id: varId,
        t: pontos.map((p) => carimbo(p.d)),
        v: pontos.map((p) => p.v),
        sp: pontos.map((p) => p.sp),
        auto: pontos.map((p) => p.auto),
      },
    ],
  };
}

function amostraViva(d: number, v: number, sp: number | null, auto: boolean): AmostraViva {
  return { ts: carimbo(d), vars: { cv_1: { v, sp, status: null } }, auto };
}

test("ponta viva OPC: pontos adensados entram na série sem buraco de SP/modo", () => {
  const resp = historico("cv_1", [{ d: 0, v: 1, sp: 1.5, auto: true }]);
  const vivas: AmostraViva[] = [amostraViva(10, 1.2, 1.5, true)];
  const opc = new Map([["cv_1", [{ t: T0 + 12, v: 1.25 }, { t: T0 + 14, v: 1.3 }]]]);
  const [serie] = mesclarSeriesVivas(resp, vivas, ["cv_1"], opc);
  expect(serie.t).toEqual([T0, T0 + 10, T0 + 12, T0 + 14]);
  expect(serie.v).toEqual([1, 1.2, 1.25, 1.3]);
  // SP e modo dos pontos OPC herdam o último conhecido (só mudam na cadência do MPC).
  expect(serie.sp).toEqual([1.5, 1.5, 1.5, 1.5]);
  expect(serie.auto).toEqual([true, true, true, true]);
});

test("ponta viva OPC: ponto em ts já coberto pelo mpc.state não duplica (state manda)", () => {
  const resp = historico("cv_1", []);
  const vivas: AmostraViva[] = [amostraViva(10, 1.2, 1.5, true)];
  const opc = new Map([["cv_1", [{ t: T0 + 10, v: 9.9 }]]]);
  const [serie] = mesclarSeriesVivas(resp, vivas, ["cv_1"], opc);
  expect(serie.t).toEqual([T0 + 10]);
  expect(serie.v).toEqual([1.2]);
});

test("ponta viva OPC: sem pontos novos a série é idêntica à de antes", () => {
  const resp = historico("cv_1", [{ d: 0, v: 1, sp: 1.5, auto: false }]);
  const vivas: AmostraViva[] = [amostraViva(10, 1.2, 1.6, true)];
  const [semOpc] = mesclarSeriesVivas(resp, vivas, ["cv_1"]);
  const [comOpcVazio] = mesclarSeriesVivas(resp, vivas, ["cv_1"], new Map());
  expect(comOpcVazio).toEqual(semOpc);
});

// --------------------------------------------------- eixo x compartilhado (carry-forward, §7.4-6)

test("eixo compartilhado: pena sem tag OPC repete o último valor nos carimbos das penas adensadas", () => {
  // Regressão: uma CV alimentada por script (sem tag OPC) só tem carimbo na cadência do MPC,
  // enquanto as penas com tag adensam a 4 Hz. Com `null` nos carimbos alheios, cada ponto da
  // pena sem tag virava um trecho de 1 ponto — invisível com `spanGaps: false` e sem marcador.
  const eixoX = [T0, T0 + 0.25, T0 + 0.5, T0 + 0.75, T0 + 1];
  const alinhada = alinharNoEixo(eixoX, [T0, T0 + 1], [33.3, 33.4], 2);

  expect(alinhada).toEqual([33.3, 33.3, 33.3, 33.3, 33.4]);
});

test("carimbo alheio antes da primeira amostra da pena fica vazio: carry-forward não anda para trás", () => {
  const alinhada = alinharNoEixo([T0 - 1, T0, T0 + 1], [T0, T0 + 1], [1, 2], 10);

  expect(alinhada).toEqual([null, 1, 2]);
});

test("carry-forward para no teto: silêncio de mais de 2 cadências vira gap, não reta contínua", () => {
  const eixoX = [T0, T0 + 1, T0 + 2, T0 + 3, T0 + 4, T0 + 5];
  const alinhada = alinharNoEixo(eixoX, [T0, T0 + 5], [1, 2], 2);

  expect(alinhada).toEqual([1, 1, 1, null, null, 2]);
});

test("null da própria série (SP rastreado, qualidade) é o que se repete adiante: continua gap", () => {
  // A repetição carrega o último valor conhecido, e um `null` amostrado é conhecido: o traço
  // fica cortado até a próxima amostra com valor, em vez de voltar ao valor anterior ao gap.
  const eixoX = [T0, T0 + 0.5, T0 + 1, T0 + 1.5, T0 + 2];
  const alinhada = alinharNoEixo(eixoX, [T0, T0 + 1, T0 + 2], [1, null, 3], 2);

  expect(alinhada).toEqual([1, 1, null, null, 3]);
});

test("teto do carry-forward escala com a cadência: Ts_mpc no raw, bucket de 1 min no agregado", () => {
  expect(tetoCarryForwardOperacaoS("raw", 1)).toBe(2);
  expect(tetoCarryForwardOperacaoS("raw", 60)).toBe(120);
  // No `1m` o bucket é de 60 s: um teto de Ts_mpc gaparia toda série agregada saudável.
  expect(tetoCarryForwardOperacaoS("1m", 1)).toBe(120);
});

test("carry-forward para na fronteira do passado: carimbo da predição nunca recebe medição repetida", () => {
  // eixoX = 3 carimbos de histórico (0, 5, 10) + 2 carimbos só da predição (15, 20). A pena
  // amostrou em 0 e 10; 15 e 20 estão dentro do teto de 10 s, então sem o limite o carry-forward
  // desenharia a medição de 10 na seção futura — reta sólida atravessando a linha do "agora".
  const eixoX = [0, 5, 10, 15, 20].map((d) => T0 + d);
  const coluna = alinharNoEixo(eixoX, [T0, T0 + 10], [1, 2], 10, T0 + 10);

  expect(coluna).toEqual([1, 1, 2, null, null]);
});

test("último carimbo histórico é o mais novo entre as penas — a esparsa ainda alcança a ponta densa", () => {
  const densa = { id: "cv_1", t: [T0, T0 + 4, T0 + 8], v: [1, 2, 3], sp: [], auto: [] };
  const esparsa = { id: "mv_1", t: [T0 + 2], v: [9], sp: [], auto: [] };

  expect(ultimoCarimboHistorico([esparsa, densa])).toBe(T0 + 8);
  // Sem histórico nenhum nada de medido desenha (a predição não passa por este limite).
  expect(ultimoCarimboHistorico([])).toBe(Number.NEGATIVE_INFINITY);
});

test("predição entra só nos seus próprios carimbos: teto 0 não repete o plano em carimbo alheio", () => {
  // T0+2 é carimbo da ponta viva OPC de outra pena, entre dois pontos do plano: repetir o valor
  // do plano ali viraria degrau numa pena de CV, que é reta entre pontos (§3.3 só a MV é degrau).
  const eixoX = [T0, T0 + 2, T0 + 5, T0 + 10];

  expect(alinharNoEixo(eixoX, [T0, T0 + 5, T0 + 10], [10, 20, 30], 0)).toEqual([10, null, 20, 30]);
});

test("emenda: o trecho já decorrido do plano sai de cena e o tracejado começa no fim do sólido (DESIGN §Overview)", () => {
  // Ts_mpc = 5 s. O quadro que publica o plano já avançou pelo menos uma fronteira além do
  // dispatch que o produziu (`prediction.ts = _dispatch_ts`, `blocks/mpc.py`; `t[0] = 0`,
  // `test_mpc_worker.py`), então `tAbs[0]` cai ATRÁS da ponta viva. A âncora não se move (§3.5,
  // F5R-01): quem muda é só o desenho — a predição "continua" na linha-cursor, tinta molhada na
  // ponta, não traço voltando por cima do que já secou.
  const plano = emendarPlanoNoDivisor([T0 + 5, T0 + 10, T0 + 15], [2, 4, 6], T0 + 12, false);

  // Começa exatamente no divisor (fim do sólido): sem sobreposição e sem buraco na emenda.
  expect(plano.t).toEqual([T0 + 12, T0 + 15]);
  // Reta entre os pontos que cercam o divisor (CV é trajetória contínua): 4 + (6-4) × 2/5.
  expect(plano.v[0]).toBeCloseTo(4.8, 10);
});

test("emenda de MV é degrau, não reta: o valor no divisor é o do próximo ponto (§3.3, align -1)", () => {
  // `mv[k]` vale no intervalo que TERMINA em `tAbs[k]`: interpolar ali moveria a quina do degrau.
  const plano = emendarPlanoNoDivisor([T0 + 5, T0 + 10, T0 + 15], [30, 45, 60], T0 + 12, true);

  expect(plano.t).toEqual([T0 + 12, T0 + 15]);
  expect(plano.v).toEqual([60, 60]);
});

test("emenda: plano inteiro no futuro passa intacto; plano inteiro decorrido não desenha", () => {
  const tAbs = [T0 + 20, T0 + 25];
  expect(emendarPlanoNoDivisor(tAbs, [1, 2], T0 + 10, false)).toEqual({ t: tAbs, v: [1, 2] });
  // Sem histórico nenhum o divisor é -Infinity: nada a recortar, o plano desenha inteiro.
  expect(emendarPlanoNoDivisor(tAbs, [1, 2], Number.NEGATIVE_INFINITY, false).t).toEqual(tAbs);
  // Quadro velho (plano todo atrás da ponta viva): nada a desenhar, e nunca uma reta esticada.
  expect(emendarPlanoNoDivisor(tAbs, [1, 2], T0 + 30, false)).toEqual({ t: [], v: [] });
});

test("emenda: linha de CV ausente no quadro (comprimento incompatível) não desenha nada", () => {
  expect(emendarPlanoNoDivisor([T0 + 5, T0 + 10], [], T0 + 7, false)).toEqual({ t: [], v: [] });
});

test("borda viva: mpc.state novo faz append na série sem esperar o poll", () => {
  const resp = historico("cv_1", [
    { d: 0, v: 1, sp: 1.5, auto: true },
    { d: 5, v: 1.1, sp: 1.5, auto: true },
  ]);
  const vivas: AmostraViva[] = [amostraViva(10, 1.2, 1.5, true)];
  const [serie] = mesclarSeriesVivas(resp, vivas, ["cv_1"]);

  expect(serie.t).toEqual([0, 5, 10].map((d) => T0 + d));
  expect(serie.v).toEqual([1, 1.1, 1.2]);
  expect(serie.sp).toEqual([1.5, 1.5, 1.5]);
  expect(serie.auto).toEqual([true, true, true]);
});

test("poll re-sincroniza sem duplicar pontos que a borda viva já tinha visto", () => {
  // O poll já trouxe t=10, que a borda viva também capturou ao vivo antes do poll chegar.
  const resp = historico("cv_1", [
    { d: 0, v: 1, sp: 1.5, auto: true },
    { d: 5, v: 1.1, sp: 1.5, auto: true },
    { d: 10, v: 1.2, sp: 1.5, auto: true },
  ]);
  const vivas: AmostraViva[] = [amostraViva(10, 1.2, 1.5, true), amostraViva(15, 1.3, 1.5, true)];
  const [serie] = mesclarSeriesVivas(resp, vivas, ["cv_1"]);

  expect(serie.t).toEqual([0, 5, 10, 15].map((d) => T0 + d));
  expect(serie.v).toEqual([1, 1.1, 1.2, 1.3]);
});

test("montagem de séries é pura: mesma entrada produz a mesma saída, sem mutar o histórico", () => {
  const resp = historico("cv_1", [{ d: 0, v: 1, sp: null, auto: false }]);
  const congelado = JSON.parse(JSON.stringify(resp)) as MpcHistoryResponse;
  mesclarSeriesVivas(resp, [amostraViva(5, 2, null, false)], ["cv_1"]);
  expect(resp).toEqual(congelado);
});

test("var_id sem histórico nem amostra viva devolve série vazia (sempre uma série por id pedido)", () => {
  const resp = historico("cv_1", [{ d: 0, v: 1, sp: null, auto: false }]);
  const [, vazia] = mesclarSeriesVivas(resp, [], ["cv_1", "cv_2"]);
  expect(vazia).toEqual({ id: "cv_2", t: [], v: [], sp: [], auto: [] });
});

test("chave de consulta muda com a janela — react-query recarrega ao trocar de janela", () => {
  const a = chaveHistoricoOperacao(462, "mpc1", ["cv_1"], 1800);
  const b = chaveHistoricoOperacao(462, "mpc1", ["cv_1"], 7200);
  expect(a).not.toEqual(b);
});

test("âncora do overlay é prediction.ts, nunca o ts do quadro (§3.5, F5R-01)", () => {
  const previsao: MpcPrediction = {
    ts: carimbo(100), // prediction.ts: fronteira em que o solve foi despachado
    t: [0, 10, 20],
    cv: [[1, 2, 3]],
    mv: [[5, 5.5, 6]],
  };
  const overlay = montarOverlayPrevisao(previsao);

  // A série futura começa em prediction.ts (T0+100), não em algum `ts` de quadro diferente
  // (ex.: T0+105, que seria o `MpcState.ts` proibido pela regra global 2).
  expect(overlay.tAbs).toEqual([100, 110, 120].map((d) => T0 + d));
  expect(overlay.agora).toBe(T0 + 100);
  expect(overlay.cv).toEqual([[1, 2, 3]]);
  expect(overlay.mv).toEqual([[5, 5.5, 6]]);
});

test("quadro com t: [] (fora de AUTO) remove o overlay sem apagar o histórico (§3.4)", () => {
  const resp = historico("cv_1", [
    { d: 0, v: 1, sp: 1.5, auto: true },
    { d: 5, v: 1.1, sp: 1.5, auto: true },
  ]);
  const [serie] = mesclarSeriesVivas(resp, [], ["cv_1"]);
  const overlay = montarOverlayPrevisao({ ts: carimbo(5), t: [], cv: [], mv: [] });

  expect(overlay).toEqual({ tAbs: [], agora: null, cv: [], mv: [] });
  // O histórico não é tocado pela ausência de predição — são funções independentes.
  expect(serie.t).toEqual([0, 5].map((d) => T0 + d));
  expect(serie.v).toEqual([1, 1.1]);
});

test("degrau fantasma da MV usa align: -1 — align: +1 é proibido (§3.3)", () => {
  expect(OPCOES_DEGRAU_MV.align).toBe(-1);
});

test("SP dessaturada exatamente onde auto=false — PV-tracking não é SP comandado (§2.2-1, F5R-21)", () => {
  const sp = [1, 2, 3, 4];
  const auto = [true, true, false, false];
  const divisao = dividirSpPorAuto(sp, auto);

  expect(divisao.comandado).toEqual([1, 2, null, null]);
  expect(divisao.rastreado).toEqual([null, null, 3, 4]);
});

test("SP dessaturada: null original nunca vira valor em nenhum dos dois traços", () => {
  const divisao = dividirSpPorAuto([null, 5], [false, true]);
  expect(divisao.comandado).toEqual([null, 5]);
  expect(divisao.rastreado).toEqual([null, null]);
});

test("defaults: cada CV traz a pena de PV ligada e a pena de SP DESLIGADA logo abaixo (emenda de §7.4-6)", () => {
  const selecao = selecionarPenasDefault([{ id: "cv_a" }, { id: "cv_b" }], [], [], []);

  expect(selecao.map((p) => [p.id, p.categoria, p.ligada])).toEqual([
    ["cv_a", "cv", true],
    [idPenaSp("cv_a"), "sp", false],
    ["cv_b", "cv", true],
    [idPenaSp("cv_b"), "sp", false],
  ]);
  // A pena de SP é da MESMA variável da CV: cor, nome, escala Y e faixa do operador saem de lá
  // (`LegendaOperacao`/`escalasUplot` leem `varId`, nunca o id da pena).
  expect(selecao.map((p) => p.varId)).toEqual(["cv_a", "cv_a", "cv_b", "cv_b"]);
});

test("defaults: CV custa 1 pena (o SP paga a dele), então 8 CVs cabem no teto e a 9ª é excedente", () => {
  const cvs = Array.from({ length: 9 }, (_, i) => ({ id: `cv_${String(i)}` }));
  const selecao = selecionarPenasDefault(cvs, [], [], []);
  const pv = selecao.filter((p) => p.categoria === "cv");

  expect(CUSTO_PENAS.cv).toBe(1);
  expect(CUSTO_PENAS.sp).toBe(1);
  expect(pv.filter((p) => p.ligada)).toHaveLength(TETO_PENAS_OPERACAO);
  expect(pv[8]).toEqual({
    id: "cv_8",
    varId: "cv_8",
    categoria: "cv",
    ligada: false,
    excedente: true,
  });
  // Nenhuma pena de SP nasce ligada — o teto é gasto por traço DESENHADO, e o alvo é opt-in.
  expect(selecao.filter((p) => p.categoria === "sp" && p.ligada)).toEqual([]);
});

test("defaults: Restrições (banda, 1 pena) preenchem o que sobrou do teto depois das CVs, na ordem do config", () => {
  const cvs = Array.from({ length: 6 }, (_, i) => ({ id: `cv_${String(i)}` })); // 6 penas
  const constraints = [{ id: "co_1" }, { id: "co_2" }, { id: "co_3" }]; // sobram 2 penas
  const selecao = selecionarPenasDefault(cvs, constraints, [], []);
  const restricoes = selecao.filter((p) => p.categoria === "constraint");

  expect(restricoes.map((p) => p.id)).toEqual(["co_1", "co_2", "co_3"]);
  expect(restricoes.map((p) => p.ligada)).toEqual([true, true, false]);
  expect(restricoes.map((p) => p.excedente)).toEqual([false, false, true]);
});

test("defaults: MVs e DVs nascem desligadas (opt-in pela legenda), mesmo com o teto livre", () => {
  const selecao = selecionarPenasDefault([], [], [{ id: "mv_1" }], [{ id: "dv_1" }]);

  expect(selecao).toEqual([
    { id: "mv_1", varId: "mv_1", categoria: "mv", ligada: false, excedente: false },
    { id: "dv_1", varId: "dv_1", categoria: "dv", ligada: false, excedente: false },
  ]);
});

test("tracoPenaSp: o SP sai no matiz da PRÓPRIA CV, pontilhado — nunca no Azul Único (§7.4-6)", () => {
  const traco = tracoPenaSp("PENA", "TEXTO", false);

  expect(traco.stroke).toBe("PENA");
  expect(traco.dash).toEqual(TRACO_SP);
  // Pontilhado ≠ tracejado da predição (`[5, 5]`): sólido = PV medido, pontilhado = SP
  // comandado, tracejado = futuro. Três estilos, um matiz por variável.
  expect(traco.dash).not.toEqual([5, 5]);
});

test("tracoPenaSp rastreado: MESMA cor da CV puxada para o texto do poço, mesmo pontilhado (§2.2-1, F5R-21)", () => {
  const rastreado = tracoPenaSp("PENA", "TEXTO", true);

  expect(rastreado.stroke).toBe("color-mix(in oklch, PENA, TEXTO 60%)");
  expect(rastreado.dash).toEqual(tracoPenaSp("PENA", "TEXTO", false).dash);
  expect(rastreado.width).toBe(tracoPenaSp("PENA", "TEXTO", false).width);
});

test("faixa da legenda do SP usa o MESMO pontilhado do traço do gráfico (canal redundante)", () => {
  // Duas linhas da legenda com o mesmo matiz de propósito (CV e o alvo dela): cor sozinha não
  // separa, cor + estilo separam — a faixa tem de repetir o dash do canvas, não um valor solto.
  expect(faixaPontilhadaSp("PENA")).toBe(
    "repeating-linear-gradient(to right, PENA 0 2px, transparent 2px 6px)",
  );
  expect(TRACO_SP).toEqual([2, 4]);
});

test("teto de penas de operação é 8 (distinto do teto de 6 do trend de engenharia)", () => {
  expect(TETO_PENAS_OPERACAO).toBe(8);
});

// -------------------------------------------------------------------- paleta de 8 penas (§6.6-5)

/** Lê o valor cru do token direto de `tokens.css` — a paleta tem fonte única (DESIGN.md
 *  §Do's); duplicar os literais OKLCH aqui criaria um segundo lugar para divergir.
 *  `node:fs` aqui é seguro porque `tsconfig.build.json` exclui `*.check.ts` do build de
 *  produção (a imagem roda `npm ci` sem `@types/node`). */
const TOKENS_CSS = readFileSync(
  fileURLToPath(new URL("../../styles/tokens.css", import.meta.url)),
  "utf-8",
);

/** Valor cru do token no tema pedido: o bloco `@theme` é o claro, `[data-theme="dark"]` é o
 *  escuro, e os dois têm paleta própria — ler só o primeiro casamento do arquivo deixaria o
 *  tema escuro sem teste nenhum (foi nele que a pena 1 e o Azul Único ficaram idênticos). */
const INICIO_TEMA_ESCURO = TOKENS_CSS.indexOf('[data-theme="dark"]');
if (INICIO_TEMA_ESCURO === -1) {
  throw new Error('tokens.css: seletor [data-theme="dark"] não encontrado — fatia de tema inválida');
}

type Tema = "claro" | "escuro";
const TEMAS: readonly Tema[] = ["claro", "escuro"];

function valorTokenTema(nome: string, tema: Tema): string {
  const fonte =
    tema === "claro"
      ? TOKENS_CSS.slice(0, INICIO_TEMA_ESCURO)
      : TOKENS_CSS.slice(INICIO_TEMA_ESCURO);
  const casado = fonte.match(new RegExp(`${nome}:\\s*([^;]+);`));
  if (casado === null) throw new Error(`token ${nome} não encontrado no tema ${tema}`);
  return casado[1].trim();
}

/** Só a forma sem unidade (`oklch(L C H)`), que é a que `tokens.css` usa. A forma percentual
 *  (`oklch(72% 0.16 258)`) é CSS válido e casaria no mesmo regex capturando `72`, cem vezes a
 *  escala de L — a distância sairia enorme e o teste aprovaria colisão real. Melhor falhar. */
function coordenadasOklch(valor: string): readonly [number, number, number] {
  const casado = /^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/.exec(valor);
  if (casado === null || valor.includes("%")) {
    throw new Error(`valor não é oklch() de 3 coordenadas sem unidade: ${valor}`);
  }
  return [Number(casado[1]), Number(casado[2]), Number(casado[3])];
}

/**
 * Distância perceptual entre duas cores OKLCH: L mais o par cromático do próprio espaço
 * (`C·cos h`, `C·sin h`). Comparar só o texto do token (o que este teste fazia antes) aprova
 * `oklch(0.72 0.16 258)` contra `oklch(0.7 0.17 258)` — duas cores que o operador não consegue
 * separar no gráfico —, e comparar matiz em grau puro trataria 20° a C 0.02 (cinza) como colisão
 * e 20° a C 0.22 como distinção.
 */
function distanciaPerceptual(a: string, b: string): number {
  const [la, ca, ha] = coordenadasOklch(a);
  const [lb, cb, hb] = coordenadasOklch(b);
  const ra = (ha * Math.PI) / 180;
  const rb = (hb * Math.PI) / 180;
  return Math.hypot(
    la - lb,
    ca * Math.cos(ra) - cb * Math.cos(rb),
    ca * Math.sin(ra) - cb * Math.sin(rb),
  );
}

/** Piso de distinção, calibrado na própria paleta: o par mais apertado que ela embarca de
 *  propósito é 0.0615 (`--color-pen-2` × `--color-pen-8`, tema escuro), enquanto as duas
 *  colisões que a tela de operação provou ficavam em 0.022 (pena 1 × Azul Único) e 0.039
 *  (pena 4 × Âmbar Advertência). 0.05 separa os dois grupos com folga para os dois lados. */
const PISO_DISTINCAO = 0.05;

/** Cores que a pena nunca pode imitar: as três de severidade (A Regra da Cor Anormal) e o Azul
 *  Único, que é só interação/seleção (A Regra do Azul Único) — pena no matiz do acento faz o
 *  operador ler a variável como estado de seleção. */
const TOKENS_RESERVADOS = ["--color-alarm", "--color-warn", "--color-success", "--color-accent"];

/** Faixa de matiz do Azul Único, em graus OKLCH: "existe UM azul" (DESIGN §Colors) é regra de
 *  matiz, não de luminosidade — duas cores no mesmo matiz e L diferente continuam sendo "o
 *  azul" para quem lê o gráfico. 25° deixa passar a pena 7 (a mais próxima de propósito: 27°
 *  no tema claro, 28° no escuro) e reprova qualquer pena no matiz do acento. Pena
 *  quase-neutra (`--color-pen-6`, C 0.02) fica fora da regra: cinza não é o azul. */
const FAIXA_MATIZ_AZUL_UNICO = 25;
const CROMA_NEUTRA = 0.05;

test("paleta do trend de operação tem 8 tokens, um por posição do teto (§6.6-5)", () => {
  expect(TOKENS_PENA_OPERACAO).toHaveLength(TETO_PENAS_OPERACAO);
});

test("as 8 cores de pena são distinguíveis entre si nos dois temas (§6.6-5)", () => {
  const colisoes: string[] = [];
  for (const tema of TEMAS) {
    for (const [i, tokenA] of TOKENS_PENA_OPERACAO.entries()) {
      for (const tokenB of TOKENS_PENA_OPERACAO.slice(i + 1)) {
        const distancia = distanciaPerceptual(
          valorTokenTema(tokenA, tema),
          valorTokenTema(tokenB, tema),
        );
        if (distancia < PISO_DISTINCAO) {
          colisoes.push(`${tema}: ${tokenA} × ${tokenB} = ${distancia.toFixed(4)}`);
        }
      }
    }
  }

  expect(colisoes).toEqual([]);
});

test("nenhuma cor de pena colide com cor reservada de severidade nem com o Azul Único (§6.6-5, DESIGN §Colors)", () => {
  // O Azul Único é interação, nunca dado (DESIGN §Colors): uma pena de série no mesmo azul faz
  // a variável se passar por seleção/foco, e a seleção de zoom (`.u-select`, `trend.css`) por
  // pena — inclusive desligada, quando ela não desenha nada.
  const colisoes: string[] = [];
  for (const tema of TEMAS) {
    for (const tokenPena of TOKENS_PENA_OPERACAO) {
      for (const tokenReservado of TOKENS_RESERVADOS) {
        const distancia = distanciaPerceptual(
          valorTokenTema(tokenPena, tema),
          valorTokenTema(tokenReservado, tema),
        );
        if (distancia < PISO_DISTINCAO) {
          colisoes.push(`${tema}: ${tokenPena} × ${tokenReservado} = ${distancia.toFixed(4)}`);
        }
      }
    }
  }

  // Mesmo matiz do acento com outra luminosidade ainda é "o azul": a distância perceptual acima
  // aprovaria (a pena 1 do tema claro ficava a 0.10 do acento) e o operador continuaria lendo a
  // pena como o azul de interação.
  for (const tema of TEMAS) {
    const [, , matizAcento] = coordenadasOklch(valorTokenTema("--color-accent", tema));
    for (const tokenPena of TOKENS_PENA_OPERACAO) {
      const [, croma, matiz] = coordenadasOklch(valorTokenTema(tokenPena, tema));
      if (croma < CROMA_NEUTRA) continue;
      const bruto = Math.abs(matiz - matizAcento) % 360;
      const desvio = bruto > 180 ? 360 - bruto : bruto;
      if (desvio < FAIXA_MATIZ_AZUL_UNICO) {
        colisoes.push(`${tema}: ${tokenPena} está a ${String(desvio)}° do Azul Único`);
      }
    }
  }

  expect(colisoes).toEqual([]);
});

test("o traço do SP de qualquer posição da paleta fica longe do Azul Único nos dois temas (§7.4-6)", () => {
  // O invariante que o defeito reportado em operação violou, agora executável: a cor do SP é
  // SEMPRE a da pena da CV, então nenhuma posição da paleta pode aproximá-la do acento. O
  // trecho rastreado fica fora: o `color-mix` com o texto do poço não é `oklch()` de 3
  // coordenadas, e afastar do matiz é justo o que ele faz.
  const colisoes: string[] = [];
  for (const tema of TEMAS) {
    const acento = valorTokenTema("--color-accent", tema);
    for (const tokenPena of TOKENS_PENA_OPERACAO) {
      const { stroke } = tracoPenaSp(valorTokenTema(tokenPena, tema), "irrelevante", false);
      const distancia = distanciaPerceptual(stroke, acento);
      if (distancia < PISO_DISTINCAO) {
        colisoes.push(`${tema}: SP em ${tokenPena} = ${distancia.toFixed(4)} do acento`);
      }
    }
  }

  expect(colisoes).toEqual([]);
});

test("atribuirCoresPenas — a mesma função que TrendOperacao.tsx usa para colorir cada pena — devolve 8 cores distintas para 8 ids, sem wrap antes do teto (§6.6-5)", () => {
  const ids = ["cv_1", "cv_2", "co_1", "co_2", "co_3", "mv_1", "mv_2", "dv_1"]; // 8 ids
  const coresResolvidas = TOKENS_PENA_OPERACAO.map((t) => valorTokenTema(t, "claro"));
  const mapa = atribuirCoresPenas(ids, coresResolvidas);

  expect(mapa.size).toBe(8);
  // Comparação por conjunto, não caso a caso: 8 ids distintos ⇒ 8 cores distintas.
  expect(new Set(mapa.values()).size).toBe(8);
});

test("atribuirCoresPenas: id além do teto de 8 recicla por módulo — mesmo comportamento de antes (§6.6-5)", () => {
  const ids = Array.from({ length: 9 }, (_, i) => `v${String(i)}`); // 9º id, 1 além do teto
  const coresResolvidas = TOKENS_PENA_OPERACAO.map((t) => valorTokenTema(t, "claro"));
  const mapa = atribuirCoresPenas(ids, coresResolvidas);

  expect(mapa.get("v8")).toBe(mapa.get("v0"));
});
