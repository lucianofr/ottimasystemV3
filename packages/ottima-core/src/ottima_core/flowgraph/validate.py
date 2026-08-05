"""Validação semântica do `graph_json` — tags do projeto, Ts do flow e topologia (RF-302/307).

Núcleo puro — nada de SQLAlchemy nem de `services/` aqui: o chamador traduz linhas do banco em
`TagRef`. `validate_graph` nunca levanta por conteúdo de grafo: devolve `ValidationResult`. Ver
`ottima_core/flowgraph/__init__.py` para a divisão de responsabilidade completa do pacote.
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field

from ottima_core.flowgraph.parse import _TAG_DIRECTION, FlowEdge, FlowGraph, FlowNode

MAX_DELAY_SAMPLES = 7200  # teto da fila de tempo morto do TFS (spec §3.4)

# "bivalent" é a porta do bloco Script, que aceita numérico e booleano (decisão A-5).
PortKind = Literal["num", "bool", "bivalent"]
_PORT_LABEL: dict[str, str] = {"num": "numérica", "bool": "booleana", "bivalent": "bivalente"}


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
