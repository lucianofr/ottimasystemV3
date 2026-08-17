// GERADO — não editar; fonte: ottima_core.contracts_export
// Regenerar: npm run generate:contracts

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

export type ContratoPorta = ContratoPortaFixa | ContratoPortaDinamica | ContratoPortaDinamicaComDefault;

export const PORT_CONTRACTS: Record<"opc_read" | "opc_write" | "script" | "fuzzy" | "first_order" | "kalman" | "pid" | "tfs" | "mpc", ContratoPorta> = {
  "opc_read": {
    "dynamic": false,
    "ports": [
      {
        "name": "out",
        "direction": "output",
        "type": "tag"
      }
    ]
  },
  "opc_write": {
    "dynamic": false,
    "ports": [
      {
        "name": "in",
        "direction": "input",
        "type": "tag"
      }
    ]
  },
  "script": {
    "dynamic": true,
    "source": "config.n_inputs / config.n_outputs (spec F3 §3.3)",
    "rules": [
      {
        "direction": "input",
        "prefix": "IN",
        "count_field": "n_inputs",
        "max": 8,
        "type": "bivalent"
      },
      {
        "direction": "output",
        "prefix": "OUT",
        "count_field": "n_outputs",
        "max": 8,
        "type": "bivalent"
      }
    ]
  },
  "fuzzy": {
    "dynamic": true,
    "source": "config.n_inputs / config.n_outputs (RF-541, ADR-029)",
    "rules": [
      {
        "direction": "input",
        "prefix": "IN",
        "count_field": "n_inputs",
        "max": 8,
        "type": "num"
      },
      {
        "direction": "output",
        "prefix": "OUT",
        "count_field": "n_outputs",
        "max": 8,
        "type": "num"
      }
    ],
    "default_fll": "Engine: tsukamoto\nInputVariable: X\n  enabled: true\n  range: -10.000 10.000\n  lock-range: false\n  term: small Bell -10.000 5.000 3.000\n  term: medium Bell 0.000 5.000 3.000\n  term: large Bell 10.000 5.000 3.000\nOutputVariable: Ramps\n  enabled: true\n  range: 0.000 1.000\n  lock-range: false\n  aggregation: none\n  defuzzifier: WeightedAverage Automatic\n  default: nan\n  lock-previous: false\n  term: b Ramp 0.600 0.400\n  term: a Ramp 0.000 0.250\n  term: c Ramp 0.700 1.000\nOutputVariable: Sigmoids\n  enabled: true\n  range: 0.0210 1.000\n  lock-range: false\n  aggregation: none\n  defuzzifier: WeightedAverage Automatic\n  default: nan\n  lock-previous: false\n  term: b Sigmoid 0.500 -30.000\n  term: a Sigmoid 0.130 30.000\n  term: c Sigmoid 0.830 30.000\nOutputVariable: ZSShapes\n  enabled: true\n  range: 0.000 1.000\n  lock-range: false\n  aggregation: none\n  defuzzifier: WeightedAverage Automatic\n  default: nan\n  lock-previous: false\n  term: b ZShape 0.300 0.600\n  term: a SShape 0.000 0.250\n  term: c SShape 0.700 1.000\nOutputVariable: Concaves\n  enabled: true\n  range: 0.000 1.000\n  lock-range: false\n  aggregation: none\n  defuzzifier: WeightedAverage Automatic\n  default: nan\n  lock-previous: false\n  term: b Concave 0.500 0.400\n  term: a Concave 0.240 0.250\n  term: c Concave 0.900 1.000\nRuleBlock: \n  enabled: true\n  conjunction: none\n  disjunction: none\n  implication: none\n  activation: General\n  rule: if X is small then Ramps is a and Sigmoids is a and ZSShapes is a and Concaves is a\n  rule: if X is medium then Ramps is b and Sigmoids is b and ZSShapes is b and Concaves is b\n  rule: if X is large then Ramps is c and Sigmoids is c and ZSShapes is c and Concaves is c",
    "default_counts": {
      "n_inputs": 1,
      "n_outputs": 4
    },
    "max_fll_length": 200000
  },
  "first_order": {
    "dynamic": false,
    "ports": [
      {
        "name": "in",
        "direction": "input",
        "type": "num"
      },
      {
        "name": "out",
        "direction": "output",
        "type": "num"
      }
    ]
  },
  "kalman": {
    "dynamic": false,
    "ports": [
      {
        "name": "in",
        "direction": "input",
        "type": "num"
      },
      {
        "name": "out",
        "direction": "output",
        "type": "num"
      }
    ]
  },
  "pid": {
    "dynamic": false,
    "ports": [
      {
        "name": "pv",
        "direction": "input",
        "type": "num"
      },
      {
        "name": "sp",
        "direction": "input",
        "type": "num"
      },
      {
        "name": "out",
        "direction": "output",
        "type": "num"
      }
    ]
  },
  "tfs": {
    "dynamic": false,
    "ports": [
      {
        "name": "u1",
        "direction": "input",
        "type": "num"
      },
      {
        "name": "u2",
        "direction": "input",
        "type": "num"
      },
      {
        "name": "y1",
        "direction": "output",
        "type": "num"
      },
      {
        "name": "y2",
        "direction": "output",
        "type": "num"
      }
    ]
  },
  "mpc": {
    "dynamic": true,
    "source": "config.variables.cvs + config.variables.constraints + config.variables.dvs (entrada) / config.variables.mvs (saída) — nome de porta = id da variável, por instância (spec F4 §2.1-5, decisão A-10; derivado em flowgraph.validate._input_handles/_output_handles, plano F4a tarefa 1.2)",
    "rules": [
      {
        "direction": "input",
        "source": "ids de cvs + constraints + dvs",
        "type": "num"
      },
      {
        "direction": "output",
        "source": "ids de mvs",
        "type": "num"
      },
      {
        "direction": "output",
        "source": "portas fixas, sempre presentes mesmo sem variáveis (decisão A-10 revista): local, auto",
        "type": "num"
      }
    ]
  }
};

// --------------------------------------------------------------------------------------
// Payloads do WS (JSON Schema via model_json_schema(), spec F3 §4.2 / bus.py)
// --------------------------------------------------------------------------------------

export interface PortValue {
  v: number | boolean | null;
  ok: boolean;
}

export interface FlowStatus {
  state: "running" | "stopped" | "failed";
  scan_ms: number;
  overruns: number;
  ts: string;
  ports: Record<string, Record<string, PortValue>>;
}

export interface MpcModes {
  local_remote: "local" | "remote";
  man_auto: "man" | "auto";
}

export interface MpcPrediction {
  ts: string;
  t: number[];
  cv: number[][];
  mv: number[][];
}

export interface MpcStatus {
  solver: "ok" | "overrun" | "error" | "building" | "idle";
  overruns: number;
  last_solve_ms: number;
  armed: boolean;
  input_valid: boolean;
}

export interface MpcVarState {
  v: number;
  sp: number | null;
  status: string | null;
}

export interface SstoRun {
  run_id: string;
  config_hash: string;
  model_hash: string;
  status: "optimal" | "relaxed" | "infeasible" | "unbounded" | "error";
  solver: string;
  solve_ms: number;
  objective: number;
  mv: Record<string, number>;
  cv_ss: Record<string, number>;
  bias: Record<string, number>;
  dv: Record<string, number>;
  costs: Record<string, number>;
  delta_mv: Record<string, number>;
  mv_target: Record<string, number>;
  cv_target: Record<string, number>;
  given_up: string[];
  active_constraints: string[];
  duals: Record<string, number>;
}

export interface MpcState {
  ts: string;
  modes: MpcModes;
  status: MpcStatus;
  vars: Record<string, MpcVarState>;
  cost: number;
  prediction: MpcPrediction;
  ssto: SstoRun | null;
}

export interface FuzzyTermDegree {
  term: string;
  degree: number;
}

export interface FuzzyVarState {
  port: string;
  name: string;
  v: number | null;
  terms: FuzzyTermDegree[];
}

export interface FuzzyState {
  ts: string;
  ok: boolean;
  inputs: FuzzyVarState[];
  rules: number[];
  outputs: FuzzyVarState[];
}

// --------------------------------------------------------------------------------------
// Forma dos configs de bloco (JSON Schema via model_json_schema(), ARCH-06/TD-018): campos
// de MvVar/CvVar/ConstraintVar/DvVar/MpcConfig/ScriptConfig/FuzzyConfig/PidConfig, mesmo
// mecanismo dos payloads do WS acima (ADR-034: forma é gerada, regra travada por golden,
// default pode continuar espelhado à mão). TfsConfig fica de fora — ver
// contracts_export.py::_NODE_CONFIG_MODELS.
// --------------------------------------------------------------------------------------

export interface Limits {
  min: number;
  max: number;
}

export interface ModeValues {
  auto: number;
  target: number;
}

export interface PidBinding {
  write_tag_id: number;
  target_mode: "rcas" | "cas" | "rout";
  mode_cmd_tag_id: number;
  mode_read_tag_id: number | null;
  readback_tag_id: number;
  mode_values: ModeValues;
}

export interface MvVar {
  id: string;
  name: string;
  eu: string;
  description: string;
  zero: number;
  span: number;
  limits: Limits;
  max_rate: number;
  du_min: number;
  move_weight: number;
  initial_value: number;
  operating_point: number;
  readback_tag_id: number | null;
  pid: PidBinding | null;
  objective: "none" | "maximize" | "minimize" | "psv" | "equalize";
  psv: number | null;
  fail_action: "no_action" | "shed_local" | "manual";
  local_shed_mode: number | null;
}

export interface CvVar {
  id: string;
  name: string;
  eu: string;
  description: string;
  zero: number;
  span: number;
  kind: "selfreg" | "integrating";
  tss: number;
  weight: number;
  sp_limits: Limits;
  priority: number;
  objective: "none" | "maximize" | "minimize" | "observe_limit" | "target" | "psv";
  traj_tau_s: number;
  track_sp: boolean;
  fail_action: "no_action" | "shed_local" | "manual" | "simulate_manual" | "simulate_shed_local";
  fail_timeout_s: number;
  sp_range_pct: number | null;
  remote_sp_tag_id: number | null;
}

export interface Range {
  low: number;
  high: number;
}

export interface ConstraintVar {
  id: string;
  name: string;
  eu: string;
  description: string;
  zero: number;
  span: number;
  kind: "selfreg" | "integrating";
  tss: number;
  range: Range;
  priority: number;
  objective: "none" | "maximize" | "minimize";
  fail_action: "no_action" | "shed_local" | "manual" | "simulate_manual" | "simulate_shed_local";
  fail_timeout_s: number;
}

export interface DvVar {
  id: string;
  name: string;
  eu: string;
  zero: number;
  span: number;
  range: Range | null;
  operating_point: number;
}

export interface EconomicsConfig {
  enabled: boolean;
  costs: Record<string, number>;
  slack_weight: number;
  detuning_weight: number;
  solver: "highs" | "osqp" | "gurobi";
  integrating_tolerance: number;
}

export interface MpcVariables {
  mvs: MvVar[];
  cvs: CvVar[];
  constraints: ConstraintVar[];
  dvs: DvVar[];
}

export interface PairModel {
  enabled: boolean;
  params: Record<string, number>;
}

export interface MpcConfig {
  name: string;
  multiplier: number;
  variables: MpcVariables;
  models: Record<string, Record<string, PairModel>>;
  economics: EconomicsConfig | null;
}

export interface ScriptConfig {
  n_inputs: number;
  n_outputs: number;
  code: string;
  output_eu: Record<string, string>;
}

export interface FuzzyConfig {
  fll: string;
  n_inputs: number;
  n_outputs: number;
  output_eu: Record<string, string>;
}

export interface PidConfig {
  kc: number;
  ti_seconds: number;
  td_seconds: number;
  setpoint: number;
  output_min: number | null;
  output_max: number | null;
  auto_mode: boolean;
  proportional_on_measurement: boolean;
  differential_on_measurement: boolean;
  starting_output: number;
}

export interface SopdtParams {
  K: number;
  tau1: number;
  tau2: number;
  theta: number;
}

export interface IopdtParams {
  Ki: number;
  theta: number;
}
