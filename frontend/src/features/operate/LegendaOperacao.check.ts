import { expect, test } from "@playwright/test";
import type { ReactElement } from "react";

import type { MpcVarState } from "../../lib/contracts.gen";
import type { EscalaVar } from "../trend/escalas";
import type { PainelLegendaTrendProps } from "../trend/PainelLegendaTrend";
import { LegendaOperacao, type LegendaOperacaoProps } from "./LegendaOperacao";
import { idPenaSp, type PenaLegenda } from "./trendOperacao";

/**
 * Fiação do aviso "Fora da escala" na legenda de operação.
 *
 * O predicado (`foraDaFaixa`) já está pinado em `escalas.check.ts`; o que carregou o defeito
 * de campo é a FIAÇÃO — de qual escala cada linha lê e quando ela pode avisar. Dois pontos
 * que nenhum teste de predicado alcança:
 *
 * - a pena de SP não tem editor de escala próprio: ela desenha na escala da CV
 *   (`escalas[pena.varId]`), com o valor DELA (`estado.sp`). SP fora da faixa com a PV
 *   dentro corta só a linha tracejada — sem este aviso, nenhuma linha da legenda explica
 *   o sumiço;
 * - pena DESLIGADA não foi cortada pela moldura, ela nem chega a ser desenhada: avisar ali
 *   seria a mesma plaqueta mentirosa que o aviso existe para evitar.
 *
 * Sem jsdom no repo: `LegendaOperacao` não usa hooks, então o teste a chama como função pura
 * e lê o `linhas` que ela entrega ao painel — que é exatamente a decisão sob teste.
 */

const ESCALA_FIXA: EscalaVar = { auto: false, min: 40, max: 60 };

function pena(overrides: Partial<PenaLegenda> & Pick<PenaLegenda, "id" | "categoria">): PenaLegenda {
  return { varId: "cv1", ligada: true, excedente: false, ...overrides };
}

const PENA_CV = pena({ id: "cv1", categoria: "cv" });
const PENA_SP = pena({ id: idPenaSp("cv1"), categoria: "sp" });

function legenda(
  ligadas: readonly string[],
  vars: Readonly<Record<string, MpcVarState>>,
): PainelLegendaTrendProps["linhas"] {
  const props: LegendaOperacaoProps = {
    defaults: [PENA_CV, PENA_SP],
    ligadas: new Set(ligadas),
    porIdDefinicao: new Map([["cv1", { name: "Topo", eu: "%" }]]),
    cores: new Map([["cv1", "#0ff"]]),
    vars,
    valoresCursor: null,
    foco: "cv1",
    escalas: { cv1: ESCALA_FIXA },
    onAlternarPena: () => {},
    onFocarPena: () => {},
    onMudarEscala: () => {},
  };
  const elemento = LegendaOperacao(props) as ReactElement<PainelLegendaTrendProps>;
  return elemento.props.linhas;
}

/** Quantos avisos a linha `chave` carrega. Contagem, não presença: `some()` sobre um array
 *  por linha já isola as linhas entre si, mas a contagem também recusa o dia em que alguém
 *  empilhar a mesma plaqueta duas vezes na mesma linha. */
function avisos(linhas: PainelLegendaTrendProps["linhas"], chave: string): number {
  const linha = linhas.find((l) => l.chave === chave);
  if (linha === undefined) throw new Error(`linha ${chave} ausente da legenda`);
  return (linha.badges ?? []).filter((b) => b.testId === "operate-trend-legend-fora-escala").length;
}

/** Total na legenda inteira: fecha a porta para o aviso vazar numa linha que o teste não
 *  nomeou (a legenda real tem 7 linhas; esta tem 2, e nenhuma outra pode avisar). */
function avisosNaLegenda(linhas: PainelLegendaTrendProps["linhas"]): number {
  return linhas.reduce(
    (soma, l) =>
      soma + (l.badges ?? []).filter((b) => b.testId === "operate-trend-legend-fora-escala").length,
    0,
  );
}

test("SP fora da faixa da CV avisa na linha do SP, sem contaminar a linha da CV", () => {
  const linhas = legenda(["cv1", idPenaSp("cv1")], { cv1: { v: 50, sp: 80, status: null } });
  expect(linhas.map((l) => l.chave)).toEqual(["cv1", idPenaSp("cv1")]);
  expect(avisos(linhas, idPenaSp("cv1"))).toBe(1);
  expect(avisos(linhas, "cv1")).toBe(0);
  expect(avisosNaLegenda(linhas)).toBe(1);
});

test("PV fora da faixa avisa na linha da CV", () => {
  const linhas = legenda(["cv1", idPenaSp("cv1")], { cv1: { v: 30, sp: 50, status: null } });
  expect(avisos(linhas, "cv1")).toBe(1);
  expect(avisos(linhas, idPenaSp("cv1"))).toBe(0);
  expect(avisosNaLegenda(linhas)).toBe(1);
});

test("PV e SP fora da faixa avisam nas duas linhas, uma plaqueta em cada", () => {
  const linhas = legenda(["cv1", idPenaSp("cv1")], { cv1: { v: 30, sp: 80, status: null } });
  expect(avisos(linhas, "cv1")).toBe(1);
  expect(avisos(linhas, idPenaSp("cv1"))).toBe(1);
  expect(avisosNaLegenda(linhas)).toBe(2);
});

test("pena desligada fora da faixa não avisa: a moldura não cortou nada", () => {
  const linhas = legenda([], { cv1: { v: 30, sp: 80, status: null } });
  expect(avisosNaLegenda(linhas)).toBe(0);
});

test("sem quadro do bloco não há valor para julgar — travessão, não aviso", () => {
  const linhas = legenda(["cv1", idPenaSp("cv1")], {});
  expect(avisosNaLegenda(linhas)).toBe(0);
});
