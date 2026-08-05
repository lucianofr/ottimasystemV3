"""Validação semântica do `graph_json` — tags do projeto, Ts do flow e topologia (RF-302/307).

Núcleo puro — nada de SQLAlchemy nem de `services/` aqui: o chamador traduz linhas do banco em
`TagRef`. `validate_graph` nunca levanta por conteúdo de grafo: devolve `ValidationResult`. Ver
`ottima_core/flowgraph/__init__.py` para a divisão de responsabilidade completa do pacote.
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from ottima_core.flowgraph.mpc_config import (
    MpcConfig,
    MvVar,
    RowKind,
    derive_horizons,
    mpc_state_dimension,
)
from ottima_core.flowgraph.parse import _TAG_DIRECTION, FlowEdge, FlowGraph, FlowNode

MAX_DELAY_SAMPLES = 7200  # teto da fila de tempo morto do TFS (spec §3.4)

# "bivalent" é a porta do bloco Script, que aceita numérico e booleano (decisão A-5).
PortKind = Literal["num", "bool", "bivalent"]
_PORT_LABEL: dict[str, str] = {"num": "numérica", "bool": "booleana", "bivalent": "bivalente"}

# Teto de contagem por categoria de variável do bloco `mpc` (spec §2.2-2, [NOVA]).
_MPC_MV_RANGE = (1, 4)
_MPC_CV_RESTRICAO_RANGE = (1, 6)
_MPC_DV_RANGE = (0, 4)

# Params exigidos por `kind` de linha da matriz `models` (spec §2.1-2/§2.2-3, ADR-013).
_SELFREG_PARAMS = frozenset({"K", "tau1", "tau2", "theta"})
_INTEGRATING_PARAMS = frozenset({"Ki", "theta"})

# Campos de `pid` por direção exigida (spec §2.2-6): write/mode_cmd = W; readback/mode_read = R.
_PID_WRITE_FIELDS = ("write_tag_id", "mode_cmd_tag_id")
_PID_READ_FIELDS = ("readback_tag_id", "mode_read_tag_id")


class TagRef(BaseModel):
    """O que a validação precisa saber de uma tag; o chamador projeta a linha do banco."""

    id: int
    conn_id: int
    direction: Literal["r", "w"]
    data_type: Literal["float", "int", "bool"]


class ValidationResult(BaseModel):
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_graph(
    graph: FlowGraph, tags: Mapping[int, TagRef], ts_seconds: float
) -> ValidationResult:
    """Valida a semântica do grafo contra as tags do projeto e o Ts do flow.

    `tags` é o mapa `{tag_id: TagRef}` **das tags do projeto do flow** — recortar por projeto
    é responsabilidade do chamador. Por isso a mensagem de tag desconhecida cobre os dois
    casos (não existe / não é do projeto): daqui os dois são indistinguíveis.

    `ts_seconds` é o período de varredura do flow; a API deve converter o `Decimal` que o
    SQLAlchemy devolve em `Flow.ts_seconds`. Levanta `ValueError` se não for positivo — isso
    é erro de programação do chamador, não conteúdo de grafo.
    """
    if ts_seconds <= 0:
        raise ValueError("ts_seconds deve ser positivo para validar o teto de atraso do TFS")

    errors: list[str] = []
    warnings: list[str] = []
    by_id = {node.id: node for node in graph.nodes}

    # Tipa o config bruto de cada nó `mpc` antes de tudo: o resto da validação (portas
    # dinâmicas inclusive) depende de um `MpcConfig` e não deve arriscar `KeyError`/
    # `TypeError` num payload torto (spec §2.2-1, tarefa 1.2 do plano F4a).
    mpc_configs = _parse_mpc_configs(graph.nodes, errors)

    _check_exec_order(graph.nodes, errors)
    _check_tags(graph.nodes, tags, errors)
    _check_tfs_delay(graph.nodes, ts_seconds, errors)

    linked = _check_edge_endpoints(graph.edges, by_id, errors)
    resolved = _check_handles(linked, by_id, mpc_configs, errors)
    _check_fan_in(resolved, errors)
    _check_port_types(resolved, by_id, tags, errors)
    _check_required_inputs(graph.nodes, resolved, mpc_configs, errors)
    _check_cycles(graph.nodes, linked, errors)
    _collect_inversion_warnings(linked, by_id, warnings)

    _check_mpc_nodes(graph.nodes, mpc_configs, tags, ts_seconds, errors, warnings)

    return ValidationResult(errors=errors, warnings=warnings)


def _output_handles(node: FlowNode, mpc_configs: dict[str, MpcConfig]) -> tuple[str, ...]:
    if node.type == "opc_read":
        return ("out",)
    if node.type == "script":
        return tuple(f"OUT{i}" for i in range(1, node.config.n_outputs + 1))
    if node.type == "tfs":
        return ("y1", "y2")
    if node.type == "mpc":
        # Decisão A-10: uma saída por MV, handle = id estável da variável; podem ficar
        # desconectadas (a malha real usa as tags do `pid`).
        config = mpc_configs.get(node.id)
        return tuple(mv.id for mv in config.variables.mvs) if config else ()
    return ()


def _input_handles(node: FlowNode, mpc_configs: dict[str, MpcConfig]) -> tuple[str, ...]:
    if node.type == "opc_write":
        return ("in",)
    if node.type == "script":
        return tuple(f"IN{i}" for i in range(1, node.config.n_inputs + 1))
    if node.type == "tfs":
        return ("u1", "u2")
    if node.type == "mpc":
        # Decisão A-10: uma entrada por CV, Restrição e DV, handle = id estável da variável.
        config = mpc_configs.get(node.id)
        if config is None:
            return ()
        return tuple(
            var.id
            for var in (
                *config.variables.cvs,
                *config.variables.constraints,
                *config.variables.dvs,
            )
        )
    return ()


def _listing(handles: tuple[str, ...]) -> str:
    return ", ".join(handles) if handles else "(nenhuma)"


def _check_exec_order(nodes: list[FlowNode], errors: list[str]) -> None:
    total = len(nodes)
    by_order: dict[int, list[str]] = {}
    for node in nodes:
        by_order.setdefault(node.exec_order, []).append(node.id)

    for order in sorted(by_order):
        ids = by_order[order]
        if len(ids) > 1:
            errors.append(
                f"exec_order duplicado: o valor {order} é usado pelos blocos "
                f"{', '.join(ids)} (RF-307)"
            )

    missing = sorted(set(range(1, total + 1)) - set(by_order))
    outside = sorted(order for order in by_order if order > total)
    if missing or outside:
        detail: list[str] = []
        if missing:
            detail.append(f"faltam os valores {', '.join(str(value) for value in missing)}")
        if outside:
            detail.append(f"sobram os valores {', '.join(str(value) for value in outside)}")
        errors.append(
            f"exec_order deve ser contíguo de 1 a {total}, um por bloco: "
            f"{'; '.join(detail)} (RF-307, ADR-024)"
        )


def _check_tags(nodes: list[FlowNode], tags: Mapping[int, TagRef], errors: list[str]) -> None:
    for node in nodes:
        expected = _TAG_DIRECTION.get(node.type)
        if expected is None:
            continue
        tag = tags.get(node.config.tag_id)
        if tag is None:
            errors.append(
                f"nó '{node.id}' ({node.type}): a tag {node.config.tag_id} não existe ou não "
                "pertence ao projeto do flow"
            )
        elif tag.direction != expected:
            errors.append(
                f"nó '{node.id}' ({node.type}): a tag {tag.id} tem direção '{tag.direction}'; "
                f"este bloco exige direção '{expected}'"
            )


def _check_tfs_delay(nodes: list[FlowNode], ts_seconds: float, errors: list[str]) -> None:
    for node in nodes:
        if node.type != "tfs":
            continue
        for j, row in enumerate(node.config.matrix):
            for k, element in enumerate(row):
                if not element.enabled:
                    continue
                # Arredondamento banker's (half-even) do round() do Python: a mesma
                # convenção do bloco TFS em runtime (ottima_flow_runtime.blocks.tfs) e do
                # futuro modelo interno do MPC (F4b) — o mesmo theta precisa virar o mesmo
                # número de amostras nos dois códigos de propósito (spec F4 §3.1; fecha
                # débito m2 da spec F4 §8).
                samples = round(element.params.theta / ts_seconds)
                if samples > MAX_DELAY_SAMPLES:
                    errors.append(
                        f"nó '{node.id}' (tfs): o elemento y{j + 1}/u{k + 1} precisa de "
                        f"{samples} amostras de tempo morto (theta={element.params.theta} s, "
                        f"Ts={ts_seconds} s), acima do teto de {MAX_DELAY_SAMPLES}"
                    )


def _check_edge_endpoints(
    edges: list[FlowEdge], by_id: dict[str, FlowNode], errors: list[str]
) -> list[FlowEdge]:
    """Reporta extremidades inexistentes; devolve as arestas com topologia utilizável."""
    linked: list[FlowEdge] = []
    for edge in edges:
        ok = True
        for field, node_id in (("source", edge.source), ("target", edge.target)):
            if node_id not in by_id:
                errors.append(
                    f"aresta '{edge.id}': '{field}' referencia o nó inexistente '{node_id}'"
                )
                ok = False
        if ok:
            linked.append(edge)
    return linked


def _check_handles(
    edges: list[FlowEdge],
    by_id: dict[str, FlowNode],
    mpc_configs: dict[str, MpcConfig],
    errors: list[str],
) -> list[FlowEdge]:
    """Reporta handles inválidos; devolve as arestas com as duas portas resolvidas."""
    resolved: list[FlowEdge] = []
    for edge in edges:
        source, target = by_id[edge.source], by_id[edge.target]
        outputs, inputs = _output_handles(source, mpc_configs), _input_handles(target, mpc_configs)
        ok = True
        if edge.source_handle not in outputs:
            errors.append(
                f"aresta '{edge.id}': 'sourceHandle' '{edge.source_handle}' não é uma saída de "
                f"'{source.id}' ({source.type}); saídas: {_listing(outputs)}"
            )
            ok = False
        if edge.target_handle not in inputs:
            errors.append(
                f"aresta '{edge.id}': 'targetHandle' '{edge.target_handle}' não é uma entrada "
                f"de '{target.id}' ({target.type}); entradas: {_listing(inputs)}"
            )
            ok = False
        if ok:
            resolved.append(edge)
    return resolved


def _check_fan_in(edges: list[FlowEdge], errors: list[str]) -> None:
    """Spec §6.2: no máximo uma aresta por porta de entrada.

    Regra do servidor, não só do editor: duas fontes no mesmo handle deixariam o valor
    consumido pelo runtime indefinido.
    """
    by_port: dict[tuple[str, str], list[str]] = {}
    for edge in edges:
        by_port.setdefault((edge.target, edge.target_handle), []).append(edge.id)
    for (node_id, handle), edge_ids in by_port.items():
        if len(edge_ids) > 1:
            errors.append(
                f"a porta de entrada '{node_id}.{handle}' recebe {len(edge_ids)} arestas "
                f"({', '.join(edge_ids)}); no máximo uma é permitida"
            )


def _port_kind(node: FlowNode, tags: Mapping[int, TagRef]) -> PortKind | None:
    """Tipo da porta do bloco (decisão A-5).

    Serve os dois lados da aresta porque cada tipo tem um único sentido de porta: `opc_read`
    só aparece como origem, `opc_write` só como destino, e Script/TFS têm o mesmo tipo nas
    duas pontas. Devolve `None` quando a tag é desconhecida: a integridade referencial já
    reportou o problema e um erro de tipo em cima só faria ruído.
    """
    if node.type == "script":
        return "bivalent"
    if node.type in _TAG_DIRECTION:
        tag = tags.get(node.config.tag_id)
        if tag is None:
            return None
        return "bool" if tag.data_type == "bool" else "num"
    return "num"  # portas do TFS e do MPC (spec §2.1-5: todas numéricas)


def _check_port_types(
    edges: list[FlowEdge],
    by_id: dict[str, FlowNode],
    tags: Mapping[int, TagRef],
    errors: list[str],
) -> None:
    """Decisão A-5: Script bivalente dos dois lados, resto estrito."""
    for edge in edges:
        source, target = by_id[edge.source], by_id[edge.target]
        out_kind = _port_kind(source, tags)
        in_kind = _port_kind(target, tags)
        if out_kind is None or in_kind is None:
            continue
        if out_kind == "bivalent" or in_kind == "bivalent" or out_kind == in_kind:
            continue
        errors.append(
            f"aresta '{edge.id}': a saída '{source.id}.{edge.source_handle}' é "
            f"{_PORT_LABEL[out_kind]} e a entrada '{target.id}.{edge.target_handle}' é "
            f"{_PORT_LABEL[in_kind]}; só as portas do bloco Script são bivalentes "
            "(decisão A-5)"
        )


def _required_input_handles(node: FlowNode, mpc_configs: dict[str, MpcConfig]) -> tuple[str, ...]:
    if node.type == "tfs":
        # Spec §3.4: uK é obrigatória se e somente se a coluna K tem elemento habilitado.
        return tuple(
            f"u{k + 1}" for k in range(2) if any(row[k].enabled for row in node.config.matrix)
        )
    # 'in' do Write, IN1..INn do Script e uma por CV/Restrição/DV do MPC (decisão A-10) são
    # sempre obrigatórias (RF-302).
    return _input_handles(node, mpc_configs)


def _check_required_inputs(
    nodes: list[FlowNode],
    edges: list[FlowEdge],
    mpc_configs: dict[str, MpcConfig],
    errors: list[str],
) -> None:
    connected = {(edge.target, edge.target_handle) for edge in edges}
    for node in nodes:
        for handle in _required_input_handles(node, mpc_configs):
            if (node.id, handle) not in connected:
                errors.append(
                    f"nó '{node.id}' ({node.type}): a entrada '{handle}' é obrigatória e está "
                    "desconectada"
                )


def _check_cycles(nodes: list[FlowNode], edges: list[FlowEdge], errors: list[str]) -> None:
    """RF-302: o dígrafo source->target precisa ser acíclico.

    Travessia iterativa com pilha explícita, não recursão: o `graph_json` chega de um corpo
    de PUT, e um grafo encadeado com alguns milhares de nós estouraria o limite de recursão
    do Python — RecursionError vira 500, e nenhuma rota de flows pode devolver 5xx para
    entrada de usuário.
    """
    successors: dict[str, list[str]] = {node.id: [] for node in nodes}
    for edge in edges:
        successors[edge.source].append(edge.target)

    closed: set[str] = set()  # subárvore já fechada, não pode fechar ciclo
    on_path: set[str] = set()  # nós na pilha atual; reencontrar um deles é o ciclo

    for root in nodes:
        if root.id in closed:
            continue
        # `path` espelha a pilha: path[i] é o nó de stack[i], para reconstruir o caminho.
        stack: list[tuple[str, int]] = [(root.id, 0)]
        path: list[str] = [root.id]
        on_path.add(root.id)
        while stack:
            node_id, index = stack[-1]
            following = successors[node_id]
            if index == len(following):
                stack.pop()
                path.pop()
                on_path.discard(node_id)
                closed.add(node_id)
                continue
            stack[-1] = (node_id, index + 1)
            next_id = following[index]
            if next_id in on_path:
                cycle = path[path.index(next_id) :] + [next_id]
                errors.append(
                    f"ciclo detectado no grafo: {' -> '.join(cycle)}; "
                    "o fluxo de dados precisa ser acíclico (RF-302)"
                )
                return
            if next_id not in closed:
                stack.append((next_id, 0))
                path.append(next_id)
                on_path.add(next_id)


def _collect_inversion_warnings(
    edges: list[FlowEdge], by_id: dict[str, FlowNode], warnings: list[str]
) -> None:
    """RF-307/ADR-024: consumir antes de produzir é legal, mas atrasa uma varredura."""
    for edge in edges:
        source, target = by_id[edge.source], by_id[edge.target]
        if target.exec_order < source.exec_order:
            warnings.append(
                f"aresta '{edge.id}': o bloco '{target.id}' (exec_order {target.exec_order}) "
                f"consome a saída de '{source.id}' (exec_order {source.exec_order}); "
                "o valor usado será o da varredura anterior"
            )


# --------------------------------------------------------------------------------------
# Bloco `mpc` — validação semântica completa (spec F4 §2.2, tarefa 1.2 do plano F4a)
# --------------------------------------------------------------------------------------


def _parse_mpc_configs(nodes: list[FlowNode], errors: list[str]) -> dict[str, MpcConfig]:
    """Tipa o config bruto de cada nó `mpc` via `MpcConfig.model_validate` (spec §2.2-1).

    Só entra no dict devolvido quando a forma é válida: o resto das checagens do bloco
    (§2.2-2..8) precisa de campos tipados e não deve arriscar `KeyError`/`TypeError`/
    `ZeroDivisionError` num payload torto — por isso um nó `mpc` reprovado aqui sai do resto
    da validação com um único erro, sem cascata de ruído. Mesa pura: nunca `GraphParseError`,
    sempre pelo canal `ValidationResult.errors` (`parse_graph` nunca olha o conteúdo do `mpc`,
    só o resto da forma do grafo).
    """
    configs: dict[str, MpcConfig] = {}
    for node in nodes:
        if node.type != "mpc":
            continue
        try:
            configs[node.id] = MpcConfig.model_validate(node.config.model_dump())
        except ValidationError as erro:
            campos = ", ".join(
                ".".join(str(parte) for parte in item["loc"]) or "(raiz)" for item in erro.errors()
            )
            errors.append(
                f"nó '{node.id}' (mpc): config não confere com a spec F4 §2.1 (campos: {campos})"
            )
    return configs


def _check_mpc_caps(node: FlowNode, config: MpcConfig, errors: list[str]) -> None:
    """Spec §2.2-2: MVs 1..4 · CVs+Restrições 1..6 · DVs 0..4 (cobre "≥1 MV e ≥1 (CV ou
    Restrição)", RF-601, como piso das duas primeiras faixas)."""
    variables = config.variables
    checks = (
        (len(variables.mvs), _MPC_MV_RANGE, "MVs"),
        (
            len(variables.cvs) + len(variables.constraints),
            _MPC_CV_RESTRICAO_RANGE,
            "CVs somadas a Restrições",
        ),
        (len(variables.dvs), _MPC_DV_RANGE, "DVs"),
    )
    for count, (low, high), label in checks:
        if not low <= count <= high:
            errors.append(f"nó '{node.id}' (mpc): {count} {label}; teto do bloco é {low}..{high}")


def _valid_pair_params(kind: RowKind, params: dict[str, float]) -> bool:
    """Completude e validade dos `params` do par por `kind` da linha (spec §2.2-3):
    selfreg (SOPDT) exige K≠0, τ1>0, τ2≥0, θ≥0; integrating (IOPDT) exige Ki≠0, θ≥0."""
    expected = _SELFREG_PARAMS if kind == "selfreg" else _INTEGRATING_PARAMS
    if set(params) != expected:
        return False
    if kind == "selfreg":
        return (
            params["K"] != 0 and params["tau1"] > 0 and params["tau2"] >= 0 and params["theta"] >= 0
        )
    return params["Ki"] != 0 and params["theta"] >= 0


def _check_mpc_matrix(node: FlowNode, config: MpcConfig, errors: list[str]) -> bool:
    """Regras da matriz `models` (spec §2.2-3).

    Devolve `True` quando a matriz está íntegra o bastante para alimentar
    `mpc_state_dimension` sem `KeyError` (linhas conhecidas, pares habilitados com params
    completos e válidos pelo `kind` da linha) — pré-condição documentada no relatório da
    tarefa 1.1.
    """
    variables = config.variables
    row_kind: dict[str, RowKind] = {
        var.id: var.kind for var in (*variables.cvs, *variables.constraints)
    }
    mv_ids = {var.id for var in variables.mvs}
    dv_ids = {var.id for var in variables.dvs}
    mv_has_pair = dict.fromkeys(mv_ids, False)
    dv_has_pair = dict.fromkeys(dv_ids, False)

    intact = True
    for row_id, cols in config.models.items():
        if row_id not in row_kind:
            errors.append(
                f"nó '{node.id}' (mpc): a linha '{row_id}' de 'models' não corresponde a "
                "nenhuma CV ou Restrição do bloco"
            )
            intact = False
            continue
        kind = row_kind[row_id]
        row_has_mv_pair = False
        for col_id, pair in cols.items():
            if col_id not in mv_ids and col_id not in dv_ids:
                errors.append(
                    f"nó '{node.id}' (mpc): a coluna '{col_id}' da linha '{row_id}' não "
                    "corresponde a nenhuma MV ou DV do bloco"
                )
                intact = False
                continue
            if not pair.enabled:
                continue
            if col_id in mv_ids:
                row_has_mv_pair = True
                mv_has_pair[col_id] = True
            else:
                dv_has_pair[col_id] = True
            if not _valid_pair_params(kind, pair.params):
                errors.append(
                    f"nó '{node.id}' (mpc): o par '{row_id}'/'{col_id}' está habilitado com "
                    f"params inválidos ou incompletos para o kind '{kind}'"
                )
                intact = False
        if not row_has_mv_pair:
            errors.append(
                f"nó '{node.id}' (mpc): a linha '{row_id}' não tem nenhum par habilitado "
                "cuja coluna é MV"
            )

    for row_id in row_kind:
        if row_id not in config.models:
            errors.append(
                f"nó '{node.id}' (mpc): a linha '{row_id}' não tem nenhum par habilitado "
                "cuja coluna é MV"
            )

    for mv_id, has_pair in mv_has_pair.items():
        if not has_pair:
            errors.append(f"nó '{node.id}' (mpc): a MV '{mv_id}' não tem nenhum par habilitado")
    for dv_id, has_pair in dv_has_pair.items():
        if not has_pair:
            errors.append(f"nó '{node.id}' (mpc): a DV '{dv_id}' não tem nenhum par habilitado")

    return intact


def _check_mpc_numbers(node: FlowNode, config: MpcConfig, errors: list[str]) -> None:
    """Spec §2.2-4 (exceto `priority`/`multiplier`, já travados em `MpcConfig` — tarefa 1.1)."""
    variables = config.variables
    for mv_var in variables.mvs:
        if not mv_var.limits.min < mv_var.limits.max:
            errors.append(
                f"nó '{node.id}' (mpc): a MV '{mv_var.id}' precisa de limits.min < limits.max"
            )
        if not mv_var.du_max > 0:
            errors.append(f"nó '{node.id}' (mpc): a MV '{mv_var.id}' precisa de du_max > 0")
    for cv_var in variables.cvs:
        if not cv_var.tss > 0:
            errors.append(f"nó '{node.id}' (mpc): a CV '{cv_var.id}' precisa de tss > 0")
        if not cv_var.sp_limits.min < cv_var.sp_limits.max:
            errors.append(
                f"nó '{node.id}' (mpc): a CV '{cv_var.id}' precisa de sp_limits.min < sp_limits.max"
            )
        if not cv_var.weight > 0:
            errors.append(f"nó '{node.id}' (mpc): a CV '{cv_var.id}' precisa de weight > 0")
    for co_var in variables.constraints:
        if not co_var.tss > 0:
            errors.append(f"nó '{node.id}' (mpc): a Restrição '{co_var.id}' precisa de tss > 0")
        if not co_var.range.low < co_var.range.high:
            errors.append(
                f"nó '{node.id}' (mpc): a Restrição '{co_var.id}' precisa de range.low < range.high"
            )


def _check_pid_tag(
    node: FlowNode,
    mv_var: MvVar,
    field_name: str,
    tag_id: int,
    expected: Literal["r", "w"],
    tags: Mapping[int, TagRef],
    errors: list[str],
) -> None:
    tag = tags.get(tag_id)
    if tag is None:
        errors.append(
            f"nó '{node.id}' (mpc): a MV '{mv_var.id}' referencia em '{field_name}' a tag "
            f"{tag_id}, que não existe ou não pertence ao projeto do flow"
        )
        return
    if tag.direction != expected:
        errors.append(
            f"nó '{node.id}' (mpc): a MV '{mv_var.id}' referencia em '{field_name}' a tag "
            f"{tag_id} com direção '{tag.direction}'; este campo exige direção '{expected}'"
        )


def _check_mpc_pid_tags(
    node: FlowNode, config: MpcConfig, tags: Mapping[int, TagRef], errors: list[str]
) -> None:
    """Spec §2.2-6: tags do `pid` existem, direção correta, pertencem ao projeto do flow
    (mesma barreira da F3 §5.2). `pid` é opcional por MV (decisão A-8) — MV "direta" sem
    `pid` não tem nenhuma tag para checar."""
    for mv_var in config.variables.mvs:
        pid = mv_var.pid
        if pid is None:
            continue
        for field_name in _PID_WRITE_FIELDS:
            _check_pid_tag(node, mv_var, field_name, getattr(pid, field_name), "w", tags, errors)
        for field_name in _PID_READ_FIELDS:
            tag_id = getattr(pid, field_name)
            if tag_id is None:  # mode_read_tag_id é opcional (spec §2.1-3)
                continue
            _check_pid_tag(node, mv_var, field_name, tag_id, "r", tags, errors)


def _check_mpc_horizons(
    node: FlowNode,
    config: MpcConfig,
    ts_seconds: float,
    errors: list[str],
    warnings: list[str],
) -> float | None:
    """Spec §2.2-5/7: `Np<2` e `Np>120` são 422; `Np>60` é warning não-bloqueante.

    Devolve `Ts_mpc` quando o horizonte pôde ser derivado (≥1 CV/Restrição — sem isso `tss`
    fica vazio e `derive_horizons` levanta `ValueError`, a pré-condição documentada pela
    tarefa 1.1) para o chamador decidir se computa a dimensão de estados; `None` caso a
    contrário (o teto de §2.2-2 já reprovou 0 CVs+Restrições).
    """
    tss = [cv_var.tss for cv_var in config.variables.cvs] + [
        co_var.tss for co_var in config.variables.constraints
    ]
    if not tss:
        return None
    horizons = derive_horizons(config.multiplier, ts_seconds, tss)
    if horizons.np < 2:
        errors.append(f"nó '{node.id}' (mpc): multiplicador grande demais para o TSS")
    elif horizons.np > 120:
        errors.append(f"nó '{node.id}' (mpc): aumente o multiplicador ou reduza o TSS")
    elif horizons.np > 60:
        warnings.append(
            f"nó '{node.id}' (mpc): Np={horizons.np} acima de 60 (referência de carga RNF-02)"
        )
    return horizons.ts_mpc


def _check_mpc_nodes(
    nodes: list[FlowNode],
    mpc_configs: dict[str, MpcConfig],
    tags: Mapping[int, TagRef],
    ts_seconds: float,
    errors: list[str],
    warnings: list[str],
) -> None:
    for node in nodes:
        if node.type != "mpc":
            continue
        config = mpc_configs.get(node.id)
        if config is None:
            continue  # forma inválida já reportada por `_parse_mpc_configs`

        _check_mpc_caps(node, config, errors)
        matrix_intact = _check_mpc_matrix(node, config, errors)
        _check_mpc_numbers(node, config, errors)
        _check_mpc_pid_tags(node, config, tags, errors)
        ts_mpc = _check_mpc_horizons(node, config, ts_seconds, errors, warnings)

        if ts_mpc is not None and matrix_intact:
            dimension = mpc_state_dimension(config, ts_mpc)
            if dimension > 120:
                warnings.append(
                    f"nó '{node.id}' (mpc): dimensão de estados agregada ({dimension}) "
                    "acima de 120 (RF-608)"
                )
