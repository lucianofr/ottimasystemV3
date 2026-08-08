"""Montagem do arquivo de projeto (bundle) e coerência interna do import (spec F6
§2.1-7, §3.2-4 camada 3). Puro: nenhuma função aqui toca banco, Redis ou disco — os
models chegam já carregados e o resultado é só devolvido para quem grava o arquivo
ou faz o insert.

`Connection` na assinatura das funções abaixo é `ottima_core.models.OpcConnection`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from ottima_core.models import Flow, OpcConnection, Project, Tag
from ottima_core.portability.schemas import (
    SCHEMA_VERSION,
    BundleConnection,
    BundleFlow,
    BundleProject,
    BundleTag,
    ProjectBundle,
)
from ottima_core.portability.tag_ref import grafo_para_bundle, problemas_de_tag_ref


def ref_por_id(
    connections: Sequence[OpcConnection], tags: Sequence[Tag]
) -> dict[int, tuple[str, str]]:
    """Monta `{tag.id: (connection.name, tag.name)}` a partir dos models carregados —
    a tabela que `grafo_para_bundle` usa para traduzir `*_tag_id` em `*_tag_ref`."""
    nome_da_conexao = {connection.id: connection.name for connection in connections}
    return {tag.id: (nome_da_conexao[tag.connection_id], tag.name) for tag in tags}


def montar_bundle(
    *,
    project: Project,
    connections: Sequence[OpcConnection],
    tags: Sequence[Tag],
    flows: Sequence[Flow],
    exported_at: datetime,
) -> ProjectBundle:
    """Projeta o estado vivo de um projeto no arquivo de portabilidade (spec §2.1-7).

    Ordem estável — conexões e flows por `name`, tags por `(connection, name)` — para
    que um arquivo que circula entre plantas nunca produza diff espúrio entre duas
    execuções do mesmo export.
    """
    refs = ref_por_id(connections, tags)
    nome_da_conexao = {connection.id: connection.name for connection in connections}

    conexoes_ordenadas = sorted(connections, key=lambda c: c.name)
    tags_ordenadas = sorted(tags, key=lambda t: (nome_da_conexao[t.connection_id], t.name))
    flows_ordenados = sorted(flows, key=lambda f: f.name)

    return ProjectBundle(
        schema_version=SCHEMA_VERSION,
        exported_at=exported_at,
        project=BundleProject(name=project.name, description=project.description),
        connections=[
            BundleConnection(
                name=c.name,
                endpoint=c.endpoint,
                security_policy=c.security_policy,
                security_mode=c.security_mode,
                auth_mode=c.auth_mode,
                auth_username=c.auth_username,
                watchdog_read_node_id=c.watchdog_read_node_id,
                watchdog_write_node_id=c.watchdog_write_node_id,
                watchdog_period_ms=c.watchdog_period_ms,
            )
            for c in conexoes_ordenadas
        ],
        tags=[
            BundleTag(
                connection=nome_da_conexao[t.connection_id],
                name=t.name,
                node_id=t.node_id,
                direction=t.direction,
                data_type=t.data_type,
                eu=t.eu,
                description=t.description,
            )
            for t in tags_ordenadas
        ],
        flows=[
            BundleFlow(
                name=f.name,
                ts_seconds=float(f.ts_seconds),
                desired_state=f.desired_state,
                graph=grafo_para_bundle(f.graph_json, refs),
            )
            for f in flows_ordenados
        ],
    )


def problemas_de_coerencia_interna(bundle: ProjectBundle) -> list[str]:
    """Camada 3 do import (spec §3.2-4): valida a coerência interna de um bundle já
    validado pela forma (camadas 1/2), em memória, antes de qualquer insert. Nunca
    levanta exceção — um item de lista por problema, para o 422 agregado do import.
    """
    problemas: list[str] = []

    for nome, contagem in Counter(c.name for c in bundle.connections).items():
        if contagem > 1:
            problemas.append(f"conexão '{nome}' duplicada no bundle")

    for nome, contagem in Counter(f.name for f in bundle.flows).items():
        if contagem > 1:
            problemas.append(f"flow '{nome}' duplicado no bundle")

    # Contar por (connection, name): mesmo nome em conexões diferentes é legítimo —
    # `Tag.name` é único por conexão (`uq_tags_connection_name`), não por projeto.
    for (conexao, nome), contagem in Counter((t.connection, t.name) for t in bundle.tags).items():
        if contagem > 1:
            problemas.append(f"tag '{nome}' duplicada na conexão '{conexao}'")

    nomes_conexao = {c.name for c in bundle.connections}
    for tag in bundle.tags:
        if tag.connection not in nomes_conexao:
            problemas.append(
                f"tag '{tag.name}' referencia conexão '{tag.connection}' que não existe no bundle"
            )

    refs_validas = {(tag.connection, tag.name) for tag in bundle.tags}
    for flow in bundle.flows:
        problemas.extend(
            problemas_de_tag_ref(flow.graph, onde=f"fluxo '{flow.name}'", refs=refs_validas)
        )

    return problemas
