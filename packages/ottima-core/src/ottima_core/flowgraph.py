"""Modelo tipado do `graph_json` de um flow + validação compartilhada (RF-302/307, ADR-024).

Uma implementação, dois consumidores (spec F3 §2.1): a API valida no save (422) e o runtime
valida ao montar a definição *staged* do hot-swap. Núcleo puro — nada de SQLAlchemy nem de
`services/` aqui: o chamador traduz linhas do banco em `TagRef`.

Divisão de responsabilidade:

- `parse_graph` cuida da **forma** (estrutura e tipagem estática do JSONB) e levanta
  `GraphParseError` com a lista completa de problemas;
- `validate_graph` cuida da **semântica que precisa de contexto** (tags do projeto, Ts do
  flow, topologia) e nunca levanta por conteúdo de grafo — devolve `ValidationResult`.
"""

import math
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NodeType = Literal["opc_read", "opc_write", "script", "tfs"]
NODE_TYPES: tuple[str, ...] = ("opc_read", "opc_write", "script", "tfs")

MAX_SCRIPT_PORTS = 8  # spec §3.3
MAX_DELAY_SAMPLES = 7200  # teto da fila de tempo morto do TFS (spec §3.4)

# "bivalent" é a porta do bloco Script, que aceita numérico e booleano (decisão A-5).
PortKind = Literal["num", "bool", "bivalent"]
_PORT_LABEL: dict[str, str] = {"num": "numérica", "bool": "booleana", "bivalent": "bivalente"}

_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "opc_read": ("tag_id",),
    "opc_write": ("tag_id",),
    "script": ("n_inputs", "n_outputs", "code"),
    "tfs": ("matrix",),
}
_PARAM_KEYS: dict[str, tuple[str, ...]] = {
    "sopdt": ("K", "tau1", "tau2", "theta"),
    "iopdt": ("Ki", "theta"),
}
_GAIN_KEYS = frozenset({"K", "Ki"})  # únicos params que podem ser negativos
_TAG_DIRECTION: dict[str, str] = {"opc_read": "r", "opc_write": "w"}


# --------------------------------------------------------------------------------------
# Modelo
# --------------------------------------------------------------------------------------


class TagRef(BaseModel):
    """O que a validação precisa saber de uma tag; o chamador projeta a linha do banco."""

    id: int
    conn_id: int
    direction: Literal["r", "w"]
    data_type: Literal["float", "int", "bool"]


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class TagConfig(BaseModel):
    """Config de `opc_read` e `opc_write` — idêntica; quem discrimina é `FlowNode.type`."""

    model_config = ConfigDict(extra="forbid")

    tag_id: int


class ScriptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_inputs: int = Field(ge=0, le=MAX_SCRIPT_PORTS)
    n_outputs: int = Field(ge=0, le=MAX_SCRIPT_PORTS)
    code: str


class SopdtParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    K: float
    tau1: float = Field(ge=0)
    tau2: float = Field(ge=0)
    theta: float = Field(ge=0)


class IopdtParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    Ki: float
    theta: float = Field(ge=0)


class TfsElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    kind: Literal["sopdt", "iopdt"]
    params: SopdtParams | IopdtParams


class TfsConfig(BaseModel):
    """`matrix[J][K]` é a contribuição de `uK` para `yJ` (spec §3.4), sempre 2x2."""

    model_config = ConfigDict(extra="forbid")

    matrix: list[list[TfsElement]]


NodeConfig = TagConfig | ScriptConfig | TfsConfig


class FlowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: NodeType
    position: Position
    exec_order: int = Field(ge=1)
    label: str = ""
    config: NodeConfig

    def functional_config(self) -> dict[str, Any]:
        """Identidade funcional do bloco, para o hot-swap (ADR-024, spec §4.1-3).

        `exec_order`, `label` e `position` ficam de fora de propósito: mudá-los não altera o
        que o bloco calcula, então o estado interno sobrevive ao swap (ADR-011).
        """
        return {"type": self.type, **self.config.model_dump()}


class FlowEdge(BaseModel):
    # As chaves do JSON são as do React Flow (camelCase); do lado Python valem os nomes
    # snake_case do projeto.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    source: str
    target: str
    source_handle: str = Field(alias="sourceHandle")
    target_handle: str = Field(alias="targetHandle")


class FlowGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[FlowNode]
    edges: list[FlowEdge]

    def node(self, node_id: str) -> FlowNode:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)


class GraphParseError(ValueError):
    """Problemas estruturais do `graph_json`. `errors` traz todos, não só o primeiro."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class ValidationResult(BaseModel):
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# parse_graph
# --------------------------------------------------------------------------------------


def _is_int(value: object) -> bool:
    # bool é subclasse de int em Python: True não é um exec_order nem um tag_id.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def parse_graph(data: dict) -> FlowGraph:
    """Valida a forma do `graph_json` e devolve o modelo tipado.

    Levanta `GraphParseError` com **todos** os problemas estruturais encontrados, para que o
    usuário corrija de uma vez em lugar de descobrir um por save.
    """
    if not isinstance(data, dict):
        raise GraphParseError(["graph_json deve ser um objeto com 'nodes' e 'edges'"])

    errors: list[str] = []
    raw_nodes = data.get("nodes")
    raw_edges = data.get("edges")
    if not isinstance(raw_nodes, list):
        errors.append("graph_json: 'nodes' é obrigatório e deve ser uma lista")
    if not isinstance(raw_edges, list):
        errors.append("graph_json: 'edges' é obrigatório e deve ser uma lista")
    if errors:
        raise GraphParseError(errors)

    nodes = _parse_nodes(raw_nodes, errors)
    edges = _parse_edges(raw_edges, errors)
    if errors:
        raise GraphParseError(errors)
    return FlowGraph(nodes=nodes, edges=edges)


def _parse_nodes(raw_nodes: list, errors: list[str]) -> list[FlowNode]:
    nodes: list[FlowNode] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            errors.append(f"nó na posição {index}: deve ser um objeto")
            continue
        node_id = raw.get("id")
        if not isinstance(node_id, str) or not node_id:
            errors.append(f"nó na posição {index}: 'id' deve ser uma string não-vazia")
            continue
        if node_id in seen:
            errors.append(f"id de nó duplicado: '{node_id}'")
            continue
        seen.add(node_id)
        node = _parse_node(node_id, raw, errors)
        if node is not None:
            nodes.append(node)
    return nodes


def _parse_node(node_id: str, raw: dict, errors: list[str]) -> FlowNode | None:
    where = f"nó '{node_id}'"
    node_type = raw.get("type")
    if node_type == "mpc":
        errors.append(
            f"{where}: o bloco MPC só entra em operação na F4 (decisão A-1); "
            "remova-o do grafo antes de salvar"
        )
        return None
    if node_type not in NODE_TYPES:
        errors.append(
            f"{where}: tipo '{node_type}' não é um bloco válido; use um de: {', '.join(NODE_TYPES)}"
        )
        return None

    position = _parse_position(where, raw.get("position"), errors)

    data = raw.get("data")
    if not isinstance(data, dict):
        errors.append(f"{where}: 'data' é obrigatório e deve ser um objeto")
        return None

    exec_order = data.get("exec_order")
    if not _is_int(exec_order) or exec_order < 1:
        errors.append(f"{where}: 'exec_order' é obrigatório e deve ser um inteiro maior que 0")
        exec_order = None

    label = data.get("label", "")
    if not isinstance(label, str):
        errors.append(f"{where}: 'label' deve ser uma string")
        label = ""

    # O editor é a única fonte deste JSON: chave extra em 'data' é bug de versão do frontend,
    # não campo opcional. Aceitar em silêncio esconderia o bug até o runtime tropeçar nele.
    allowed = {"exec_order", "label", *_CONFIG_KEYS[node_type]}
    for key in sorted(set(data) - allowed):
        errors.append(f"{where}: chave desconhecida em 'data': '{key}'")

    config = _parse_config(where, node_type, data, errors)
    if config is None or position is None or exec_order is None:
        return None
    return FlowNode(
        id=node_id,
        type=node_type,
        position=position,
        exec_order=exec_order,
        label=label,
        config=config,
    )


def _parse_position(where: str, raw: object, errors: list[str]) -> Position | None:
    if not isinstance(raw, dict) or not all(_is_number(raw.get(axis)) for axis in ("x", "y")):
        errors.append(f"{where}: 'position' deve ser um objeto com 'x' e 'y' numéricos")
        return None
    return Position(x=float(raw["x"]), y=float(raw["y"]))


def _parse_config(where: str, node_type: str, data: dict, errors: list[str]) -> NodeConfig | None:
    if node_type in _TAG_DIRECTION:
        tag_id = data.get("tag_id")
        if not _is_int(tag_id) or tag_id < 1:
            errors.append(f"{where}: 'tag_id' é obrigatório e deve ser um inteiro positivo")
            return None
        return TagConfig(tag_id=tag_id)
    if node_type == "script":
        return _parse_script_config(where, data, errors)
    return _parse_tfs_config(where, data, errors)


def _parse_script_config(where: str, data: dict, errors: list[str]) -> ScriptConfig | None:
    counts: dict[str, int] = {}
    for field in ("n_inputs", "n_outputs"):
        value = data.get(field)
        if not _is_int(value) or not 0 <= value <= MAX_SCRIPT_PORTS:
            errors.append(
                f"{where}: '{field}' é obrigatório e deve ser um inteiro entre 0 e "
                f"{MAX_SCRIPT_PORTS}"
            )
        else:
            counts[field] = value

    code = data.get("code")
    if not isinstance(code, str):
        errors.append(f"{where}: 'code' é obrigatório e deve ser uma string")
        return None
    if len(counts) != 2:
        return None
    return ScriptConfig(n_inputs=counts["n_inputs"], n_outputs=counts["n_outputs"], code=code)


def _parse_tfs_config(where: str, data: dict, errors: list[str]) -> TfsConfig | None:
    matrix = data.get("matrix")
    if (
        not isinstance(matrix, list)
        or len(matrix) != 2
        or any(not isinstance(row, list) or len(row) != 2 for row in matrix)
    ):
        errors.append(
            f"{where}: 'matrix' é obrigatória e deve ser 2x2 (linhas y1..y2 por colunas u1..u2)"
        )
        return None

    rows: list[list[TfsElement]] = []
    complete = True
    for j, row in enumerate(matrix):
        parsed: list[TfsElement] = []
        for k, raw in enumerate(row):
            element = _parse_tfs_element(f"{where}: elemento y{j + 1}/u{k + 1}", raw, errors)
            if element is None:
                complete = False
            else:
                parsed.append(element)
        rows.append(parsed)
    if not complete:
        return None
    return TfsConfig(matrix=rows)


def _parse_tfs_element(where: str, raw: object, errors: list[str]) -> TfsElement | None:
    if not isinstance(raw, dict):
        errors.append(f"{where}: deve ser um objeto com 'enabled', 'kind' e 'params'")
        return None
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        errors.append(f"{where}: 'enabled' é obrigatório e deve ser booleano")
        return None
    kind = raw.get("kind")
    if kind not in _PARAM_KEYS:
        errors.append(f"{where}: 'kind' deve ser 'sopdt' ou 'iopdt'")
        return None
    params = raw.get("params")
    if not isinstance(params, dict):
        errors.append(f"{where}: 'params' é obrigatório e deve ser um objeto")
        return None

    expected = _PARAM_KEYS[kind]
    values: dict[str, float] = {}
    for extra in sorted(set(params) - set(expected)):
        errors.append(f"{where}: '{extra}' não é um parâmetro de '{kind}'")
    for key in expected:
        value = params.get(key)
        # Exigir finitude também em theta: ele entra em round(theta/Ts) na regra de teto,
        # onde inf/nan estouraria com OverflowError/ValueError em vez de virar um 422.
        if not _is_number(value) or not math.isfinite(value):
            errors.append(f"{where}: '{key}' é obrigatório e deve ser um número finito")
        elif key not in _GAIN_KEYS and value < 0:
            # tau = 0 é legal (spec §3.4 degrada para passagem direta); negativo é não-físico.
            errors.append(f"{where}: '{key}' não pode ser negativo")
        else:
            values[key] = float(value)

    if len(values) != len(expected) or len(params) != len(expected):
        return None
    built = SopdtParams(**values) if kind == "sopdt" else IopdtParams(**values)
    return TfsElement(enabled=enabled, kind=kind, params=built)


def _parse_edges(raw_edges: list, errors: list[str]) -> list[FlowEdge]:
    edges: list[FlowEdge] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_edges):
        if not isinstance(raw, dict):
            errors.append(f"aresta na posição {index}: deve ser um objeto")
            continue
        edge_id = raw.get("id")
        if not isinstance(edge_id, str) or not edge_id:
            errors.append(f"aresta na posição {index}: 'id' deve ser uma string não-vazia")
            continue
        if edge_id in seen:
            errors.append(f"id de aresta duplicado: '{edge_id}'")
            continue
        seen.add(edge_id)

        fields: dict[str, str] = {}
        for key in ("source", "target", "sourceHandle", "targetHandle"):
            value = raw.get(key)
            if not isinstance(value, str) or not value:
                errors.append(f"aresta '{edge_id}': '{key}' deve ser uma string não-vazia")
            else:
                fields[key] = value
        if len(fields) == 4:
            edges.append(
                FlowEdge(
                    id=edge_id,
                    source=fields["source"],
                    target=fields["target"],
                    source_handle=fields["sourceHandle"],
                    target_handle=fields["targetHandle"],
                )
            )
    return edges


# --------------------------------------------------------------------------------------
# validate_graph
# --------------------------------------------------------------------------------------


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

    _check_exec_order(graph.nodes, errors)
    _check_tags(graph.nodes, tags, errors)
    _check_tfs_delay(graph.nodes, ts_seconds, errors)

    linked = _check_edge_endpoints(graph.edges, by_id, errors)
    resolved = _check_handles(linked, by_id, errors)
    _check_fan_in(resolved, errors)
    _check_port_types(resolved, by_id, tags, errors)
    _check_required_inputs(graph.nodes, resolved, errors)
    _check_cycles(graph.nodes, linked, errors)
    _collect_inversion_warnings(linked, by_id, warnings)

    return ValidationResult(errors=errors, warnings=warnings)


def _output_handles(node: FlowNode) -> tuple[str, ...]:
    if node.type == "opc_read":
        return ("out",)
    if node.type == "script":
        return tuple(f"OUT{i}" for i in range(1, node.config.n_outputs + 1))
    if node.type == "tfs":
        return ("y1", "y2")
    return ()


def _input_handles(node: FlowNode) -> tuple[str, ...]:
    if node.type == "opc_write":
        return ("in",)
    if node.type == "script":
        return tuple(f"IN{i}" for i in range(1, node.config.n_inputs + 1))
    if node.type == "tfs":
        return ("u1", "u2")
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
    edges: list[FlowEdge], by_id: dict[str, FlowNode], errors: list[str]
) -> list[FlowEdge]:
    """Reporta handles inválidos; devolve as arestas com as duas portas resolvidas."""
    resolved: list[FlowEdge] = []
    for edge in edges:
        source, target = by_id[edge.source], by_id[edge.target]
        outputs, inputs = _output_handles(source), _input_handles(target)
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
    return "num"  # portas do TFS


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


def _required_input_handles(node: FlowNode) -> tuple[str, ...]:
    if node.type == "tfs":
        # Spec §3.4: uK é obrigatória se e somente se a coluna K tem elemento habilitado.
        return tuple(
            f"u{k + 1}" for k in range(2) if any(row[k].enabled for row in node.config.matrix)
        )
    # 'in' do Write e IN1..INn do Script são sempre obrigatórias (RF-302).
    return _input_handles(node)


def _check_required_inputs(nodes: list[FlowNode], edges: list[FlowEdge], errors: list[str]) -> None:
    connected = {(edge.target, edge.target_handle) for edge in edges}
    for node in nodes:
        for handle in _required_input_handles(node):
            if (node.id, handle) not in connected:
                errors.append(
                    f"nó '{node.id}' ({node.type}): a entrada '{handle}' é obrigatória e está "
                    "desconectada"
                )


def _check_cycles(nodes: list[FlowNode], edges: list[FlowEdge], errors: list[str]) -> None:
    """RF-302: o dígrafo source->target precisa ser acíclico."""
    successors: dict[str, list[str]] = {node.id: [] for node in nodes}
    for edge in edges:
        successors[edge.source].append(edge.target)

    open_nodes: set[str] = set()  # na pilha da busca atual
    closed: set[str] = set()
    path: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        open_nodes.add(node_id)
        path.append(node_id)
        for following in successors[node_id]:
            if following in open_nodes:
                return path[path.index(following) :] + [following]
            if following not in closed:
                cycle = visit(following)
                if cycle is not None:
                    return cycle
        path.pop()
        open_nodes.discard(node_id)
        closed.add(node_id)
        return None

    for node in nodes:
        if node.id in closed:
            continue
        cycle = visit(node.id)
        if cycle is not None:
            errors.append(
                f"ciclo detectado no grafo: {' -> '.join(cycle)}; "
                "o fluxo de dados precisa ser acíclico (RF-302)"
            )
            return


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
