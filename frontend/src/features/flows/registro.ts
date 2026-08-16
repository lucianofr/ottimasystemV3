import type { NodeTypes } from "@xyflow/react";

import {
  contratoFuzzy,
  matrizPadrao,
  type DadosBase,
  type DadosFirstOrder,
  type DadosFuzzy,
  type DadosKalman,
  type DadosMpc,
  type DadosPid,
  type DadosScript,
  type DadosTag,
  type DadosTfs,
  type TipoBloco,
} from "./graph";
import {
  NoEscritaOpc,
  NoFiltroKalman,
  NoFiltroPrimeiraOrdem,
  NoFuzzy,
  NoLeituraOpc,
  NoMpc,
  NoPid,
  NoScriptPython,
  NoTfsMatriz,
} from "./nodes";

/**
 * Registro de tipo de Bloco (ARCH-18/TD-021).
 *
 * Antes, adicionar um tipo exigia tocar 6 arquivos independentes — nenhum "sabia" dos
 * outros, e só os `Record` tipados (rótulo/descrição) eram pegos pelo compilador se faltasse
 * uma chave; os 3 switches de `graph.ts` e o mapa de nós de `nodes/index.tsx` não, e a falta
 * só aparecia em runtime/E2E. Este módulo é a aresta única: `graph.ts`, `nodes/index.tsx` e
 * `FlowPalette.tsx` derivam dele em vez de manter listas paralelas, e
 * `Record<TipoBloco, DefinicaoBloco>` faz faltar uma entrada quebrar o BUILD.
 *
 * Escolha de pasta: `registro.ts` fica plano em `features/flows/`, não em `blocos/registro.ts`
 * (sugestão da auditoria) — a convenção já em uso aqui reserva subpastas (`nodes/`, `config/`,
 * `mpc/`) para GRUPOS de arquivos relacionados; este é um módulo único, no mesmo nível de
 * `graph.ts`/`impactoSave.ts`/`canalPrimitivos.ts`.
 *
 * Campos: só os que hoje já são dados puros por tipo (`rotulo`, `descricao`, `defaults`,
 * `Node`). O switch de `aplicar()` em `ModalConfigBloco.tsx` e o `lerNo` de `graph.ts`
 * continuam switch — cada `case` ali faz parsing/validação genuinamente diferente por tipo
 * (helpers distintos, campos distintos do FormData/JSON), e empurrar isso para dentro do
 * registro trocaria um switch por um Record de closures sem concentrar nada (só o PID tem
 * `montarDadosPid` extraído — ARCH-19 é quem generaliza os outros 8, fora deste escopo).
 */

/** Config por tipo, sem os campos comuns (`exec_order`/`label`) que `criarBloco` sempre
 *  soma por cima — a mesma forma que cada `case` de `criarBloco` já espalhava. */
type ConfigDoBloco =
  | Omit<DadosTag, keyof DadosBase>
  | Omit<DadosScript, keyof DadosBase>
  | Omit<DadosTfs, keyof DadosBase>
  | Omit<DadosMpc, keyof DadosBase>
  | Omit<DadosFirstOrder, keyof DadosBase>
  | Omit<DadosKalman, keyof DadosBase>
  | Omit<DadosFuzzy, keyof DadosBase>
  | Omit<DadosPid, keyof DadosBase>;

type ComponenteNo = NodeTypes[string];

export interface DefinicaoBloco {
  rotulo: string;
  descricao: string;
  /** Função, não objeto: `tfs`/`script`/`fuzzy`/`mpc` embutem array/objeto mutável
   *  (`matrix`, `output_eu`, `variables`) que precisa nascer novo a cada bloco — um literal
   *  compartilhado faria dois blocos novos apontarem para o mesmo objeto (era o
   *  comportamento de `matrizPadrao()`/`{}` chamados por instância em `criarBloco`, agora
   *  preservado aqui). */
  defaults: () => ConfigDoBloco;
  Node: ComponenteNo;
}

/** Defaults dos blocos de filtro (ADR-026), compartilhados pelo registro e por `lerNo`
 *  (`graph.ts`): o bloco recém-arrastado já nasce com uma config que passa no save
 *  (`measurement_noise` > 0), e um `graph_json` com o campo corrompido cai no mesmo valor em
 *  vez de virar `NaN`. */
export const PADRAO_FIRST_ORDER = { tau: 5 } as const;
export const PADRAO_KALMAN = { measurement_noise: 1, process_noise: 0.1 } as const;

/** Defaults do PID (ADR-031, RF-551): estrutura ISA, tempos em segundos, derivativa
 *  desligada de fábrica (PI é o padrão industrial), faixa de saída 0..100 (MV em %). */
export const PADRAO_PID = {
  kc: 1,
  ti_seconds: 60,
  td_seconds: 0,
  setpoint: 0,
  output_min: 0,
  output_max: 100,
  auto_mode: true,
  proportional_on_measurement: false,
  differential_on_measurement: true,
  starting_output: 0,
} as const;

export const REGISTRO_BLOCO: Record<TipoBloco, DefinicaoBloco> = {
  opc_read: {
    rotulo: "Leitura OPC",
    descricao: "Lê o valor corrente de uma tag do projeto",
    defaults: () => ({ tag_id: null }),
    Node: NoLeituraOpc,
  },
  opc_write: {
    rotulo: "Escrita OPC",
    descricao: "Escreve o valor da entrada em uma tag do projeto",
    defaults: () => ({ tag_id: null }),
    Node: NoEscritaOpc,
  },
  script: {
    rotulo: "Script",
    descricao: "Código Python com IN1..INn e OUT1..OUTn",
    defaults: () => ({ n_inputs: 1, n_outputs: 1, code: "OUT1 = IN1\n", output_eu: {} }),
    Node: NoScriptPython,
  },
  first_order: {
    rotulo: "Filtro 1ª ordem",
    descricao: "Suaviza o sinal por constante de tempo (τ)",
    defaults: () => ({ ...PADRAO_FIRST_ORDER }),
    Node: NoFiltroPrimeiraOrdem,
  },
  kalman: {
    rotulo: "Filtro Kalman",
    descricao: "Estima o valor verdadeiro de um sinal ruidoso",
    defaults: () => ({ ...PADRAO_KALMAN }),
    Node: NoFiltroKalman,
  },
  tfs: {
    rotulo: "TFS",
    descricao: "Matriz 2x2 de funções de transferência (SOPDT/IOPDT)",
    defaults: () => ({ matrix: matrizPadrao(), output_eu: {} }),
    Node: NoTfsMatriz,
  },
  mpc: {
    rotulo: "MPC",
    descricao: "Controle preditivo multivariável — portas dinâmicas conforme o config",
    defaults: () => ({
      name: "",
      multiplier: 1,
      variables: { mvs: [], cvs: [], constraints: [], dvs: [] },
      models: {},
    }),
    Node: NoMpc,
  },
  fuzzy: {
    rotulo: "Fuzzy",
    descricao: "Controlador fuzzy (FLL)",
    defaults: () => ({
      n_inputs: contratoFuzzy.default_counts.n_inputs,
      n_outputs: contratoFuzzy.default_counts.n_outputs,
      fll: contratoFuzzy.default_fll,
      output_eu: {},
    }),
    Node: NoFuzzy,
  },
  pid: {
    rotulo: "PID",
    descricao: "Controlador PID (ISA) — PV, SP e saída",
    defaults: () => ({ ...PADRAO_PID }),
    Node: NoPid,
  },
};

const TIPOS_DO_REGISTRO = Object.keys(REGISTRO_BLOCO) as TipoBloco[];

/** Rótulo por tipo — reexportado por `graph.ts` (a maioria dos consumidores já importa de
 *  lá; trocar 6 arquivos de import só para mover o dono não paga o frete). */
export const ROTULO_BLOCO: Record<TipoBloco, string> = Object.fromEntries(
  TIPOS_DO_REGISTRO.map((tipo) => [tipo, REGISTRO_BLOCO[tipo].rotulo]),
) as Record<TipoBloco, string>;

/** Referência estável: `nodeTypes` novo a cada render faz o React Flow remontar os nós.
 *  Reexportado por `nodes/index.tsx` para `FlowEditorPage.tsx` continuar importando de
 *  `"./nodes"` sem mudança. */
export const TIPOS_DE_NO: NodeTypes = Object.fromEntries(
  TIPOS_DO_REGISTRO.map((tipo) => [tipo, REGISTRO_BLOCO[tipo].Node]),
);
