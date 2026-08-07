import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import type { ParModeloMpc, VariaveisMpc } from "../graph";
import {
  arredondarBankers,
  derivarHorizontes,
  dimensaoEstado,
  validarConfigMpc,
} from "./mpcLogic";

/**
 * Golden Python->TS do bloco MPC (spec F5 §7.6-2, plano F5b tarefa 6.2) — espelho de
 * `ottima_core.mpc_golden_export` (tarefa 6.1). Compara campo a campo contra o JSON
 * commitado ao lado (`mpcLogic.golden.json`, fonte única e compartilhada com o teste
 * Python): mudar o Python sem regenerar o golden já vira vermelho lá; divergir aqui do
 * lado TS (fórmula, limiar, veredito) vira vermelho aqui (§7.6-4, drift bidirecional).
 *
 * Fora do escopo (só servidor, nunca mirrorado no TS): integridade de tag do `pid`
 * (§2.2-6) — por isso todo `pid` do golden é sempre `null`, e a comparação de
 * `validarConfigMpc` é pela CONTAGEM de erros/avisos, não pelo texto: a mensagem pt-BR é
 * livre entre os dois lados (§7.6-2), só o veredito estrutural precisa bater.
 */

interface CasoArredondamento {
  valor: number;
  esperado: number;
}

interface CasoHorizonte {
  multiplier: number;
  ts_flow: number;
  tss: number[];
  ts_mpc: number;
  np: number;
  nc: number;
}

interface CasoDimensao {
  nome: string;
  variaveis: VariaveisMpc;
  modelos: Record<string, Record<string, ParModeloMpc>>;
  ts_mpc: number;
  esperado: number;
}

interface CasoValidacao {
  regra: string;
  ts_flow_segundos: number;
  config: {
    name: string;
    multiplier: number;
    variables: VariaveisMpc;
    models: Record<string, Record<string, ParModeloMpc>>;
  };
  esperado: { erros: number; avisos: number };
}

interface Golden {
  arredondamento_bankers: CasoArredondamento[];
  horizontes: CasoHorizonte[];
  dimensao_estado: CasoDimensao[];
  validacao: CasoValidacao[];
}

const CAMINHO_GOLDEN = fileURLToPath(new URL("./mpcLogic.golden.json", import.meta.url));
const golden = JSON.parse(readFileSync(CAMINHO_GOLDEN, "utf-8")) as Golden;

for (const caso of golden.arredondamento_bankers) {
  test(`golden arredondarBankers: ${String(caso.valor)} -> ${String(caso.esperado)}`, () => {
    expect(arredondarBankers(caso.valor)).toBe(caso.esperado);
  });
}

for (const caso of golden.horizontes) {
  test(
    `golden derivarHorizontes: multiplier=${String(caso.multiplier)} ` +
      `tsFlow=${String(caso.ts_flow)} tss=${JSON.stringify(caso.tss)}`,
    () => {
      expect(derivarHorizontes(caso.multiplier, caso.ts_flow, caso.tss)).toEqual({
        tsMpc: caso.ts_mpc,
        np: caso.np,
        nc: caso.nc,
      });
    },
  );
}

for (const caso of golden.dimensao_estado) {
  test(`golden dimensaoEstado: ${caso.nome}`, () => {
    expect(dimensaoEstado(caso.variaveis, caso.modelos, caso.ts_mpc)).toBe(caso.esperado);
  });
}

for (const caso of golden.validacao) {
  test(`golden validarConfigMpc: ${caso.regra}`, () => {
    const resultado = validarConfigMpc(
      caso.config.variables,
      caso.config.models,
      caso.config.multiplier,
      caso.ts_flow_segundos,
    );
    expect({ erros: resultado.erros.length, avisos: resultado.avisos.length }).toEqual(
      caso.esperado,
    );
  });
}
