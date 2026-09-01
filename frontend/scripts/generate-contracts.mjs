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
 *
 * `node_configs` (ARCH-06/TD-018) reusa o mesmo `interfacesDeSchemas` para a forma dos configs
 * de bloco (`MvVar`/`CvVar`/`ConstraintVar`/`DvVar`/`MpcConfig`/`ScriptConfig`/`FuzzyConfig`/
 * `PidConfig`) que `frontend/src/features/flows/graph.ts` importa em vez de reescrever.
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

/** Achata um dict `{nome: schema}` (schemas de raiz + `$defs` aninhados) numa lista de
 *  interfaces, sem repetir nome — um modelo pode ser raiz de um payload/config e `$defs` de
 *  outro ao mesmo tempo (ex.: `PortValue` é raiz de `ws_payloads` e também `$defs` de
 *  `FlowStatus`; `Limits` é `$defs` tanto de `MvVar` quanto de `CvVar` em `node_configs`).
 *  Genérico: serve tanto a `ws_payloads` quanto a `node_configs`. */
function interfacesDeSchemas(schemas) {
  const vistos = new Map();
  for (const [nome, schema] of Object.entries(schemas)) {
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

/** Contrato dinâmico que também define o default de criação do bloco na paleta
 * (bloco "fuzzy", ADR-029): "default_fll" é a string FLL canônica e "default_counts"
 * as contagens iniciais de portas — fonte única, o frontend nunca duplica o texto. */
export interface ContratoPortaDinamicaComDefault extends ContratoPortaDinamica {
  default_fll: string;
  default_counts: { n_inputs: number; n_outputs: number };
  max_fll_length: number;
}

/** Contrato de portas FIXAS que também carrega o default de criação (bloco "fuzzy_loop",
 * SPEC_FUZZY §3.2): as portas são as do shell, mas a paleta precisa do .fll canônico e do
 * teto do texto da mesma fonte única — sem duplicar o FLL no frontend. */
export interface ContratoPortaFixaComDefault extends ContratoPortaFixa {
  default_fll: string;
  max_fll_length: number;
}

export type ContratoPorta =
  | ContratoPortaFixa
  | ContratoPortaFixaComDefault
  | ContratoPortaDinamica
  | ContratoPortaDinamicaComDefault;
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
  const {
    port_contracts: portContracts,
    ws_payloads: wsPayloads,
    node_configs: nodeConfigs,
  } = rodarExportadorPython();

  const corpo = `// GERADO — não editar; fonte: ottima_core.contracts_export
// Regenerar: npm run generate:contracts

${TIPOS_CONTRATO_PORTA}

${tabelaPortContracts(portContracts)}

// --------------------------------------------------------------------------------------
// Payloads do WS (JSON Schema via model_json_schema(), spec F3 §4.2 / bus.py)
// --------------------------------------------------------------------------------------

${interfacesDeSchemas(wsPayloads).join("\n\n")}

// --------------------------------------------------------------------------------------
// Forma dos configs de bloco (JSON Schema via model_json_schema(), ARCH-06/TD-018): campos
// de MvVar/CvVar/ConstraintVar/DvVar/MpcConfig/ScriptConfig/FuzzyConfig/PidConfig, mesmo
// mecanismo dos payloads do WS acima (ADR-034: forma é gerada, regra travada por golden,
// default pode continuar espelhado à mão). TfsConfig fica de fora — ver
// contracts_export.py::_NODE_CONFIG_MODELS.
// --------------------------------------------------------------------------------------

${interfacesDeSchemas(nodeConfigs).join("\n\n")}
`;

  mkdirSync(dirname(ARQUIVO_SAIDA), { recursive: true });
  writeFileSync(ARQUIVO_SAIDA, corpo);
}

main();
