#!/usr/bin/env node
/**
 * Gera `frontend/src/lib/contracts.gen.ts` a partir de `ottima_core.contracts_export` (Python).
 *
 * Fonte única dos contratos de porta e dos payloads do WS (débito 2+4, plano F4a): em vez de
 * três espelhos TS mantidos à mão (`graph.ts`, `nodes/index.tsx`, `useFlowStatus.ts`), este
 * script roda o exportador Python — que imprime `port_contracts` + `ws_payloads` (JSON Schema
 * via `model_json_schema()`) em stdout — e traduz para TS com um gerador próprio, sem
 * dependência npm nova. Os schemas exportados são sempre planos (objetos, primitivos, enums,
 * dicts); um gerador genérico de JSON Schema seria mais código do que o contrato precisa.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ_REPO = fileURLToPath(new URL("../..", import.meta.url));
const ARQUIVO_SAIDA = fileURLToPath(new URL("../src/lib/contracts.gen.ts", import.meta.url));

function rodarExportadorPython() {
  const stdout = execFileSync("uv", ["run", "python", "-m", "ottima_core.contracts_export"], {
    cwd: RAIZ_REPO,
    encoding: "utf-8",
  });
  return JSON.parse(stdout);
}

// --------------------------------------------------------------------------------------
// JSON Schema (plano) -> tipo TS
// --------------------------------------------------------------------------------------

function nomeDoRef(ref) {
  return ref.split("/").pop();
}

/** Tipo TS de um schema de propriedade; nunca declara interface própria (isso é `interfaceDe`). */
function tipoDe(schema) {
  if (schema.$ref) return nomeDoRef(schema.$ref);
  if (schema.anyOf) return schema.anyOf.map(tipoDe).join(" | ");
  if (schema.enum) return schema.enum.map((valor) => JSON.stringify(valor)).join(" | ");
  if (schema.type === "array") return `${tipoDe(schema.items)}[]`;
  if (schema.type === "object") {
    if (schema.additionalProperties === true) return "Record<string, unknown>";
    if (schema.additionalProperties) return `Record<string, ${tipoDe(schema.additionalProperties)}>`;
    return "Record<string, unknown>";
  }
  if (schema.type === "integer" || schema.type === "number") return "number";
  if (schema.type === "string") return "string";
  if (schema.type === "boolean") return "boolean";
  if (schema.type === "null") return "null";
  throw new Error(`schema não plano, gerador não sabe traduzir: ${JSON.stringify(schema)}`);
}

/** Uma interface TS por schema de objeto com `properties` (modelo raiz ou `$defs`). Todo
 *  campo sai obrigatório: o Pydantic sempre serializa campos com default no `model_dump*`,
 *  então "opcional na construção" (JSON Schema `required`) não é "ausente no payload". */
function interfaceDe(nome, schema) {
  const campos = Object.entries(schema.properties ?? {})
    .map(([campo, propSchema]) => `  ${campo}: ${tipoDe(propSchema)};`)
    .join("\n");
  return `export interface ${nome} {\n${campos}\n}`;
}

/** Achata `ws_payloads` (schemas de raiz + `$defs` aninhados) numa lista de interfaces, sem
 *  repetir nome — um modelo pode ser raiz de um payload e `$defs` de outro ao mesmo tempo
 *  (ex.: `PortValue` é raiz e também `$defs` de `FlowStatus`). */
function interfacesWsPayloads(wsPayloads) {
  const vistos = new Map();
  for (const [nome, schema] of Object.entries(wsPayloads)) {
    for (const [nomeDef, defSchema] of Object.entries(schema.$defs ?? {})) {
      if (!vistos.has(nomeDef)) vistos.set(nomeDef, interfaceDe(nomeDef, defSchema));
    }
    if (!vistos.has(nome)) vistos.set(nome, interfaceDe(nome, schema));
  }
  return [...vistos.values()];
}

// --------------------------------------------------------------------------------------
// port_contracts -> TS
// --------------------------------------------------------------------------------------

const TIPOS_CONTRATO_PORTA = `
export type DirecaoPorta = "input" | "output";

export interface PortaFixa {
  name: string;
  direction: DirecaoPorta;
  type: string;
}

export interface RegraPortaDinamica {
  direction: DirecaoPorta;
  type?: string;
  source?: string;
  prefix?: string;
  count_field?: string;
  max?: number;
}

export interface ContratoPortaFixa {
  dynamic: false;
  ports: PortaFixa[];
}

export interface ContratoPortaDinamica {
  dynamic: true;
  source: string;
  rules: RegraPortaDinamica[];
}

export type ContratoPorta = ContratoPortaFixa | ContratoPortaDinamica;
`.trim();

function tabelaPortContracts(portContracts) {
  const tipos = Object.keys(portContracts)
    .map((tipo) => JSON.stringify(tipo))
    .join(" | ");
  return (
    `export const PORT_CONTRACTS: Record<${tipos}, ContratoPorta> = ` +
    `${JSON.stringify(portContracts, null, 2)};`
  );
}

// --------------------------------------------------------------------------------------

function main() {
  const { port_contracts: portContracts, ws_payloads: wsPayloads } = rodarExportadorPython();

  const corpo = `// GERADO — não editar; fonte: ottima_core.contracts_export
// Regenerar: npm run generate:contracts

${TIPOS_CONTRATO_PORTA}

${tabelaPortContracts(portContracts)}

// --------------------------------------------------------------------------------------
// Payloads do WS (JSON Schema via model_json_schema(), spec F3 §4.2 / bus.py)
// --------------------------------------------------------------------------------------

${interfacesWsPayloads(wsPayloads).join("\n\n")}
`;

  mkdirSync(dirname(ARQUIVO_SAIDA), { recursive: true });
  writeFileSync(ARQUIVO_SAIDA, corpo);
}

main();
