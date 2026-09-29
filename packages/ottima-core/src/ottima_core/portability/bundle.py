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

from ottima_core.calc_script import problemas_do_script
from ottima_core.models import (
    CalculatedTag,
    CalculatedTagInput,
    Flow,
    HistorizedVar,
    OpcConnection,
    Project,
    Tag,
)
from ottima_core.portability.schemas import (
    SCHEMA_VERSION,
    BundleCalcInputRef,
    BundleConnection,
    BundleFlow,
    BundleHistorizedVar,
    BundleProject,
    BundleTag,
    ProjectBundle,
)
from ottima_core.portability.tag_ref import grafo_para_bundle, problemas_de_tag_ref
from ottima_core.schemas.calculated_tags import MAX_CALC_INPUTS


def ref_por_id(
    connections: Sequence[OpcConnection], tags: Sequence[Tag]
) -> dict[int, tuple[str | None, str]]:
    """Monta `{tag.id: (connection.name, tag.name)}` a partir dos models carregados — a
    tabela que `grafo_para_bundle` (e a montagem de `input_tags` de tag calculada, abaixo)
    usam para traduzir um id em referência portável. Tag calculada não pertence a conexão
    nenhuma: o primeiro elemento da tupla é `None` (mesma convenção de `BundleTag.connection`
    e `BundleCalcInputRef.connection`)."""
    nome_da_conexao = {connection.id: connection.name for connection in connections}
    return {
        tag.id: (
            nome_da_conexao[tag.connection_id] if tag.connection_id is not None else None,
            tag.name,
        )
        for tag in tags
    }


def montar_bundle(
    *,
    project: Project,
    connections: Sequence[OpcConnection],
    tags: Sequence[Tag],
    flows: Sequence[Flow],
    exported_at: datetime,
    calculated_tags: Sequence[CalculatedTag] = (),
    calculated_tag_inputs: Sequence[CalculatedTagInput] = (),
    historized_vars: Sequence[HistorizedVar] = (),
) -> ProjectBundle:
    """Projeta o estado vivo de um projeto no arquivo de portabilidade (spec §2.1-7).

    `tags` traz as três naturezas de `Tag` do projeto (OPC, com `connection_id`; calculada
    e historiada, ambas com `connection_id IS NULL` — `ck_tags_owner`); `calculated_tags`/
    `calculated_tag_inputs` só existem para a segunda (RF-208, ADR-033) e `historized_vars`
    só para a terceira (RF-308, ADR-041 D1). A linha de `tags` de uma variável historiada é
    filtrada AQUI, antes de qualquer coisa — nunca vai para `ProjectBundle.tags` (cairia
    fora do XOR de `BundleTag._coerencia`, que só conhece OPC e calculada) — mesmo que o
    chamador esqueça de excluí-la da consulta; ela é reconstruída só a partir do próprio
    `BundleHistorizedVar` (`tag`, `eu`) no import. Ordem estável — conexões e flows por
    `name`; tags OPC antes das calculadas (a fronteira que o próprio banco já impõe), OPC
    por `(connection, name)` como antes, calculadas por `name`, historiadas por
    `(flow, block_id, port)` — para que um arquivo que circula entre plantas nunca produza
    diff espúrio entre duas execuções do mesmo export.
    """
    refs = ref_por_id(connections, tags)
    nome_da_conexao = {connection.id: connection.name for connection in connections}
    nome_do_flow = {f.id: f.name for f in flows}
    spec_por_tag_id = {ct.tag_id: ct for ct in calculated_tags}
    tag_por_id = {t.id: t for t in tags}

    tags_historiadas_por_id = {hv.tag_id: hv for hv in historized_vars}
    tags = [t for t in tags if t.id not in tags_historiadas_por_id]

    entradas_por_calculada: dict[int, list[int]] = {}
    for entrada in sorted(calculated_tag_inputs, key=lambda e: (e.calc_tag_id, e.position)):
        entradas_por_calculada.setdefault(entrada.calc_tag_id, []).append(entrada.source_tag_id)

    conexoes_ordenadas = sorted(connections, key=lambda c: c.name)
    tags_ordenadas = sorted(
        tags,
        key=lambda t: (
            (1, "", t.name)
            if t.connection_id is None
            else (0, nome_da_conexao[t.connection_id], t.name)
        ),
    )
    flows_ordenados = sorted(flows, key=lambda f: f.name)
    historizadas_ordenadas = sorted(
        historized_vars, key=lambda hv: (nome_do_flow[hv.flow_id], hv.block_id, hv.port)
    )

    def _bundle_tag(t: Tag) -> BundleTag:
        if t.connection_id is not None:
            return BundleTag(
                connection=nome_da_conexao[t.connection_id],
                name=t.name,
                node_id=t.node_id,
                direction=t.direction,
                data_type=t.data_type,
                eu=t.eu,
                description=t.description,
            )
        spec = spec_por_tag_id[t.id]
        return BundleTag(
            name=t.name,
            direction=t.direction,
            data_type=t.data_type,
            eu=t.eu,
            description=t.description,
            period_seconds=spec.period_seconds,
            code=spec.code,
            input_tags=[
                BundleCalcInputRef(connection=refs[origem_id][0], tag=refs[origem_id][1])
                for origem_id in entradas_por_calculada.get(t.id, [])
            ],
        )

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
                polling_period_ms=c.polling_period_ms,
            )
            for c in conexoes_ordenadas
        ],
        tags=[_bundle_tag(t) for t in tags_ordenadas],
        flows=[
            BundleFlow(
                name=f.name,
                ts_seconds=float(f.ts_seconds),
                desired_state=f.desired_state,
                graph=grafo_para_bundle(f.graph_json, refs),
                watchdog_enabled=f.watchdog_enabled,
                watchdog_connection=nome_da_conexao.get(f.watchdog_connection_id),
                watchdog_read_node_id=f.watchdog_read_node_id,
                watchdog_write_node_id=f.watchdog_write_node_id,
                watchdog_period_ms=f.watchdog_period_ms,
                watchdog_timeout_s=f.watchdog_timeout_s,
            )
            for f in flows_ordenados
        ],
        historized_vars=[
            BundleHistorizedVar(
                tag=refs[hv.tag_id][1],
                eu=tag_por_id[hv.tag_id].eu,
                flow=nome_do_flow[hv.flow_id],
                block_id=hv.block_id,
                port=hv.port,
            )
            for hv in historizadas_ordenadas
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

    # Contar por (connection, name): mesmo nome em conexões diferentes é legítimo — `Tag.name`
    # é único por conexão (`uq_tags_connection_name`), não por projeto. Tag calculada tem
    # `connection` None e é única por projeto (`uq_tags_project_name`); o mesmo Counter cobre
    # os dois casos porque `None` só agrupa com `None`.
    for (conexao, nome), contagem in Counter((t.connection, t.name) for t in bundle.tags).items():
        if contagem > 1:
            if conexao is None:
                problemas.append(f"tag calculada '{nome}' duplicada no bundle")
            else:
                problemas.append(f"tag '{nome}' duplicada na conexão '{conexao}'")

    nomes_conexao = {c.name for c in bundle.connections}
    for tag in bundle.tags:
        if tag.connection is not None and tag.connection not in nomes_conexao:
            problemas.append(
                f"tag '{tag.name}' referencia conexão '{tag.connection}' que não existe no bundle"
            )

    for flow in bundle.flows:
        if flow.watchdog_connection is not None and flow.watchdog_connection not in nomes_conexao:
            problemas.append(
                f"flow '{flow.name}' referencia conexão de watchdog "
                f"'{flow.watchdog_connection}' que não existe no bundle"
            )

    refs_validas = {(tag.connection, tag.name) for tag in bundle.tags}
    for flow in bundle.flows:
        problemas.extend(
            problemas_de_tag_ref(flow.graph, onde=f"fluxo '{flow.name}'", refs=refs_validas)
        )

    # Tags calculadas (RF-208, ADR-033 D6): cada `input_tags[]` tem de resolver para uma tag
    # deste bundle, respeitar o teto de entradas e nunca apontar para si mesma, e o SCRIPT
    # (dunder, sintaxe, atribuição de OUT, alcance de IN<n>) tem de passar pela MESMA
    # validação que o CRUD sempre impôs — sem isto, o import persistia código sem nenhuma
    # das quatro checagens (achado crítico da revisão de fase 5). Ciclo entre calculadas é
    # LEGAL (ADR-033 D5: last-value, sem deadlock) — não checado aqui de propósito, para não
    # recusar uma configuração que a própria API viva aceita. Não reintroduzir esta checagem.
    tags_calculadas = [t for t in bundle.tags if t.period_seconds is not None]
    for tag in tags_calculadas:
        refs = tag.input_tags or []
        if len(refs) > MAX_CALC_INPUTS:
            problemas.append(
                f"tag calculada '{tag.name}' tem {len(refs)} entrada(s); teto é {MAX_CALC_INPUTS}"
            )
        for chave, contagem in Counter((ref.connection, ref.tag) for ref in refs).items():
            if contagem > 1:
                problemas.append(
                    f"tag calculada '{tag.name}' repete a entrada '{chave[1]}' em duas posições"
                )
        for ref in refs:
            if ref.connection is None and ref.tag == tag.name:
                problemas.append(f"tag calculada '{tag.name}' não pode ter a si mesma como entrada")
            elif (ref.connection, ref.tag) not in refs_validas:
                problemas.append(
                    f"tag calculada '{tag.name}' referencia tag '{ref.tag}' "
                    f"(conexão {ref.connection!r}) que não existe no bundle"
                )
        assert tag.code is not None  # BundleTag._coerencia garante isso p/ tag calculada
        problemas.extend(
            f"tag calculada '{tag.name}': {p}" for p in problemas_do_script(tag.code, len(refs))
        )

    # Variáveis historiadas (RF-308, ADR-041 D5/D7): cada registro tem de resolver para um
    # flow do bundle, apontar para um bloco que realmente existe no grafo daquele flow, não
    # repetir a chave natural `(flow, block_id, port)` (mesma unicidade de
    # `uq_historized_vars_port`) e não colidir de nome com nenhuma outra tag do bundle — OPC,
    # calculada, ou outra variável historiada (o `Tag.name` que o import cria teria colisão
    # em `uq_tags_project_name`/`uq_tags_connection_name` só na hora do `flush()`, tarde
    # demais para um 422 agregado).
    nomes_flow = {f.name: f for f in bundle.flows}
    for hv in bundle.historized_vars:
        if hv.flow not in nomes_flow:
            problemas.append(
                f"variável historiada '{hv.tag}' referencia flow '{hv.flow}' que não existe "
                "no bundle"
            )

    for chave, contagem in Counter(
        (hv.flow, hv.block_id, hv.port) for hv in bundle.historized_vars
    ).items():
        if contagem > 1:
            problemas.append(
                f"variável historiada: porta '{chave[2]}' do bloco '{chave[1]}' do flow "
                f"'{chave[0]}' historiada duas vezes no bundle"
            )

    nomes_tag_existentes = {t.name for t in bundle.tags}
    for nome, contagem in Counter(hv.tag for hv in bundle.historized_vars).items():
        if contagem > 1 or nome in nomes_tag_existentes:
            problemas.append(
                f"variável historiada '{nome}' colide com o nome de outra tag do bundle"
            )

    for hv in bundle.historized_vars:
        flow = nomes_flow.get(hv.flow)
        if flow is None:
            continue  # já reportado acima (referencia flow inexistente)
        nodes = flow.graph.get("nodes")
        ids_de_no = (
            {n.get("id") for n in nodes if isinstance(n, dict)}
            if isinstance(nodes, list)
            else set()
        )
        if hv.block_id not in ids_de_no:
            problemas.append(
                f"variável historiada '{hv.tag}' referencia bloco '{hv.block_id}' que não "
                f"existe no flow '{hv.flow}'"
            )

    return problemas
