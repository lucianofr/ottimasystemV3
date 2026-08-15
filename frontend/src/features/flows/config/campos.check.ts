import { expect, test } from "@playwright/test";

import { matrizPadrao, type MatrizTfs } from "../graph";
import {
  inteiroDoCampo,
  matrizDoFormulario,
  nomeParam,
  numeroDoCampo,
  numeroOuNuloDoCampo,
} from "./campos";

test("campo numérico aceita vírgula decimal e cai no padrão quando vazio ou inválido", () => {
  expect(numeroDoCampo("1,5", 0)).toBe(1.5);
  expect(numeroDoCampo("2.75", 0)).toBe(2.75);
  expect(numeroDoCampo("-3,2", 0)).toBe(-3.2);
  expect(numeroDoCampo("  ", 9)).toBe(9);
  expect(numeroDoCampo("abc", 9)).toBe(9);
  expect(numeroDoCampo(null, 9)).toBe(9);
});

test("campo inteiro trunca e prende na faixa", () => {
  expect(inteiroDoCampo("3", 0, 0, 8)).toBe(3);
  expect(inteiroDoCampo("2,9", 0, 0, 8)).toBe(2);
  expect(inteiroDoCampo("99", 0, 0, 8)).toBe(8);
  expect(inteiroDoCampo("-4", 0, 1, 8)).toBe(1);
});

function formulario(pares: Record<string, string>): FormData {
  const dados = new FormData();
  for (const [chave, valor] of Object.entries(pares)) dados.set(chave, valor);
  return dados;
}

test("a matriz do TFS é remontada com os params do formulário", () => {
  const matriz = matrizPadrao();
  matriz[0][0] = { enabled: true, kind: "sopdt", params: { K: 1, tau1: 1, tau2: 0, theta: 0 } };
  const dados = formulario({
    [nomeParam(0, 0, "K")]: "2,5",
    [nomeParam(0, 0, "tau1")]: "30",
    [nomeParam(0, 0, "tau2")]: "5",
    [nomeParam(0, 0, "theta")]: "10",
  });

  const nova = matrizDoFormulario(matriz, dados);
  expect(nova[0][0]).toEqual({
    enabled: true,
    kind: "sopdt",
    params: { K: 2.5, tau1: 30, tau2: 5, theta: 10 },
  });
  // elementos sem campo no formulário mantêm o valor vigente
  expect(nova[1][1]).toEqual(matriz[1][1]);
});

test("elemento IOPDT nunca carrega params de SOPDT, mesmo com o campo antigo no formulário", () => {
  const matriz: MatrizTfs = matrizPadrao();
  matriz[1][0] = { enabled: true, kind: "iopdt", params: { Ki: 1, theta: 0 } };
  const dados = formulario({
    [nomeParam(1, 0, "Ki")]: "0,4",
    [nomeParam(1, 0, "theta")]: "2",
    [nomeParam(1, 0, "K")]: "999",
    [nomeParam(1, 0, "tau1")]: "999",
  });

  const elemento = matrizDoFormulario(matriz, dados)[1][0];
  expect(elemento.kind).toBe("iopdt");
  expect(Object.keys(elemento.params).sort()).toEqual(["Ki", "theta"]);
  expect(elemento.params).toEqual({ Ki: 0.4, theta: 2 });
});

test("habilitação e modelo vêm do estado do modal, não do formulário", () => {
  const matriz = matrizPadrao();
  matriz[0][1] = { enabled: true, kind: "iopdt", params: { Ki: 3, theta: 1 } };
  const nova = matrizDoFormulario(matriz, formulario({ enabled: "false", kind: "sopdt" }));
  expect(nova[0][1].enabled).toBe(true);
  expect(nova[0][1].kind).toBe("iopdt");
  expect(nova[0][0].enabled).toBe(false);
});

test("a matriz remontada continua 2x2", () => {
  const nova = matrizDoFormulario(matrizPadrao(), new FormData());
  expect(nova).toHaveLength(2);
  expect(nova[0]).toHaveLength(2);
  expect(nova[1]).toHaveLength(2);
});

test("limite do PID: em branco é escolha explícita e vira null (sem limite)", () => {
  expect(numeroOuNuloDoCampo("", 100)).toBe(null);
  expect(numeroOuNuloDoCampo("   ", 100)).toBe(null);
  expect(numeroOuNuloDoCampo(null, 100)).toBe(100);
});

test("limite do PID: texto ilegível NÃO apaga o limite, cai no valor anterior", () => {
  // "8O" (letra O) é erro de digitação plausível num campo de texto decimal. Virar null
  // removeria em silêncio o teto da MV e o limite anti-windup da integral.
  expect(numeroOuNuloDoCampo("8O", 80)).toBe(80);
  expect(numeroOuNuloDoCampo("abc", null)).toBe(null);
});

test("limite do PID: aceita vírgula decimal e sinal negativo", () => {
  expect(numeroOuNuloDoCampo("12,5", 0)).toBe(12.5);
  expect(numeroOuNuloDoCampo("-40", 0)).toBe(-40);
});
