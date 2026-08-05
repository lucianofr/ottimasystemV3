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

export type ContratoPorta = ContratoPortaFixa | ContratoPortaDinamica;

export const PORT_CONTRACTS: Record<"opc_read" | "opc_write" | "script" | "tfs" | "mpc", ContratoPorta> = {
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
    "source": "config.cvs + config.constraints + config.dvs (entrada) / config.mvs (saída) — spec F4 §2.2, plano F4a tarefa 1.2",
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
}

export interface MpcState {
  modes: MpcModes;
  status: MpcStatus;
  vars: Record<string, MpcVarState>;
  cost: number;
  prediction: MpcPrediction;
}
