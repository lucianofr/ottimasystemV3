"""Tradução de referências de tag do grafo de um flow, nos dois sentidos (spec F6 §2.2).

`TAG_REF_FIELDS` é o único lugar onde a lista de campos com referência de tag vive; a
tradução `*_tag_id` (forma banco) <-> `*_tag_ref` (forma bundle) é explícita por campo —
nunca varredura heurística por sufixo em tempo de execução. Nenhuma função aqui chama
`parse_graph`: o grafo do bundle é uma forma distinta do `graph_json` (não um superset),
tratada como dict aninhado puro.
"""

from __future__ import annotations

from collections.abc import Container, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

_TIPOS_COM_TAG_ID = frozenset({"opc_read", "opc_write"})
"""§2.2-1: `data.tag_id` só existe nestes dois tipos de nó."""


@dataclass(frozen=True, slots=True)
class CampoTagRef:
    """Um campo com referência de tag: `id_key` (forma banco) <-> `ref_key` (forma bundle)."""

    id_key: str
    ref_key: str
    obrigatorio: bool


CAMPOS_NO_DATA: tuple[CampoTagRef, ...] = (CampoTagRef("tag_id", "tag_ref", True),)
"""`nodes[].data.tag_id` — vale para `opc_read` e `opc_write` (dois lugares, um nome)."""

CAMPOS_NO_PID: tuple[CampoTagRef, ...] = (
    CampoTagRef("write_tag_id", "write_tag_ref", True),
    CampoTagRef("mode_cmd_tag_id", "mode_cmd_tag_ref", True),
    CampoTagRef("mode_read_tag_id", "mode_read_tag_ref", False),
    CampoTagRef("readback_tag_id", "readback_tag_ref", True),
)
"""`nodes[].data.variables.mvs[].pid.*` — amarração de tags do PID de uma MV."""

TAG_REF_FIELDS: tuple[CampoTagRef, ...] = CAMPOS_NO_DATA + CAMPOS_NO_PID
"""Os 5 nomes que cobrem os 6 lugares de §2.2-1 (`tag_id` serve `opc_read` e `opc_write`)."""


class ReferenciaTagInvalida(ValueError):
    """Uma ou mais referências de tag não resolveram (spec §2.2-3); `problemas` agrega todas,
    nunca só a primeira."""

    def __init__(self, problemas: list[str]) -> None:
        self.problemas = problemas
        super().__init__(" | ".join(problemas))


def _mvs_do_no(data: dict) -> list[Any]:
    variables = data.get("variables")
    if not isinstance(variables, dict):
        return []
    mvs = variables.get("mvs")
    return mvs if isinstance(mvs, list) else []


def _extrair_ref(valor: object) -> tuple[str, str] | None:
    if not isinstance(valor, dict):
        return None
    connection = valor.get("connection")
    tag = valor.get("tag")
    if not isinstance(connection, str) or not isinstance(tag, str):
        return None
    return (connection, tag)


def _para_cada_container(
    node: dict,
) -> list[tuple[dict, tuple[CampoTagRef, ...], str]]:
    """Os containers de campo com referência de tag de um nó: `(dict, campos, caminho)`."""
    data = node.get("data")
    if not isinstance(data, dict):
        return []
    containers: list[tuple[dict, tuple[CampoTagRef, ...], str]] = []
    if node.get("type") in _TIPOS_COM_TAG_ID:
        containers.append((data, CAMPOS_NO_DATA, "data"))
    for i, mv in enumerate(_mvs_do_no(data)):
        if not isinstance(mv, dict):
            continue
        pid = mv.get("pid")
        if isinstance(pid, dict):
            containers.append((pid, CAMPOS_NO_PID, f"data.variables.mvs[{i}].pid"))
    return containers


def grafo_para_bundle(graph: dict, ref_por_id: Mapping[int, tuple[str, str]]) -> dict:
    """Troca cada `*_tag_id` do grafo pelo `*_tag_ref` `{"connection", "tag"}` correspondente.

    Levanta `ReferenciaTagInvalida` com a lista completa de problemas (agregada, não no
    primeiro erro) quando algum id não resolve em `ref_por_id`.
    """
    resultado = deepcopy(graph)
    problemas: list[str] = []
    for node in resultado.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id", "?")
        for container, campos, caminho in _para_cada_container(node):
            for campo in campos:
                if campo.id_key not in container:
                    if campo.obrigatorio:
                        problemas.append(
                            f"nó '{node_id}': '{caminho}.{campo.id_key}' é obrigatório e "
                            "está ausente"
                        )
                    continue
                tag_id = container.pop(campo.id_key)
                ref = ref_por_id.get(tag_id)
                if ref is None:
                    problemas.append(
                        f"nó '{node_id}': '{caminho}.{campo.id_key}' = {tag_id!r} não tem "
                        "referência de tag conhecida"
                    )
                    continue
                connection, tag = ref
                container[campo.ref_key] = {"connection": connection, "tag": tag}
    if problemas:
        raise ReferenciaTagInvalida(problemas)
    return resultado


def grafo_para_banco(graph: dict, id_por_ref: Mapping[tuple[str, str], int]) -> dict:
    """Troca cada `*_tag_ref` do grafo pelo `*_tag_id` inteiro correspondente — inverso de
    `grafo_para_bundle`. Levanta `ReferenciaTagInvalida` agregada quando alguma referência
    não resolve em `id_por_ref`; ausência de campo obrigatório nunca vira `KeyError`, só
    mais um item da lista de problemas.
    """
    resultado = deepcopy(graph)
    problemas: list[str] = []
    for node in resultado.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id", "?")
        for container, campos, caminho in _para_cada_container(node):
            for campo in campos:
                if campo.ref_key not in container:
                    if campo.obrigatorio:
                        problemas.append(
                            f"nó '{node_id}': '{caminho}.{campo.ref_key}' é obrigatório e "
                            "está ausente"
                        )
                    continue
                ref_bruto = container.pop(campo.ref_key)
                ref = _extrair_ref(ref_bruto)
                tag_id = id_por_ref.get(ref) if ref is not None else None
                if tag_id is None:
                    problemas.append(
                        f"nó '{node_id}': '{caminho}.{campo.ref_key}' = {ref_bruto!r} não "
                        "tem referência de tag conhecida"
                    )
                    continue
                container[campo.id_key] = tag_id
    if problemas:
        raise ReferenciaTagInvalida(problemas)
    return resultado


def problemas_de_tag_ref(graph: dict, *, onde: str, refs: Container[tuple[str, str]]) -> list[str]:
    """Confere, sem traduzir, que toda `*_tag_ref` do grafo aponta para uma referência
    declarada em `refs` (camada 3 do import, §2.2-5). Ausência de campo opcional é válida;
    campo obrigatório ausente ou referência mal formada/desconhecida viram itens da lista —
    nunca uma exceção.
    """
    problemas: list[str] = []
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return [f"{onde}: 'nodes' deve ser uma lista"]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id", "?")
        for container, campos, caminho in _para_cada_container(node):
            for campo in campos:
                if campo.ref_key not in container:
                    if campo.obrigatorio:
                        problemas.append(
                            f"{onde}: nó '{node_id}': '{caminho}.{campo.ref_key}' é "
                            "obrigatório e está ausente"
                        )
                    continue
                ref = _extrair_ref(container[campo.ref_key])
                if ref is None:
                    problemas.append(
                        f"{onde}: nó '{node_id}': '{caminho}.{campo.ref_key}' deve ser um "
                        "objeto {'connection', 'tag'}"
                    )
                elif ref not in refs:
                    problemas.append(
                        f"{onde}: nó '{node_id}': '{caminho}.{campo.ref_key}' referencia "
                        f"tag desconhecida {ref[0]!r}/{ref[1]!r}"
                    )
    return problemas
