"""Fonte única dos contratos de porta por bloco + payloads do WS, exportados como JSON.

Débito 2+4 do plano F4a: três espelhos TS mantidos à mão (`graph.ts`, `nodes/index.tsx`,
`useFlowStatus.ts`) divergiam em silêncio de `flowgraph.py`/`bus.py`. Este módulo é a fonte
única; `frontend/scripts/generate-contracts.mjs` consome a saída daqui e gera
`frontend/src/lib/contracts.gen.ts`.

`PORT_CONTRACTS` descreve, por tipo de bloco, ou uma lista fixa de portas (nome, direção,
tipo) ou uma regra dinâmica (`dynamic: true` + `source` + `rules`). `opc_read`/`opc_write`/
`tfs` são fixos; `script` é dinâmico de verdade (IN1..INn/OUT1..OUTn por `n_inputs`/
`n_outputs`, spec F3 §3.3) — o gerador TS materializa esse padrão em `PortaFixa[]` a partir
de `count_field`/`prefix`/`max`, sem precisar do config de nenhum flow específico.

`mpc` NÃO segue o mesmo padrão: `flowgraph.validate.py` (plano F4a tarefa 1.2, já concluída)
deriva as portas por INSTÂNCIA — `_input_handles`/`_output_handles` leem
`config.variables.{cvs,constraints,dvs}` (entrada) e `config.variables.mvs` (saída), e o
nome de cada porta é o `id` estável que o usuário deu à variável no config daquele flow
(spec F4 §2.1-5, decisão A-10) — não um `IN{i}` templável. Por isso a entrada `mpc` aqui
embaixo é só metadado descritivo (a origem da regra, para leitura humana e para a chave do
`Record` TS existir) — `frontend/src/features/flows/graph.ts::handlesEntrada`/
`handlesSaida` NUNCA a consultam; resolvem direto do `BlocoNode.config`, como só eles podem
(ver o comentário lá). `rules`/`source` do `mpc` não alimentam nenhum gerador TS de nome de
porta, ao contrário de `script`.

`ws_payloads` é o JSON Schema (`model_json_schema()`) dos modelos do barramento que o canvas
ao vivo consome. `MpcVarState` (spec F4 §5.1) chega aninhado em `MpcState.vars` — não precisa
entrar em `_WS_MODELS`: o gerador TS achata `$defs` e produz a interface própria mesmo assim.

Executável como `uv run python -m ottima_core.contracts_export`.
"""

import json

from ottima_core.bus import FlowStatus, MpcState, PortValue
from ottima_core.flowgraph import MAX_SCRIPT_PORTS

PORT_CONTRACTS: dict[str, dict[str, object]] = {
    "opc_read": {
        "dynamic": False,
        # "tag": tipo resolvido pela tag ligada (num p/ float|int, bool p/ bool — decisão A-5,
        # `flowgraph._port_kind`), não é fixo por tipo de bloco.
        "ports": [{"name": "out", "direction": "output", "type": "tag"}],
    },
    "opc_write": {
        "dynamic": False,
        "ports": [{"name": "in", "direction": "input", "type": "tag"}],
    },
    "script": {
        "dynamic": True,
        "source": "config.n_inputs / config.n_outputs (spec F3 §3.3)",
        "rules": [
            {
                "direction": "input",
                "prefix": "IN",
                "count_field": "n_inputs",
                "max": MAX_SCRIPT_PORTS,
                "type": "bivalent",
            },
            {
                "direction": "output",
                "prefix": "OUT",
                "count_field": "n_outputs",
                "max": MAX_SCRIPT_PORTS,
                "type": "bivalent",
            },
        ],
    },
    "tfs": {
        "dynamic": False,
        "ports": [
            {"name": "u1", "direction": "input", "type": "num"},
            {"name": "u2", "direction": "input", "type": "num"},
            {"name": "y1", "direction": "output", "type": "num"},
            {"name": "y2", "direction": "output", "type": "num"},
        ],
    },
    "mpc": {
        "dynamic": True,
        "source": (
            "config.variables.cvs + config.variables.constraints + config.variables.dvs "
            "(entrada) / config.variables.mvs (saída) — nome de porta = id da variável, "
            "por instância (spec F4 §2.1-5, decisão A-10; derivado em "
            "flowgraph.validate._input_handles/_output_handles, plano F4a tarefa 1.2)"
        ),
        "rules": [
            {"direction": "input", "source": "ids de cvs + constraints + dvs", "type": "num"},
            {"direction": "output", "source": "ids de mvs", "type": "num"},
        ],
    },
}

# MpcVarState (tarefa 1.3) vem aninhado no schema de MpcState (`vars: dict[str, MpcVarState]`)
# — o gerador TS achata `$defs`, dispensa entrada própria aqui.
_WS_MODELS = (FlowStatus, PortValue, MpcState)


def build_contracts() -> dict[str, object]:
    """Monta o payload completo (porta + WS) — puro, sem I/O."""
    return {
        "port_contracts": PORT_CONTRACTS,
        "ws_payloads": {model.__name__: model.model_json_schema() for model in _WS_MODELS},
    }


def main() -> None:
    print(json.dumps(build_contracts()))


if __name__ == "__main__":
    main()
