import {
  contratoFuzzy,
  contratoFuzzyLoop,
  contratoSensorVirtual,
  matrizPadrao,
  y0Padrao,
  type DadosBase,
  type DadosBusPublish,
  type DadosBusSubscribe,
  type DadosConstant,
  type DadosDeadTime,
  type DadosFirstOrder,
  type DadosFuzzy,
  type DadosKalman,
  type DadosIntegrator,
  type DadosLeadLag,
  type DadosMpc,
  type DadosPid,
  type DadosFuzzyLoop,
  type DadosPidLoop,
  type DadosScript,
  type DadosScaler,
  type DadosSensorVirtual,
  type DadosTag,
  type DadosTfs,
  type TipoBloco,
} from "./graph";
import type { FuzzyLoopConfig, PidLoopConfig } from "../../lib/contracts.gen";

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
  | Omit<DadosPid, keyof DadosBase>
  | Omit<DadosPidLoop, keyof DadosBase>
  | Omit<DadosFuzzyLoop, keyof DadosBase>
  | Omit<DadosScaler, keyof DadosBase>
  | Omit<DadosIntegrator, keyof DadosBase>
  | Omit<DadosLeadLag, keyof DadosBase>
  | Omit<DadosDeadTime, keyof DadosBase>
  | Omit<DadosConstant, keyof DadosBase>
  | Omit<DadosBusPublish, keyof DadosBase>
  | Omit<DadosBusSubscribe, keyof DadosBase>
  | Omit<DadosSensorVirtual, keyof DadosBase>;

export interface DefinicaoBloco {
  rotulo: string;
  descricao: string;
  /** Função, não objeto: `tfs`/`script`/`fuzzy`/`mpc` embutem array/objeto mutável
   *  (`matrix`, `output_eu`, `variables`) que precisa nascer novo a cada bloco — um literal
   *  compartilhado faria dois blocos novos apontarem para o mesmo objeto (era o
   *  comportamento de `matrizPadrao()`/`{}` chamados por instância em `criarBloco`, agora
   *  preservado aqui). */
  defaults: () => ConfigDoBloco;
}

/** Defaults dos blocos de filtro (ADR-026), compartilhados pelo registro e por `lerNo`
 *  (`graph.ts`): o bloco recém-arrastado já nasce com uma config que passa no save
 *  (`measurement_noise` > 0), e um `graph_json` com o campo corrompido cai no mesmo valor em
 *  vez de virar `NaN`. */
export const PADRAO_FIRST_ORDER = { tau: 5 } as const;
export const PADRAO_KALMAN = { measurement_noise: 1, process_noise: 0.1 } as const;

/** Bases de tempo do Integrator — a mesma lista do `IntegratorConfig.time_base` no
 *  servidor (`parse.py`), espelhada aqui para o `lerNo` e o modal. */
export const BASES_TEMPO = ["s", "min", "h"] as const;

/** Defaults dos blocos utilitários: Scaler nasce 0-100 → 4-20 (a conversão canônica %→mA)
 *  e o Integrator na base por minuto (totalização de vazão é o caso típico). */
export const PADRAO_SCALER = { in_min: 0, in_max: 100, out_min: 4, out_max: 20 } as const;
export const PADRAO_INTEGRATOR = { time_base: "min" } as const;

/** Lead-Lag nasce NEUTRO (`tau_lead == tau_lag`, ganho 1): o bloco recém-arrastado não altera
 *  o sinal até ser configurado. Um default que já compensasse alguma coisa seria surpresa na
 *  válvula. Razão 1 e `tau_lag > 0` passam no save. */
export const PADRAO_LEAD_LAG = { gain: 1, tau_lead: 10, tau_lag: 10 } as const;
/** Tempo morto nasce em 0 s: passagem direta até o engenheiro informar o θ. */
export const PADRAO_DEAD_TIME = { theta: 0 } as const;

/** Constante nasce em 0 — valor neutro que passa no save sem exigir ajuste imediato. */
export const PADRAO_CONSTANT = { value: 0 } as const;

/** Barramento (ADR-042): os dois nascem com `key` vazia — o bloco recém-arrastado ainda não
 *  identifica variável nenhuma, e o engenheiro preenche antes do primeiro save (o servidor
 *  rejeita chave vazia). */
export const PADRAO_BUS_PUBLISH = { key: "" } as const;
export const PADRAO_BUS_SUBSCRIBE = { key: "" } as const;

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

/** Espelho MANUAL dos defaults do servidor (`LoopBaseConfig` + `PidLoopConfig`, `parse.py`) —
 *  tudo que o servidor preenche sozinho quando o campo falta. O ADR-034 proíbe gerar tabela de
 *  default; a trava é o teste próprio `test_loop_config_defaults.py`, que compara esta tabela
 *  com os `model_fields` do Pydantic. Os 3 campos sem default no servidor (`sp_hi_lim`,
 *  `sp_lo_lim`, `kc`) ficam de fora: a anotação `Omit<…>` faz o `tsc` acusar campo esquecido. */
export const DEFAULT_SERVIDOR_PID_LOOP: Omit<PidLoopConfig, "sp_hi_lim" | "sp_lo_lim" | "kc"> = {
  permitted: ["oos", "man", "auto"],
  normal: "auto",
  shed_opt: "shed_to_auto",
  shed_no_return: false,
  direct_acting: false,
  sp_pv_track_in_man: true,
  use_pv_for_bkcal: false,
  track_enable: false,
  track_in_manual: false,
  sp_rate_up: null,
  sp_rate_dn: null,
  out_hi_lim: 100,
  out_lo_lim: 0,
  out_rate_up: null,
  out_rate_dn: null,
  out_scale_lo: 0,
  out_scale_hi: 100,
  out_startup: 0,
  pv_ftime: 0,
  trk_val: 0,
  lo_val: 0,
  ff_scale_lo: 0,
  ff_scale_hi: 100,
  ff_gain: 1,
  ff_enable: false,
  ti_seconds: 0,
  td_seconds: 0,
  n: 8,
  beta: 1,
  gamma: 0,
  gap_band: 0,
  gap_gain: 1,
};

/** Idem para o Fuzzy Malha (`LoopBaseConfig` + `FuzzyLoopConfig`). Sem default no servidor:
 *  `sp_hi_lim`, `sp_lo_lim`, `ke`, `ku`. O `fll` também fica de fora — sai do contrato
 *  (`PORT_CONTRACTS.fuzzy_loop.default_fll`) dentro do thunk de `defaults`. */
export const DEFAULT_SERVIDOR_FUZZY_LOOP: Omit<
  FuzzyLoopConfig,
  "sp_hi_lim" | "sp_lo_lim" | "ke" | "ku" | "fll"
> = {
  permitted: ["oos", "man", "auto"],
  normal: "auto",
  shed_opt: "shed_to_auto",
  shed_no_return: false,
  direct_acting: false,
  sp_pv_track_in_man: true,
  use_pv_for_bkcal: false,
  track_enable: false,
  track_in_manual: false,
  sp_rate_up: null,
  sp_rate_dn: null,
  out_hi_lim: 100,
  out_lo_lim: 0,
  out_rate_up: null,
  out_rate_dn: null,
  out_scale_lo: 0,
  out_scale_hi: 100,
  out_startup: 0,
  pv_ftime: 0,
  trk_val: 0,
  lo_val: 0,
  ff_scale_lo: 0,
  ff_scale_hi: 100,
  ff_gain: 1,
  ff_enable: false,
  n_loops: 1,
  kde: 0,
  tf_de: 1,
  lut_enabled: false,
  lut_resolution: 65,
};

/** Defaults do PID Malha (ADR-039) para o bloco recém-arrastado: o espelho do servidor mais o
 *  mínimo que o servidor exige (limites de SP e KC) e a sintonia PI conservadora (TI = 60 s —
 *  o servidor nasceria P puro, `ti_seconds = 0`). Passa no save. */
export const PADRAO_PID_LOOP: PidLoopConfig = {
  ...DEFAULT_SERVIDOR_PID_LOOP,
  sp_hi_lim: 100,
  sp_lo_lim: 0,
  kc: 1,
  ti_seconds: 60,
};

/** Defaults do Fuzzy Malha (SPEC_FUZZY §6.4): sintonia de comissionamento — KE cobrindo 20
 *  EU de erro, KU conservador (a spec recomenda 1–5 %span/s) e KDE em zero, que é a ordem
 *  recomendada em campo (a derivada entra por último). O `fll` NÃO mora aqui: sai do
 *  contrato dentro do thunk de `defaults`, senão o ciclo de import com `graph.ts` (que lê
 *  esta const) avaliaria `contratoFuzzyLoop` antes da inicialização. */
export const PADRAO_FUZZY_LOOP: Omit<FuzzyLoopConfig, "fll"> = {
  ...DEFAULT_SERVIDOR_FUZZY_LOOP,
  sp_hi_lim: 100,
  sp_lo_lim: 0,
  ke: 0.05,
  ku: 2,
};

/** Os três sensores virtuais (RF-581, ADR-046) só diferem no rótulo: mesma descrição e mesma
 *  config inicial — `n_inputs` vem do contrato (lido dentro do thunk, não na avaliação do
 *  módulo, pelo mesmo motivo do `fll` do Fuzzy Malha) e a unidade da saída nasce vazia. */
function sensorVirtual(rotulo: string): DefinicaoBloco {
  return {
    rotulo,
    descricao: "Estima uma variável de laboratório por modelo treinado",
    defaults: () => ({ n_inputs: contratoSensorVirtual.default_counts.n_inputs, output_eu: "" }),
  };
}

export const REGISTRO_BLOCO: Record<TipoBloco, DefinicaoBloco> = {
  opc_read: {
    rotulo: "Leitura OPC",
    descricao: "Lê o valor corrente de uma tag do projeto",
    defaults: () => ({ tag_id: null }),
  },
  opc_write: {
    rotulo: "Escrita OPC",
    descricao: "Escreve o valor da entrada em uma tag do projeto",
    defaults: () => ({ tag_id: null }),
  },
  constant: {
    rotulo: "Constante",
    descricao: "Valor numérico fixo (float) na saída",
    defaults: () => ({ ...PADRAO_CONSTANT }),
  },
  script: {
    rotulo: "Script",
    descricao: "Código Python com IN1..INn e OUT1..OUTn",
    defaults: () => ({ n_inputs: 1, n_outputs: 1, code: "OUT1 = IN1\n", output_eu: {} }),
  },
  first_order: {
    rotulo: "Filtro 1ª ordem",
    descricao: "Suaviza o sinal por constante de tempo (τ)",
    defaults: () => ({ ...PADRAO_FIRST_ORDER }),
  },
  kalman: {
    rotulo: "Filtro Kalman",
    descricao: "Estima o valor verdadeiro de um sinal ruidoso",
    defaults: () => ({ ...PADRAO_KALMAN }),
  },
  tfs: {
    rotulo: "TFS",
    descricao: "Matriz 2x2 de funções de transferência (SOPDT/IOPDT)",
    defaults: () => ({ matrix: matrizPadrao(), output_eu: {}, y0: y0Padrao() }),
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
  },
  fuzzy: {
    rotulo: "Fuzzy",
    descricao: "Controlador fuzzy (FLL)",
    defaults: () => ({
      n_inputs: contratoFuzzy.default_counts.n_inputs,
      n_outputs: contratoFuzzy.default_counts.n_outputs,
      fll: contratoFuzzy.default_fll,
      output_eu: {},
      setpoint: null,
      sp_source: null,
    }),
  },
  pid: {
    rotulo: "PID",
    descricao: "Controlador PID (ISA) — PV, SP e saída",
    defaults: () => ({ ...PADRAO_PID }),
  },
  pid_loop: {
    rotulo: "PID Malha",
    descricao: "PID industrial com modos, cascata e tracking (ADR-039)",
    defaults: () => ({ ...PADRAO_PID_LOOP }),
  },
  fuzzy_loop: {
    rotulo: "Fuzzy Malha",
    descricao: "Controle fuzzy industrial com modos e cascata (ADR-039)",
    defaults: () => ({ ...PADRAO_FUZZY_LOOP, fll: contratoFuzzyLoop.default_fll }),
  },
  scaler: {
    rotulo: "Scaler",
    descricao: "Reescala o sinal da faixa de entrada para a faixa de saída",
    defaults: () => ({ ...PADRAO_SCALER }),
  },
  integrator: {
    rotulo: "Integrador",
    descricao: "Totaliza o sinal no tempo (base s/min/h), com reset",
    defaults: () => ({ ...PADRAO_INTEGRATOR }),
  },
  lead_lag: {
    rotulo: "Lead-Lag",
    descricao: "Compensação dinâmica: ganho, avanço (τ lead) e atraso (τ lag)",
    defaults: () => ({ ...PADRAO_LEAD_LAG }),
  },
  dead_time: {
    rotulo: "Tempo morto",
    descricao: "Atrasa o sinal em θ segundos",
    defaults: () => ({ ...PADRAO_DEAD_TIME }),
  },
  bus_publish: {
    rotulo: "Barramento-Publicar",
    descricao: "Publica o valor da entrada no barramento, para outro flow consumir",
    defaults: () => ({ ...PADRAO_BUS_PUBLISH }),
  },
  bus_subscribe: {
    rotulo: "Barramento-Assinar",
    descricao: "Consome do barramento um valor publicado por outro flow",
    defaults: () => ({ ...PADRAO_BUS_SUBSCRIBE }),
  },
  soft_sensor_pls: sensorVirtual("Sensor virtual PLS"),
  soft_sensor_esn: sensorVirtual("Sensor virtual ESN"),
  soft_sensor_lstm: sensorVirtual("Sensor virtual LSTM"),
};

const TIPOS_DO_REGISTRO = Object.keys(REGISTRO_BLOCO) as TipoBloco[];

/** Rótulo por tipo — reexportado por `graph.ts` (a maioria dos consumidores já importa de
 *  lá; trocar 6 arquivos de import só para mover o dono não paga o frete). */
export const ROTULO_BLOCO: Record<TipoBloco, string> = Object.fromEntries(
  TIPOS_DO_REGISTRO.map((tipo) => [tipo, REGISTRO_BLOCO[tipo].rotulo]),
) as Record<TipoBloco, string>;

