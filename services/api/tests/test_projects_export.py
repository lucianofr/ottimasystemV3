"""Testes de `GET /api/projects/{project_id}/export` (spec F6 §3.1, RF-102 emendado).

Camada HTTP: monta o bundle a partir de dados reais no banco de teste (projeto, conexões,
tags, flow) e cobre RBAC, 404, `Content-Disposition`/slug, o evento de auditoria e a
ausência de segredos/ids em qualquer profundidade do corpo. A montagem pura do bundle
(ordenação, `tag_ref` nos 6 lugares, coerência interna) já está coberta em
`packages/ottima-core/tests/test_bundle.py`; aqui é o fio HTTP completo: banco -> query do
router -> `montar_bundle` -> resposta.
"""

import base64
from collections.abc import Iterator

from ottima_core.models import (
    CalculatedTag,
    CalculatedTagInput,
    Flow,
    OpcConnection,
    SoftSensorBinding,
    SoftSensorModel,
    Tag,
)
from ottima_core.softsensor import synthetic


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


def _no_opc(node_id: str, tipo: str, exec_order: int, tag_id: int) -> dict:
    return {
        "id": node_id,
        "type": tipo,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "tag_id": tag_id},
    }


def _grafo_read_write(tag_r: int, tag_w: int) -> dict:
    """Read -> write: o menor grafo que passa por toda a validação do PUT (spec §5.2)."""
    return {
        "nodes": [_no_opc("r1", "opc_read", 1, tag_r), _no_opc("w1", "opc_write", 2, tag_w)],
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


# Mesma varredura de packages/ottima-core/tests/test_bundle.py, sobre o corpo JSON já
# desserializado da resposta HTTP (duplicado de propósito: mesmo padrão de duplicação de
# fixture já usado entre test_operate.py/test_history_mpc.py — cada suíte é auto-contida).
_CAMPOS_PROIBIDOS = frozenset(
    {
        "auth_password",
        "auth_password_enc",
        "server_cert_file",
        "id",
        "project_id",
        "connection_id",
        "is_active",
        "created_at",
        "updated_at",
    }
)


def _chaves_proibidas(valor: object, *, dentro_do_grafo: bool = False) -> Iterator[str]:
    """`id` só é permitido dentro de `flows[].graph`: ali é o identificador do nó do React
    Flow (string), nunca uma PK. Os outros campos continuam proibidos em qualquer
    profundidade, inclusive dentro do grafo."""
    if isinstance(valor, dict):
        for chave, sub in valor.items():
            if chave in _CAMPOS_PROIBIDOS and not (chave == "id" and dentro_do_grafo):
                yield chave
            yield from _chaves_proibidas(sub, dentro_do_grafo=dentro_do_grafo or chave == "graph")
    elif isinstance(valor, list):
        for item in valor:
            yield from _chaves_proibidas(item, dentro_do_grafo=dentro_do_grafo)


async def test_export_200_bundle_valido_e_content_disposition(client, admin_headers):
    """2 conexões, tag homônima entre elas (TST-01), flow com grafo read->write."""
    pid = await _projeto(client, admin_headers, "Planta C-101")
    gw1 = await _conexao(client, admin_headers, pid, "gw1", polling_period_ms=2500)
    gw2 = await _conexao(client, admin_headers, pid, "gw2")
    tag_r = await _tag(client, admin_headers, gw1, "TT-101")
    tag_w = await _tag(client, admin_headers, gw1, "FV-101", direction="w")
    await _tag(client, admin_headers, gw2, "TT-101")  # homônima em outra conexão
    await _flow_com_grafo(client, admin_headers, pid, "Malha", _grafo_read_write(tag_r, tag_w))

    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"] == 'attachment; filename="planta-c-101.ottima.json"'

    body = r.json()
    assert body["schema_version"] == 1
    assert body["project"] == {"name": "Planta C-101", "description": ""}
    assert [c["name"] for c in body["connections"]] == ["gw1", "gw2"]
    assert [(c["name"], c["polling_period_ms"]) for c in body["connections"]] == [
        ("gw1", 2500),
        ("gw2", 1000),
    ]
    assert [(t["connection"], t["name"]) for t in body["tags"]] == [
        ("gw1", "FV-101"),
        ("gw1", "TT-101"),
        ("gw2", "TT-101"),
    ]
    (flow,) = body["flows"]
    no_leitura = next(n for n in flow["graph"]["nodes"] if n["id"] == "r1")
    no_escrita = next(n for n in flow["graph"]["nodes"] if n["id"] == "w1")
    assert no_leitura["data"]["tag_ref"] == {"connection": "gw1", "tag": "TT-101"}
    assert no_escrita["data"]["tag_ref"] == {"connection": "gw1", "tag": "FV-101"}
    assert "tag_id" not in no_leitura["data"] and "tag_id" not in no_escrita["data"]


async def test_projeto_inexistente_404(client, admin_headers):
    r = await client.get("/api/projects/999999/export", headers=admin_headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "Projeto não encontrado"


async def test_rbac_operador_403_e_sem_token_401(client, admin_headers, operator_headers):
    pid = await _projeto(client, admin_headers, "Restrito")
    r = await client.get(f"/api/projects/{pid}/export", headers=operator_headers)
    assert r.status_code == 403

    r = await client.get(f"/api/projects/{pid}/export")
    assert r.status_code == 401


async def test_slug_simbolos_reduz_a_projeto(client, admin_headers):
    pid = await _projeto(client, admin_headers, "!!!???")
    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="projeto.ottima.json"'


async def test_slug_nome_acentuado_com_barras(client, admin_headers):
    pid = await _projeto(client, admin_headers, "Café / Preto //")
    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="caf-preto.ottima.json"'


async def test_varredura_recursiva_sem_segredos_nem_ids(client, admin_headers, db_session):
    pid = await _projeto(client, admin_headers, "SemVazamento")
    gw = await _conexao(
        client,
        admin_headers,
        pid,
        "gw-seguro",
        auth_mode="user_password",
        auth_username="ottima",
        auth_password="segredo-do-plc",
    )
    # `server_cert_file` só se grava pelo upload real de X.509 (POST .../server-certificate);
    # direto no banco é o mesmo atalho de test_operate.py para exercitar um estado que a API
    # não deixa criar sozinha, sem depender de um certificado real na fixture.
    conn = await db_session.get(OpcConnection, gw)
    conn.server_cert_file = "conn-seguro.der"
    await db_session.commit()

    tag_r = await _tag(client, admin_headers, gw, "TT-101")
    tag_w = await _tag(client, admin_headers, gw, "FV-101", direction="w")
    await _flow_com_grafo(client, admin_headers, pid, "Malha", _grafo_read_write(tag_r, tag_w))

    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert list(_chaves_proibidas(r.json())) == []


async def test_evento_project_exported_publicado(client, admin_headers, eventos):
    uid = (await client.get("/api/auth/me", headers=admin_headers)).json()["id"]
    pid = await _projeto(client, admin_headers, "ComEvento")
    await eventos()  # descarta o que o setup acima não deveria emitir

    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    (ev,) = await eventos()
    assert ev["severity"] == "info"
    assert ev["origin"] == f"user:{uid}"
    assert ev["payload"] == {"kind": "project_exported", "project_id": pid, "name": "ComEvento"}


async def test_tags_carregadas_apenas_pelas_conexoes_do_projeto(client, admin_headers):
    """Regressão da revisão 1.3: se as tags fossem carregadas por uma consulta independente
    (sem passar pelas conexões do próprio projeto), uma tag de OUTRO projeto quebraria
    `ref_por_id` com `KeyError` (viraria 500). O bundle exportado só pode conter o que é
    deste projeto, mesmo com outro projeto populado por perto."""
    outro_pid = await _projeto(client, admin_headers, "Vizinho")
    outro_cid = await _conexao(client, admin_headers, outro_pid, "gw-vizinho")
    await _tag(client, admin_headers, outro_cid, "TT-vizinha")

    pid = await _projeto(client, admin_headers, "Isolado")
    cid = await _conexao(client, admin_headers, pid, "gw-isolado")
    await _tag(client, admin_headers, cid, "TT-isolada")

    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["name"] for c in body["connections"]] == ["gw-isolado"]
    assert [t["name"] for t in body["tags"]] == ["TT-isolada"]


async def test_grafo_com_tag_que_nao_resolve_e_422_agregado(client, admin_headers, db_session):
    """Referência que não resolve aborta com 422 (§2.2-5), nunca exporta bundle quebrado nem
    vira 500. Só alcançável inserindo direto no banco — `PUT /api/flows/{id}` nunca grava um
    grafo cujo `tag_id` não pertença ao projeto do flow (mesmo atalho de test_operate.py)."""
    pid = await _projeto(client, admin_headers, "GrafoOrfao")
    flow_orfao = Flow(
        project_id=pid,
        name="Orfao",
        ts_seconds=1,
        graph_json={
            "nodes": [
                {
                    "id": "r1",
                    "type": "opc_read",
                    "position": {"x": 0.0, "y": 0.0},
                    "data": {"exec_order": 1, "tag_id": 999999},
                }
            ],
            "edges": [],
        },
    )
    db_session.add(flow_orfao)
    await db_session.commit()

    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 422, r.text
    assert r.json()["detail"].startswith("Export recusado")


async def test_export_projeto_so_com_tags_calculadas_200(client, admin_headers, db_session):
    """D6 (ADR-033): sem esta fatia, o INNER JOIN com `opc_connections` omitia a tag
    calculada em silêncio (nunca 500, só um export incompleto)."""
    pid = await _projeto(client, admin_headers, "SoCalculadas")
    tag = Tag(project_id=pid, name="CALC-1", direction="r", data_type="float")
    db_session.add(tag)
    await db_session.flush()
    db_session.add(CalculatedTag(tag_id=tag.id, code="OUT = 1.0", period_seconds=5))
    await db_session.commit()

    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connections"] == []
    (bt,) = body["tags"]
    assert bt["name"] == "CALC-1"
    assert bt["connection"] is None
    assert bt["node_id"] is None
    assert bt["period_seconds"] == 5
    assert bt["code"] == "OUT = 1.0"
    assert bt["input_tags"] == []


async def test_export_tag_calculada_com_entradas_ordenadas_e_tag_opc_antes(
    client, admin_headers, db_session
):
    pid = await _projeto(client, admin_headers, "ComEntradas")
    gw = await _conexao(client, admin_headers, pid, "gw1")
    tag_opc = await _tag(client, admin_headers, gw, "TT-101")

    tag_calc = Tag(project_id=pid, name="CALC-1", direction="r", data_type="float")
    db_session.add(tag_calc)
    await db_session.flush()
    db_session.add(CalculatedTag(tag_id=tag_calc.id, code="OUT = IN1 * 2", period_seconds=5))
    db_session.add(CalculatedTagInput(calc_tag_id=tag_calc.id, position=1, source_tag_id=tag_opc))
    await db_session.commit()

    r = await client.get(f"/api/projects/{pid}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [t["name"] for t in body["tags"]] == ["TT-101", "CALC-1"]
    calc = body["tags"][1]
    assert calc["input_tags"] == [{"connection": "gw1", "tag": "TT-101"}]


# ------------------------------------------------------------- sensor virtual (RF-590, ADR-046 D8)


def _grafo_sensor_virtual(tag_a: int, tag_b: int) -> dict:
    """`r1`/`r2` (opc_read) alimentando `sv1` (`soft_sensor_pls`, 2 entradas)."""
    no_sv = {
        "id": "sv1",
        "type": "soft_sensor_pls",
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": 3, "n_inputs": 2, "output_eu": "%"},
    }
    return {
        "nodes": [_no_opc("r1", "opc_read", 1, tag_a), _no_opc("r2", "opc_read", 2, tag_b), no_sv],
        "edges": [
            {
                "id": f"e{i}",
                "source": f"r{i}",
                "sourceHandle": "out",
                "target": "sv1",
                "targetHandle": f"IN{i}",
            }
            for i in (1, 2)
        ],
    }


async def _cenario_sensor_virtual(client, headers, db_session, nome: str) -> dict:
    pid = await _projeto(client, headers, nome)
    gw = await _conexao(client, headers, pid, "gw1")
    tag_a = await _tag(client, headers, gw, "TT-A")
    tag_b = await _tag(client, headers, gw, "TT-B")
    flow_id = await _flow_com_grafo(
        client, headers, pid, "Malha", _grafo_sensor_virtual(tag_a, tag_b)
    )
    return {"pid": pid, "flow_id": flow_id, "tags": [tag_a, tag_b]}


async def _modelo(db_session, pid: int, nome: str, input_tag_ids: list[int]) -> tuple:
    meta, blob = synthetic.pls([1.0, 2.0], 0.5)
    modelo = SoftSensorModel(
        project_id=pid,
        name=nome,
        method="pls",
        period_s=meta.period_s,
        n_inputs=2,
        input_tag_ids=input_tag_ids,
        meta=meta.model_dump(mode="json"),
        weights=blob,
        created_by="user:1",
    )
    db_session.add(modelo)
    await db_session.commit()
    return modelo.id, blob


async def _vincular(db_session, flow_id: int, **colunas) -> None:
    db_session.add(
        SoftSensorBinding(flow_id=flow_id, block_id="sv1", updated_by="user:1", **colunas)
    )
    await db_session.commit()


async def test_export_leva_o_modelo_vinculado_e_o_vinculo(client, admin_headers, db_session):
    c = await _cenario_sensor_virtual(client, admin_headers, db_session, "ComSensor")
    modelo_id, blob = await _modelo(db_session, c["pid"], "pls-1", c["tags"])
    await _vincular(db_session, c["flow_id"], desired_model_id=modelo_id)

    r = await client.get(f"/api/projects/{c['pid']}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    (modelo,) = body["soft_sensor_models"]
    assert (modelo["name"], modelo["method"], modelo["n_inputs"]) == ("pls-1", "pls", 2)
    assert modelo["period_s"] == 1.0
    assert modelo["meta"]["method"] == "pls"
    assert base64.b64decode(modelo["weights_b64"]) == blob
    assert modelo["input_tags"] == [
        {"connection": "gw1", "tag": "TT-A"},
        {"connection": "gw1", "tag": "TT-B"},
    ]
    assert body["soft_sensor_bindings"] == [{"flow": "Malha", "block_id": "sv1", "model": "pls-1"}]
    assert list(_chaves_proibidas(body)) == []


async def test_export_leva_o_modelo_desejado_e_nao_o_ativo(client, admin_headers, db_session):
    c = await _cenario_sensor_virtual(client, admin_headers, db_session, "DesejadoXAtivo")
    ativo, _ = await _modelo(db_session, c["pid"], "ativo", [])
    desejado, _ = await _modelo(db_session, c["pid"], "desejado", [])
    await _vincular(db_session, c["flow_id"], desired_model_id=desejado, active_model_id=ativo)

    r = await client.get(f"/api/projects/{c['pid']}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [m["name"] for m in body["soft_sensor_models"]] == ["desejado"]
    assert [b["model"] for b in body["soft_sensor_bindings"]] == ["desejado"]


async def test_export_nao_leva_modelo_sem_vinculo(client, admin_headers, db_session):
    c = await _cenario_sensor_virtual(client, admin_headers, db_session, "ModeloSolto")
    await _modelo(db_session, c["pid"], "solto", c["tags"])

    r = await client.get(f"/api/projects/{c['pid']}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["soft_sensor_models"] == []
    assert body["soft_sensor_bindings"] == []


async def test_export_entrada_sem_referencia_exportavel_vira_null(
    client, admin_headers, db_session
):
    """Tag calculada (sem conexão) e tag apagada (id órfão no array) viram `null` na posição."""
    c = await _cenario_sensor_virtual(client, admin_headers, db_session, "EntradaSemRef")
    calc = Tag(project_id=c["pid"], name="CALC-1", direction="r", data_type="float")
    db_session.add(calc)
    await db_session.flush()
    db_session.add(CalculatedTag(tag_id=calc.id, code="OUT = 1.0", period_seconds=5))
    await db_session.commit()
    modelo_id, _ = await _modelo(db_session, c["pid"], "pls-1", [c["tags"][0], calc.id, 999999])
    await _vincular(db_session, c["flow_id"], desired_model_id=modelo_id)

    r = await client.get(f"/api/projects/{c['pid']}/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    (modelo,) = r.json()["soft_sensor_models"]
    assert modelo["input_tags"] == [{"connection": "gw1", "tag": "TT-A"}, None, None]
