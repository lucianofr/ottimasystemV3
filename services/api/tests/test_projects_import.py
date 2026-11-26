"""Testes de `POST /api/projects/import` (spec F6 §3.2, RF-103).

Camada HTTP completa: teto de stream de 32 MiB antes de qualquer amarração Pydantic, as
quatro camadas de validação (schema_version, forma do bundle, referências internas, grafo),
transação única (falha em qualquer camada não deixa linha nenhuma no banco), 409 de nome
duplicado, `pending_secrets` com os 3 predicados e o evento de auditoria. A montagem pura
das camadas 1-3 já está coberta em `packages/ottima-core/tests/test_bundle.py`; aqui é o fio
HTTP completo: corpo bruto -> camadas -> insert -> resposta (mesmo padrão de duplicação de
fixture de `test_projects_export.py` — cada suíte é auto-contida).
"""

import base64

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from ottima_core.models import (
    CalculatedTag,
    CalculatedTagInput,
    Flow,
    OpcConnection,
    Project,
    SoftSensorBinding,
    SoftSensorModel,
    Tag,
)
from ottima_core.schemas.calculated_tags import MAX_CALC_INPUTS
from ottima_core.softsensor import load_model, predict, synthetic

IMPORT = "/api/projects/import"


async def _projeto(client, headers, name: str) -> int:
    r = await client.post("/api/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _conexao(client, headers, project_id: int, name: str, **extra) -> int:
    r = await client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": name,
            "endpoint": "opc.tcp://10.0.0.5:4840",
            **extra,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _tag(client, headers, connection_id: int, name: str, direction: str = "r") -> int:
    r = await client.post(
        "/api/tags",
        json={
            "connection_id": connection_id,
            "name": name,
            "node_id": f"ns=2;s={name}",
            "direction": direction,
            "data_type": "float",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _no_db(node_id: str, tipo: str, exec_order: int, tag_id: int) -> dict:
    return {
        "id": node_id,
        "type": tipo,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "tag_id": tag_id},
    }


def _grafo_db_read_write(tag_r: int, tag_w: int) -> dict:
    """Forma banco (`tag_id`): o menor grafo que passa por toda a validação do PUT."""
    return {
        "nodes": [_no_db("r1", "opc_read", 1, tag_r), _no_db("w1", "opc_write", 2, tag_w)],
        "edges": [
            {
                "id": "e1",
                "source": "r1",
                "sourceHandle": "out",
                "target": "w1",
                "targetHandle": "in",
            }
        ],
    }


async def _flow_com_grafo(client, headers, project_id: int, name: str, graph: dict) -> int:
    r = await client.post(
        "/api/flows",
        json={"project_id": project_id, "name": name, "ts_seconds": 1},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    flow_id = r.json()["id"]
    r = await client.put(f"/api/flows/{flow_id}", json={"graph_json": graph}, headers=headers)
    assert r.status_code == 200, r.text
    return flow_id


def _bundle(
    *,
    schema_version: int = 1,
    project_name: str = "Bundle",
    connections: list[dict] | None = None,
    tags: list[dict] | None = None,
    flows: list[dict] | None = None,
    historized_vars: list[dict] | None = None,
    soft_sensor_models: list[dict] | None = None,
    soft_sensor_bindings: list[dict] | None = None,
) -> dict:
    corpo = {
        "schema_version": schema_version,
        "exported_at": "2026-08-07T21:40:00Z",
        "project": {"name": project_name, "description": ""},
        "connections": connections or [],
        "tags": tags or [],
        "flows": flows or [],
    }
    # Chave omitida quando não há variável historiada: o formato antigo (sem a chave) tem de
    # continuar importando, e é isso que a maioria dos testes deste arquivo exercita.
    if historized_vars is not None:
        corpo["historized_vars"] = historized_vars
    if soft_sensor_models is not None:
        corpo["soft_sensor_models"] = soft_sensor_models
    if soft_sensor_bindings is not None:
        corpo["soft_sensor_bindings"] = soft_sensor_bindings
    return corpo


def _conexao_bundle(name: str, **campos) -> dict:
    return {"name": name, "endpoint": "opc.tcp://10.0.0.5:4840", **campos}


def _tag_bundle(connection: str, name: str, *, direction: str = "r") -> dict:
    return {
        "connection": connection,
        "name": name,
        "node_id": f"ns=2;s={name}",
        "direction": direction,
        "data_type": "float",
    }


def _tag_calc_bundle(
    name: str,
    *,
    period_seconds: int = 5,
    code: str = "OUT = 1.0",
    input_tags: list[dict] | None = None,
) -> dict:
    return {
        "name": name,
        "direction": "r",
        "data_type": "float",
        "period_seconds": period_seconds,
        "code": code,
        "input_tags": input_tags or [],
    }


def _no_bundle(node_id: str, tipo: str, exec_order: int, conn: str, tag: str) -> dict:
    return {
        "id": node_id,
        "type": tipo,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "tag_ref": {"connection": conn, "tag": tag}},
    }


def _grafo_bundle_um_no(conn: str, tag: str) -> dict:
    return {"nodes": [_no_bundle("r1", "opc_read", 1, conn, tag)], "edges": []}


def _grafo_bundle_read_write(conn: str, tag_r: str, tag_w: str, *, exec_order_w: int = 2) -> dict:
    return {
        "nodes": [
            _no_bundle("r1", "opc_read", 1, conn, tag_r),
            _no_bundle("w1", "opc_write", exec_order_w, conn, tag_w),
        ],
        "edges": [
            {
                "id": "e1",
                "source": "r1",
                "sourceHandle": "out",
                "target": "w1",
                "targetHandle": "in",
            }
        ],
    }


def _flow_bundle(name: str, graph: dict, *, ts_seconds: float = 1.0) -> dict:
    return {"name": name, "ts_seconds": ts_seconds, "desired_state": "stopped", "graph": graph}


async def _contagens(db_session) -> tuple[int, int, int, int]:
    async def _n(model) -> int:
        return (await db_session.execute(select(func.count()).select_from(model))).scalar_one()

    return (await _n(Project), await _n(OpcConnection), await _n(Tag), await _n(Flow))


async def test_import_201_round_trip_tags_novas_com_ids_diferentes(
    client, admin_headers, db_session
):
    pid = await _projeto(client, admin_headers, "Origem")
    gw = await _conexao(client, admin_headers, pid, "gw1")
    tag_r = await _tag(client, admin_headers, gw, "TT-101")
    tag_w = await _tag(client, admin_headers, gw, "FV-101", direction="w")
    await _flow_com_grafo(client, admin_headers, pid, "Malha", _grafo_db_read_write(tag_r, tag_w))

    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    bundle = r.json()

    r = await client.post(IMPORT, json={"name": "Destino", "bundle": bundle}, headers=admin_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["project"]["name"] == "Destino"
    assert body["project"]["is_active"] is False
    assert body["pending_secrets"] == [
        {
            "connection_name": "gw1",
            "needs_password": False,
            "needs_server_certificate": False,
            "needs_app_certificate": False,
        }
    ]
    novo_pid = body["project"]["id"]
    assert novo_pid != pid

    linhas = await db_session.execute(
        select(Tag.id, Tag.name)
        .join(OpcConnection, Tag.connection_id == OpcConnection.id)
        .where(OpcConnection.project_id == novo_pid)
    )
    ids_novos = {name: tag_id for tag_id, name in linhas}
    assert ids_novos["TT-101"] != tag_r
    assert ids_novos["FV-101"] != tag_w

    (flow_novo,) = await db_session.scalars(select(Flow).where(Flow.project_id == novo_pid))
    no_leitura = next(n for n in flow_novo.graph_json["nodes"] if n["id"] == "r1")
    no_escrita = next(n for n in flow_novo.graph_json["nodes"] if n["id"] == "w1")
    assert no_leitura["data"]["tag_id"] == ids_novos["TT-101"]
    assert no_escrita["data"]["tag_id"] == ids_novos["FV-101"]
    assert "tag_ref" not in no_leitura["data"]


async def test_import_round_trip_tags_calculadas_com_dependencia_entre_si(
    client, admin_headers, db_session
):
    """D6 (ADR-033): tag calculada segue no export/import com `period_seconds`/`code` e as
    entradas ordenadas — inclusive quando uma calculada lê outra calculada."""
    pid = await _projeto(client, admin_headers, "OrigemCalc")
    gw = await _conexao(client, admin_headers, pid, "gw1")
    tag_opc = await _tag(client, admin_headers, gw, "TT-101")

    tag_a = Tag(project_id=pid, name="CALC-A", direction="r", data_type="float")
    db_session.add(tag_a)
    await db_session.flush()
    db_session.add(CalculatedTag(tag_id=tag_a.id, code="OUT = IN1 * 2", period_seconds=5))
    db_session.add(CalculatedTagInput(calc_tag_id=tag_a.id, position=1, source_tag_id=tag_opc))

    tag_b = Tag(project_id=pid, name="CALC-B", direction="r", data_type="float")
    db_session.add(tag_b)
    await db_session.flush()
    db_session.add(CalculatedTag(tag_id=tag_b.id, code="OUT = IN1 + 1", period_seconds=10))
    db_session.add(CalculatedTagInput(calc_tag_id=tag_b.id, position=1, source_tag_id=tag_a.id))
    await db_session.commit()

    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    bundle = r.json()

    r = await client.post(
        IMPORT, json={"name": "DestinoCalc", "bundle": bundle}, headers=admin_headers
    )
    assert r.status_code == 201, r.text
    novo_pid = r.json()["project"]["id"]
    assert novo_pid != pid

    linhas = await db_session.execute(
        select(Tag.id, Tag.name).where(Tag.project_id == novo_pid, Tag.connection_id.is_(None))
    )
    ids_novos = {name: tag_id for tag_id, name in linhas}
    assert ids_novos["CALC-A"] != tag_a.id
    assert ids_novos["CALC-B"] != tag_b.id

    spec_a = await db_session.get(CalculatedTag, ids_novos["CALC-A"])
    spec_b = await db_session.get(CalculatedTag, ids_novos["CALC-B"])
    assert (spec_a.code, spec_a.period_seconds) == ("OUT = IN1 * 2", 5)
    assert (spec_b.code, spec_b.period_seconds) == ("OUT = IN1 + 1", 10)

    (entrada_a,) = await db_session.scalars(
        select(CalculatedTagInput).where(CalculatedTagInput.calc_tag_id == ids_novos["CALC-A"])
    )
    assert entrada_a.position == 1

    tag_opc_novo = await db_session.scalar(
        select(Tag.id)
        .join(OpcConnection, Tag.connection_id == OpcConnection.id)
        .where(OpcConnection.project_id == novo_pid, Tag.name == "TT-101")
    )
    assert entrada_a.source_tag_id == tag_opc_novo

    (entrada_b,) = await db_session.scalars(
        select(CalculatedTagInput).where(CalculatedTagInput.calc_tag_id == ids_novos["CALC-B"])
    )
    assert entrada_b.source_tag_id == ids_novos["CALC-A"]


async def test_import_round_trip_preserva_polling_period_ms(client, admin_headers, db_session):
    pid = await _projeto(client, admin_headers, "OrigemPolling")
    await _conexao(client, admin_headers, pid, "gw1", polling_period_ms=7500)

    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    bundle = r.json()
    assert bundle["connections"][0]["polling_period_ms"] == 7500

    r = await client.post(
        IMPORT, json={"name": "DestinoPolling", "bundle": bundle}, headers=admin_headers
    )
    assert r.status_code == 201, r.text
    novo_pid = r.json()["project"]["id"]

    conn = await db_session.scalar(
        select(OpcConnection).where(OpcConnection.project_id == novo_pid)
    )
    assert conn.polling_period_ms == 7500


async def test_import_bundle_sem_polling_period_ms_usa_default_1000(
    client, admin_headers, db_session
):
    bundle = _bundle(connections=[_conexao_bundle("gw1")])

    r = await client.post(
        IMPORT, json={"name": "DestinoSemPolling", "bundle": bundle}, headers=admin_headers
    )
    assert r.status_code == 201, r.text
    novo_pid = r.json()["project"]["id"]

    conn = await db_session.scalar(
        select(OpcConnection).where(OpcConnection.project_id == novo_pid)
    )
    assert conn.polling_period_ms == 1000


async def test_corpo_acima_de_32_mib_413_sem_materializar(client, admin_headers, db_session):
    antes = await _contagens(db_session)
    chunk = 65536
    total_chunks = 640  # 40 MiB, acima do teto de 32 MiB
    enviados = 0

    async def corpo():
        nonlocal enviados
        for _ in range(total_chunks):
            enviados += 1
            yield b"x" * chunk

    r = await client.post(
        IMPORT, content=corpo(), headers={**admin_headers, "Content-Type": "application/json"}
    )
    assert r.status_code == 413, r.text
    assert enviados < total_chunks  # o gerador não foi drenado
    assert await _contagens(db_session) == antes


async def test_import_aceita_corpo_de_20_mib_e_recusa_de_40(client, admin_headers, db_session):
    """O teto subiu de 4 para 32 MiB (ADR-046 D8): 20 MiB passam; 40 MiB declarados no
    `content-length` são recusados sem ler o corpo (o outro caminho do teto, ao lado do corte
    em fluxo do teste acima)."""
    bundle = _bundle(project_name="Grande")
    bundle["project"]["description"] = "x" * (20 * 1024 * 1024)
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 201, r.text[:300]

    antes = await _contagens(db_session)
    r = await client.post(
        IMPORT,
        content=b"x" * (40 * 1024 * 1024),
        headers={**admin_headers, "Content-Type": "application/json"},
    )
    assert r.status_code == 413, r.text
    assert r.json()["detail"] == "Corpo do import excede o limite de 32 MiB."
    assert await _contagens(db_session) == antes


async def test_corpo_nao_e_json_valido_422(client, admin_headers, db_session):
    antes = await _contagens(db_session)
    r = await client.post(
        IMPORT,
        content=b"isto nao e json {",
        headers={**admin_headers, "Content-Type": "application/json"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Corpo não é JSON válido"
    assert await _contagens(db_session) == antes


async def test_schema_version_diferente_422_sem_tocar_banco(client, admin_headers, db_session):
    antes = await _contagens(db_session)
    r = await client.post(IMPORT, json={"bundle": _bundle(schema_version=2)}, headers=admin_headers)
    assert r.status_code == 422, r.text
    # Mensagem própria da camada 1 (§3.2-2) — não a tradução genérica de `literal_error` que a
    # camada 2 (`ProjectBundle.model_validate`) produziria para o mesmo campo ("schema_version:
    # valor inválido; esperado um de: 1"). Provar o texto exato garante que quem recusou foi a
    # camada 1 (recusa imediata, sem tentativa de migração), não a camada 2 — remover a camada 1
    # inteira produziria um 422 parecido, mas com este texto diferente.
    assert (
        r.json()["detail"]
        == "Import recusado (1 problemas) | schema_version 2 não suportado; esperado 1"
    )
    assert await _contagens(db_session) == antes


async def test_schema_version_diferente_422_nao_valida_resto_do_bundle(
    client, admin_headers, db_session
):
    """ "Sem tentativa de migração" (§3.2-2) tem de ser observável: um bundle com
    `schema_version: 2` e o resto do conteúdo também inválido (`auth_mode` fora do enum) recusa
    só pela versão — a camada 2 nunca roda, então o problema do `auth_mode` não aparece na lista
    agregada. Se a camada 1 fosse removida (ou rodasse depois da 2), este teste veria 2+
    problemas e/ou o texto de `auth_mode` no detail."""
    antes = await _contagens(db_session)
    bundle = _bundle(schema_version=2, connections=[_conexao_bundle("gw1", auth_mode="invalido")])
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail == "Import recusado (1 problemas) | schema_version 2 não suportado; esperado 1"
    assert "auth_mode" not in detail
    assert await _contagens(db_session) == antes


async def test_campo_proibido_422_camada2_agregado_com_varios_problemas(
    client, admin_headers, db_session
):
    antes = await _contagens(db_session)
    bundle = _bundle(
        connections=[
            _conexao_bundle("gw1", auth_password_enc="nao-pode-atravessar"),
            _conexao_bundle("gw2", auth_mode="invalido"),
        ]
    )
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail.startswith("Import recusado (2 problemas)")
    assert detail.count(" | ") == 2
    assert await _contagens(db_session) == antes


async def test_tag_ref_referencia_conexao_ausente_422_camada3(client, admin_headers, db_session):
    antes = await _contagens(db_session)
    bundle = _bundle(
        connections=[_conexao_bundle("gw1")],
        tags=[_tag_bundle("gw1", "TT-101")],
        flows=[_flow_bundle("Malha", _grafo_bundle_um_no("gw-fantasma", "TT-101"))],
    )
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 422, r.text
    assert r.json()["detail"].startswith("Import recusado")
    assert await _contagens(db_session) == antes


async def test_variavel_historiada_com_porta_inexistente_422(client, admin_headers, db_session):
    """Fronteira de confiança do ADR-041 D7: a coerência do bundle vê o grafo cru e sabe
    checar id de bloco, mas porta é dinâmica (mpc/script) e entrada precisa de aresta — o
    import reaplica a MESMA regra do cadastro interativo, senão nasce variável historiada
    morta, visível no seletor do Trend e sem nunca receber dado."""
    antes = await _contagens(db_session)
    bundle = _bundle(
        connections=[_conexao_bundle("gw1")],
        tags=[_tag_bundle("gw1", "TT-101")],
        flows=[_flow_bundle("Malha", _grafo_bundle_um_no("gw1", "TT-101"))],
        historized_vars=[
            {
                "tag": "Malha.r1.nao_existe",
                "eu": "",
                "flow": "Malha",
                "block_id": "r1",
                "port": "nao_existe",
            }
        ],
    )
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 422, r.text
    assert "Porta não existe neste bloco" in r.json()["detail"]
    assert await _contagens(db_session) == antes


async def test_import_materializa_variavel_historiada(client, admin_headers):
    """Round-trip do caminho FELIZ: o bundle não traz a linha de `tags` da historiada (ela
    cai fora do XOR de `BundleTag`), então o import tem de criá-la e ligar o registro ao
    `flow_id` resolvido por NOME — com os dois `flush` na ordem certa."""
    bundle = _bundle(
        project_name="ComHistoriada",
        connections=[_conexao_bundle("gw1")],
        tags=[_tag_bundle("gw1", "TT-101")],
        flows=[_flow_bundle("Malha", _grafo_bundle_um_no("gw1", "TT-101"))],
        historized_vars=[
            {"tag": "Malha.r1.out", "eu": "°C", "flow": "Malha", "block_id": "r1", "port": "out"}
        ],
    )
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 201, r.text
    projeto_id = r.json()["project"]["id"]

    flows = (await client.get(f"/api/flows?project_id={projeto_id}", headers=admin_headers)).json()
    flow_id = next(f["id"] for f in flows if f["name"] == "Malha")
    lista = (
        await client.get(f"/api/historized-vars?flow_id={flow_id}", headers=admin_headers)
    ).json()
    assert lista == [
        {
            "tag_id": lista[0]["tag_id"],
            "flow_id": flow_id,
            "block_id": "r1",
            "port": "out",
            "name": "Malha.r1.out",
            "eu": "°C",
        }
    ]

    tag = (await client.get(f"/api/tags/{lista[0]['tag_id']}", headers=admin_headers)).json()
    assert (tag["project_id"], tag["connection_id"], tag["direction"], tag["data_type"]) == (
        projeto_id,
        None,
        "r",
        "float",
    )


async def test_nome_duplicado_no_bundle_422_camada3_sem_integrity_error(
    client, admin_headers, db_session
):
    antes = await _contagens(db_session)
    bundle = _bundle(connections=[_conexao_bundle("gw1"), _conexao_bundle("gw1")])
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 422, r.text  # nunca 500 (TST-04)
    assert "duplicada" in r.json()["detail"]
    assert await _contagens(db_session) == antes


async def test_tag_calculada_com_input_tags_irresolvel_422_camada3(
    client, admin_headers, db_session
):
    antes = await _contagens(db_session)
    bundle = _bundle(
        tags=[_tag_calc_bundle("CALC-1", input_tags=[{"connection": None, "tag": "fantasma"}])]
    )
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 422, r.text  # nunca 500, e nada inserido antes de detectar
    assert r.json()["detail"].startswith("Import recusado")
    assert await _contagens(db_session) == antes


async def test_ciclo_entre_tags_calculadas_round_trip_com_sucesso(
    client, admin_headers, db_session
):
    """ADR-033 D5: ciclo entre tags calculadas é seguro (last-value, sem deadlock) — o
    import não pode recusar uma configuração que a própria API viva aceita."""
    bundle = _bundle(
        tags=[
            _tag_calc_bundle("CALC-A", input_tags=[{"connection": None, "tag": "CALC-B"}]),
            _tag_calc_bundle("CALC-B", input_tags=[{"connection": None, "tag": "CALC-A"}]),
        ]
    )
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 201, r.text
    novo_pid = r.json()["project"]["id"]

    linhas = await db_session.execute(
        select(Tag.name).where(Tag.project_id == novo_pid, Tag.connection_id.is_(None))
    )
    assert {nome for (nome,) in linhas} == {"CALC-A", "CALC-B"}


async def test_tag_calculada_com_script_dunder_422_camada3_sem_insercao(
    client, admin_headers, db_session
):
    """Achado crítico da revisão de fase 5: o import persistia código sem NENHUMA das
    quatro checagens que o CRUD sempre impôs — inclusive a fuga clássica de sandbox."""
    antes = await _contagens(db_session)
    bundle = _bundle(
        tags=[_tag_calc_bundle("CALC-1", code="OUT = ().__class__.__base__.__subclasses__()")]
    )
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 422, r.text
    assert "dunder" in r.json()["detail"].lower()
    assert await _contagens(db_session) == antes


async def test_tag_calculada_acima_do_teto_de_entradas_422_camada3_sem_insercao(
    client, admin_headers, db_session
):
    antes = await _contagens(db_session)
    tags_origem = [_tag_bundle("gw1", f"TT-{i}") for i in range(MAX_CALC_INPUTS + 1)]
    entradas = [{"connection": "gw1", "tag": f"TT-{i}"} for i in range(MAX_CALC_INPUTS + 1)]
    bundle = _bundle(
        connections=[_conexao_bundle("gw1")],
        tags=[*tags_origem, _tag_calc_bundle("CALC-1", code="OUT = 1.0", input_tags=entradas)],
    )
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 422, r.text
    assert str(MAX_CALC_INPUTS) in r.json()["detail"]
    assert await _contagens(db_session) == antes


async def test_exec_order_nao_contiguo_422_camada4_e_rollback_completo(
    client, admin_headers, db_session
):
    antes = await _contagens(db_session)
    bundle = _bundle(
        connections=[_conexao_bundle("gw1")],
        tags=[_tag_bundle("gw1", "TT-101"), _tag_bundle("gw1", "FV-101", direction="w")],
        flows=[
            _flow_bundle(
                "Malha", _grafo_bundle_read_write("gw1", "TT-101", "FV-101", exec_order_w=3)
            )
        ],
    )
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail.startswith("Import recusado")
    assert "exec_order" in detail
    # Rollback tem de desfazer projeto/conexão/tag já flushados antes do grafo reprovar
    assert await _contagens(db_session) == antes


async def test_nome_de_projeto_colidindo_409_banco_inalterado(client, admin_headers, db_session):
    await _projeto(client, admin_headers, "JaExiste")
    antes = await _contagens(db_session)
    r = await client.post(
        IMPORT, json={"bundle": _bundle(project_name="JaExiste")}, headers=admin_headers
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Nome de projeto já em uso"
    assert await _contagens(db_session) == antes


async def test_rbac_operador_403_e_sem_token_401(client, admin_headers, operator_headers):
    bundle = _bundle()
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=operator_headers)
    assert r.status_code == 403

    r = await client.post(IMPORT, json={"bundle": bundle})
    assert r.status_code == 401


async def test_pending_secrets_tres_predicados_sem_certificado_de_app(
    client, admin_headers, db_session
):
    """Sem certificado de aplicação gerado: as 3 fórmulas de §3.2-8 num bundle só, incluindo
    o caso do achado F6R-14 (`auth_mode: certificate` com `security_policy: none`)."""
    bundle = _bundle(
        connections=[
            _conexao_bundle("gw-senha", auth_mode="user_password", auth_username="ottima"),
            _conexao_bundle("gw-seguro", security_policy="basic256sha256", security_mode="sign"),
            _conexao_bundle("gw-cert", auth_mode="certificate"),
        ]
    )
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 201, r.text
    por_nome = {p["connection_name"]: p for p in r.json()["pending_secrets"]}
    assert por_nome["gw-senha"] == {
        "connection_name": "gw-senha",
        "needs_password": True,
        "needs_server_certificate": False,
        "needs_app_certificate": False,
    }
    assert por_nome["gw-seguro"] == {
        "connection_name": "gw-seguro",
        "needs_password": False,
        "needs_server_certificate": True,
        "needs_app_certificate": True,
    }
    # F6R-14: sem o 3º predicado, esta conexão teria pendência vazia e falharia depois em
    # cert_missing sem aviso nenhum (policy none não bastaria para sinalizar a exigência).
    assert por_nome["gw-cert"] == {
        "connection_name": "gw-cert",
        "needs_password": False,
        "needs_server_certificate": False,
        "needs_app_certificate": True,
    }


async def test_pending_secrets_com_certificado_de_app_existente(client, admin_headers):
    gerado = await client.post("/api/certificates/app/generate", headers=admin_headers)
    assert gerado.status_code == 201, gerado.text

    bundle = _bundle(
        connections=[
            _conexao_bundle("gw-seguro", security_policy="basic256sha256", security_mode="sign"),
            _conexao_bundle("gw-cert", auth_mode="certificate"),
        ]
    )
    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)
    assert r.status_code == 201, r.text
    por_nome = {p["connection_name"]: p for p in r.json()["pending_secrets"]}
    assert por_nome["gw-seguro"]["needs_app_certificate"] is False
    assert por_nome["gw-cert"]["needs_app_certificate"] is False


async def test_evento_project_imported_publicado(client, admin_headers, eventos):
    uid = (await client.get("/api/auth/me", headers=admin_headers)).json()["id"]
    pid = await _projeto(client, admin_headers, "ComEventoOrigem")
    gw = await _conexao(client, admin_headers, pid, "gw1")
    tag_r = await _tag(client, admin_headers, gw, "TT-101")
    tag_w = await _tag(client, admin_headers, gw, "FV-101", direction="w")
    await _flow_com_grafo(client, admin_headers, pid, "Malha", _grafo_db_read_write(tag_r, tag_w))
    bundle = (await client.get(f"/api/projects/{pid}/export", headers=admin_headers)).json()
    await eventos()  # descarta o que o setup acima emitiu (project_exported)

    r = await client.post(
        IMPORT, json={"name": "ComEventoDestino", "bundle": bundle}, headers=admin_headers
    )
    assert r.status_code == 201, r.text
    novo_pid = r.json()["project"]["id"]
    (ev,) = await eventos()
    assert ev["severity"] == "info"
    assert ev["origin"] == f"user:{uid}"
    assert ev["payload"] == {
        "kind": "project_imported",
        "project_id": novo_pid,
        "name": "ComEventoDestino",
        "connections": 1,
        "tags": 2,
        "flows": 1,
        # Contagem nova do ADR-041: o import também materializa as variáveis historiadas do
        # bundle, e o número entra na auditoria junto das outras contagens.
        "historized_vars": 0,
    }


# ------------------------------------------------------------- sensor virtual (RF-590, ADR-046 D8)


def _no_sv(tipo: str = "soft_sensor_pls") -> dict:
    return {
        "id": "sv1",
        "type": tipo,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": 3, "n_inputs": 2, "output_eu": "%"},
    }


def _arestas_sv() -> list[dict]:
    """`r1`/`r2` -> `IN1`/`IN2` de `sv1`."""
    return [
        {
            "id": f"e{i}",
            "source": f"r{i}",
            "sourceHandle": "out",
            "target": "sv1",
            "targetHandle": f"IN{i}",
        }
        for i in (1, 2)
    ]


def _grafo_sv_bundle(conn: str, tag_a: str, tag_b: str, tipo: str = "soft_sensor_pls") -> dict:
    """`r1`/`r2` (opc_read) alimentando `sv1` (2 entradas), na forma do bundle (`tag_ref`)."""
    return {
        "nodes": [
            _no_bundle("r1", "opc_read", 1, conn, tag_a),
            _no_bundle("r2", "opc_read", 2, conn, tag_b),
            _no_sv(tipo),
        ],
        "edges": _arestas_sv(),
    }


def _modelo_sv_bundle(nome: str = "m1", artefato: tuple | None = None, **campos) -> dict:
    meta, blob = artefato or synthetic.pls([1.0, 2.0], 0.5)
    return {
        "name": nome,
        "method": meta.method,
        "period_s": meta.period_s,
        "n_inputs": len(meta.inputs),
        "meta": meta.model_dump(mode="json"),
        "weights_b64": base64.b64encode(blob).decode("ascii"),
        "input_tags": [{"connection": "gw1", "tag": "TT-A"}, {"connection": "gw1", "tag": "TT-B"}],
        **campos,
    }


def _bundle_sv(modelos: list[dict], vinculos: list[dict], *, tipo: str = "soft_sensor_pls") -> dict:
    return _bundle(
        connections=[_conexao_bundle("gw1")],
        tags=[_tag_bundle("gw1", "TT-A"), _tag_bundle("gw1", "TT-B")],
        flows=[_flow_bundle("Malha", _grafo_sv_bundle("gw1", "TT-A", "TT-B", tipo))],
        soft_sensor_models=modelos,
        soft_sensor_bindings=vinculos,
    )


_VINCULO = {"flow": "Malha", "block_id": "sv1", "model": "m1"}


async def _contagens_sv(db_session) -> tuple[int, int]:
    async def _n(model) -> int:
        return (await db_session.execute(select(func.count()).select_from(model))).scalar_one()

    return await _n(SoftSensorModel), await _n(SoftSensorBinding)


async def _id_admin(client, admin_headers) -> int:
    return (await client.get("/api/auth/me", headers=admin_headers)).json()["id"]


async def test_import_cria_vinculo_so_com_o_desejado(client, admin_headers, db_session):
    meta, blob = synthetic.pls([1.0, 2.0], 0.5)
    bundle = _bundle_sv([_modelo_sv_bundle("m1")], [_VINCULO])

    r = await client.post(
        IMPORT, json={"name": "ComSensor", "bundle": bundle}, headers=admin_headers
    )
    assert r.status_code == 201, r.text
    novo_pid = r.json()["project"]["id"]
    autor = f"user:{await _id_admin(client, admin_headers)}"

    modelo = await db_session.scalar(
        select(SoftSensorModel)
        .options(undefer(SoftSensorModel.weights))
        .where(SoftSensorModel.project_id == novo_pid)
    )
    assert (modelo.name, modelo.method, modelo.n_inputs, modelo.period_s) == ("m1", "pls", 2, 1.0)
    assert modelo.created_by == autor
    assert modelo.weights == blob
    assert modelo.meta == meta.model_dump(mode="json")
    ids_das_tags = dict(
        (
            await db_session.execute(
                select(Tag.name, Tag.id)
                .join(OpcConnection, Tag.connection_id == OpcConnection.id)
                .where(OpcConnection.project_id == novo_pid)
            )
        ).all()
    )
    assert modelo.input_tag_ids == [ids_das_tags["TT-A"], ids_das_tags["TT-B"]]

    flow_id = await db_session.scalar(select(Flow.id).where(Flow.project_id == novo_pid))
    vinculo = (
        await db_session.execute(
            select(
                SoftSensorBinding.desired_model_id,
                SoftSensorBinding.active_model_id,
                SoftSensorBinding.candidate_model_id,
                SoftSensorBinding.updated_by,
            ).where(SoftSensorBinding.flow_id == flow_id, SoftSensorBinding.block_id == "sv1")
        )
    ).one()
    assert tuple(vinculo) == (modelo.id, None, None, autor)


async def test_import_com_tag_de_entrada_que_nao_resolve_nao_falha(
    client, admin_headers, db_session
):
    modelo = _modelo_sv_bundle("m1", input_tags=[{"connection": "gw1", "tag": "NAO-EXISTE"}, None])
    r = await client.post(
        IMPORT,
        json={"name": "SemTags", "bundle": _bundle_sv([modelo], [_VINCULO])},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    novo_pid = r.json()["project"]["id"]
    ids = await db_session.scalar(
        select(SoftSensorModel.input_tag_ids).where(SoftSensorModel.project_id == novo_pid)
    )
    assert ids == []


async def test_roundtrip_export_import_preserva_a_estimativa(client, admin_headers, db_session):
    pid = await _projeto(client, admin_headers, "OrigemSensor")
    gw = await _conexao(client, admin_headers, pid, "gw1")
    tag_a = await _tag(client, admin_headers, gw, "TT-A")
    tag_b = await _tag(client, admin_headers, gw, "TT-B")
    grafo = {
        "nodes": [
            _no_db("r1", "opc_read", 1, tag_a),
            _no_db("r2", "opc_read", 2, tag_b),
            _no_sv("soft_sensor_esn"),
        ],
        "edges": _arestas_sv(),
    }
    flow_id = await _flow_com_grafo(client, admin_headers, pid, "Malha", grafo)

    meta, blob = synthetic.esn(2, units=8, warmup=4)
    original = SoftSensorModel(
        project_id=pid,
        name="esn-1",
        method="esn",
        period_s=meta.period_s,
        n_inputs=2,
        input_tag_ids=[tag_a, tag_b],
        meta=meta.model_dump(mode="json"),
        weights=blob,
        created_by="user:1",
    )
    db_session.add(original)
    await db_session.flush()
    db_session.add(
        SoftSensorBinding(
            flow_id=flow_id, block_id="sv1", desired_model_id=original.id, updated_by="user:1"
        )
    )
    await db_session.commit()

    exportado = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert exportado.status_code == 200, exportado.text
    r = await client.post(
        IMPORT, json={"name": "DestinoSensor", "bundle": exportado.json()}, headers=admin_headers
    )
    assert r.status_code == 201, r.text
    novo_pid = r.json()["project"]["id"]

    importado = await db_session.scalar(
        select(SoftSensorModel)
        .options(undefer(SoftSensorModel.weights))
        .where(SoftSensorModel.project_id == novo_pid)
    )
    assert importado.id != original.id
    janela = np.random.default_rng(7).normal(size=(meta.warmup_steps, 2))
    estimativa_original = predict(load_model(original.id, original.meta, blob), janela)
    estimativa_importada = predict(
        load_model(importado.id, importado.meta, importado.weights), janela
    )
    assert np.isfinite(estimativa_original)
    assert estimativa_importada == estimativa_original


def _lixo_b64() -> str:
    return base64.b64encode(b"nao sou um npz").decode("ascii")


def _defeito(nome: str) -> tuple[list[dict], list[dict]]:
    """`(modelos, vinculos)` de um bundle com exatamente um defeito de sensor virtual."""
    if nome == "base64":
        return [_modelo_sv_bundle("m1", weights_b64="isto nao e base64!")], [_VINCULO]
    if nome == "artefato":
        return [_modelo_sv_bundle("m1", weights_b64=_lixo_b64())], [_VINCULO]
    if nome == "nome_duplicado":
        return [_modelo_sv_bundle("m1"), _modelo_sv_bundle("m1")], [_VINCULO]
    if nome == "vinculo_orfao":
        return [_modelo_sv_bundle("m1")], [{**_VINCULO, "flow": "nao-existe"}]
    if nome == "bloco_comum":
        return [_modelo_sv_bundle("m1")], [{**_VINCULO, "block_id": "r1"}]
    raise AssertionError(nome)


@pytest.mark.parametrize(
    "defeito", ["base64", "artefato", "nome_duplicado", "vinculo_orfao", "bloco_comum"]
)
async def test_import_recusado_nao_grava_nada(client, admin_headers, db_session, defeito):
    modelos, vinculos = _defeito(defeito)
    antes = (await _contagens(db_session), await _contagens_sv(db_session))

    r = await client.post(
        IMPORT, json={"bundle": _bundle_sv(modelos, vinculos)}, headers=admin_headers
    )

    assert r.status_code == 422, r.text
    assert r.json()["detail"].startswith("Import recusado")
    assert (await _contagens(db_session), await _contagens_sv(db_session)) == antes


async def test_bundle_antigo_sem_os_campos_novos_continua_importando(
    client, admin_headers, db_session
):
    bundle = _bundle(
        connections=[_conexao_bundle("gw1")],
        tags=[_tag_bundle("gw1", "TT-101"), _tag_bundle("gw1", "FV-101", direction="w")],
        flows=[_flow_bundle("Malha", _grafo_bundle_read_write("gw1", "TT-101", "FV-101"))],
    )
    assert "soft_sensor_models" not in bundle and "soft_sensor_bindings" not in bundle
    antes = await _contagens_sv(db_session)

    r = await client.post(IMPORT, json={"bundle": bundle}, headers=admin_headers)

    assert r.status_code == 201, r.text
    assert await _contagens_sv(db_session) == antes
