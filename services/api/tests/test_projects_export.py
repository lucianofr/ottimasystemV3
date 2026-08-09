"""Testes de `GET /api/projects/{project_id}/export` (spec F6 §3.1, RF-102 emendado).

Camada HTTP: monta o bundle a partir de dados reais no banco de teste (projeto, conexões,
tags, flow) e cobre RBAC, 404, `Content-Disposition`/slug, o evento de auditoria e a
ausência de segredos/ids em qualquer profundidade do corpo. A montagem pura do bundle
(ordenação, `tag_ref` nos 6 lugares, coerência interna) já está coberta em
`packages/ottima-core/tests/test_bundle.py`; aqui é o fio HTTP completo: banco -> query do
router -> `montar_bundle` -> resposta.
"""

from collections.abc import Iterator

from ottima_core.models import Flow, OpcConnection


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
    gw1 = await _conexao(client, admin_headers, pid, "gw1")
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
