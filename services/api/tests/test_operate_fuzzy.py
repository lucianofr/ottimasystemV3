"""Rotas `/api/operate/fuzzy` — discovery e detalhe do bloco Fuzzy (ADR-030).

Mesmo esqueleto de `test_operate.py` para o cenário (`_cenario`): projeto/conexão/tag/flow com
um bloco `fuzzy` (`fz1`) e um `opc_read` (`r1`) alimentando a porta `IN1` — sempre com
`admin_headers` (PUT do grafo exige admin, F3 §5.1). Duplicado de propósito (cada mesa de
teste é auto-contida no projeto, ver test_operate.py).
"""

from ottima_core.contracts_export import FUZZY_DEFAULT_FLL
from ottima_core.flowgraph.introspect import N_PONTOS

# --------------------------------------------------------------- construtores do cenário Fuzzy


async def _projeto(client, headers, nome: str) -> int:
    r = await client.post("/api/projects", json={"name": nome}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _conexao(client, headers, project_id: int, nome: str) -> int:
    r = await client.post(
        "/api/connections",
        json={"project_id": project_id, "name": nome, "endpoint": "opc.tcp://x:4840"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _tag(client, headers, conn_id: int, nome: str, direcao: str) -> int:
    r = await client.post(
        "/api/tags",
        json={
            "connection_id": conn_id,
            "name": nome,
            "node_id": f"ns=2;s={nome}",
            "direction": direcao,
            "data_type": "float",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _flow(client, headers, project_id: int, nome: str, ts: float = 1) -> dict:
    r = await client.post(
        "/api/flows",
        json={"project_id": project_id, "name": nome, "ts_seconds": ts},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _no(node_id: str, tipo: str, exec_order: int, **config) -> dict:
    return {
        "id": node_id,
        "type": tipo,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, **config},
    }


def _aresta(source: str, source_handle: str, target: str, target_handle: str, id_: str) -> dict:
    return {
        "id": id_,
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
    }


async def _cenario(client, admin_headers, nome: str) -> tuple[int, str]:
    """Flow salvo com um bloco `fuzzy` (`fz1`, paleta default RF-541/ADR-029) e um `opc_read`
    (`r1`) alimentando `IN1` — a única entrada é obrigatória (RF-541). `r1` também serve o
    teste de "bloco não é Fuzzy" (mesmo esqueleto de test_operate.py)."""
    pid = await _projeto(client, admin_headers, nome)
    cid = await _conexao(client, admin_headers, pid, f"plc-{nome}")
    flow = await _flow(client, admin_headers, pid, nome)
    tag_id = await _tag(client, admin_headers, cid, "IN-1", "r")
    graph = {
        "nodes": [
            _no("r1", "opc_read", 1, tag_id=tag_id),
            _no("fz1", "fuzzy", 2, fll=FUZZY_DEFAULT_FLL, n_inputs=1, n_outputs=4),
        ],
        "edges": [_aresta("r1", "out", "fz1", "IN1", "e1")],
    }
    r = await client.put(
        f"/api/flows/{flow['id']}", json={"graph_json": graph}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    return flow["id"], "fz1"


# ------------------------------------------------------------------------------- /fuzzy


async def test_fuzzy_anonimo_401(client):
    """Sem token, `require_operator` reprova antes de qualquer leitura no banco (spec §6.1)."""
    r = await client.get("/api/operate/fuzzy")
    assert r.status_code == 401


async def test_fuzzy_sem_projeto_ativo_lista_vazia(client, admin_headers, operator_headers):
    """Existe bloco `fuzzy` no banco, mas nenhum projeto foi ativado (mesmo escopo de /mpcs,
    decisão A-7)."""
    await _cenario(client, admin_headers, "FuzzySemAtivo")

    r = await client.get("/api/operate/fuzzy", headers=operator_headers)

    assert r.status_code == 200, r.text
    assert r.json() == []


async def test_fuzzy_lista_nomes_de_porta_do_fll_default(client, admin_headers, operator_headers):
    """Discovery projeta `IN1`/`X` e `OUT1..OUT4` com os nomes das `OutputVariable` do FLL
    default (RF-541/ADR-029); curvas descartadas na listagem, `eu` ausente sem `output_eu`."""
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyLista")
    detalhe = await client.get(f"/api/flows/{flow_id}", headers=admin_headers)
    project_id = detalhe.json()["project_id"]
    r = await client.post(f"/api/projects/{project_id}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text

    r = await client.get("/api/operate/fuzzy", headers=operator_headers)

    assert r.status_code == 200, r.text
    assert r.json() == [
        {
            "flow_id": flow_id,
            "flow_name": "FuzzyLista",
            "block_id": block_id,
            "block_name": block_id,  # nó sem `label`: cai para o id do bloco
            "inputs": [{"port": "IN1", "name": "X"}],
            "outputs": [
                {"port": "OUT1", "name": "Ramps", "eu": None},
                {"port": "OUT2", "name": "Sigmoids", "eu": None},
                {"port": "OUT3", "name": "ZSShapes", "eu": None},
                {"port": "OUT4", "name": "Concaves", "eu": None},
            ],
        }
    ]


# ------------------------------------------------------------------------ /fuzzy/{flow}/{bloco}


async def test_fuzzy_detail_anonimo_401(client, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyDetalheAnonimo")
    r = await client.get(f"/api/operate/fuzzy/{flow_id}/{block_id}")
    assert r.status_code == 401


async def test_fuzzy_detail_introspeccao_completa(client, admin_headers, operator_headers):
    """Detalhe devolve a introspecção completa (ADR-030): curvas amostradas em `N_PONTOS`
    pontos, normas do motor e texto das regras — o frontend nunca parseia FLL (ADR-029)."""
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyDetalhe")

    r = await client.get(f"/api/operate/fuzzy/{flow_id}/{block_id}", headers=operator_headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["flow_id"] == flow_id
    assert body["flow_name"] == "FuzzyDetalhe"
    assert body["block_id"] == block_id
    assert body["block_name"] == block_id
    assert body["output_eu"] == {}

    intro = body["introspection"]
    assert intro["name"] == "tsukamoto"
    assert [v["port"] for v in intro["inputs"]] == ["IN1"]
    assert intro["inputs"][0]["name"] == "X"
    assert len(intro["inputs"][0]["x"]) == N_PONTOS
    assert [t["name"] for t in intro["inputs"][0]["terms"]] == ["small", "medium", "large"]
    assert all(len(t["y"]) == N_PONTOS for t in intro["inputs"][0]["terms"])

    assert [v["port"] for v in intro["outputs"]] == ["OUT1", "OUT2", "OUT3", "OUT4"]
    assert [v["name"] for v in intro["outputs"]] == [
        "Ramps",
        "Sigmoids",
        "ZSShapes",
        "Concaves",
    ]
    assert intro["outputs"][0]["defuzzifier"] == "WeightedAverage"

    assert len(intro["rule_blocks"]) == 1
    rule_block = intro["rule_blocks"][0]
    assert rule_block["activation"] == "General"
    assert len(rule_block["rules"]) == 3
    assert rule_block["rules"][0].startswith("if X is small then")


async def test_fuzzy_detail_flow_inexistente_404(client, operator_headers):
    r = await client.get("/api/operate/fuzzy/999999/fz1", headers=operator_headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "Flow não encontrado"


async def test_fuzzy_detail_bloco_inexistente_422(client, admin_headers, operator_headers):
    flow_id, _ = await _cenario(client, admin_headers, "FuzzyBlocoNope")
    r = await client.get(f"/api/operate/fuzzy/{flow_id}/nope", headers=operator_headers)
    assert r.status_code == 422
    assert "nope" in r.json()["detail"]


async def test_fuzzy_detail_bloco_nao_e_fuzzy_422(client, admin_headers, operator_headers):
    """`r1` existe no cenário, mas é `opc_read` — /fuzzy/{...} só aceita bloco `fuzzy`."""
    flow_id, _ = await _cenario(client, admin_headers, "FuzzyBlocoNaoFuzzy")
    r = await client.get(f"/api/operate/fuzzy/{flow_id}/r1", headers=operator_headers)
    assert r.status_code == 422
    assert "Fuzzy" in r.json()["detail"]
