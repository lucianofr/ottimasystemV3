"""CRUD de flows (RF-302/306/307): rotas, papéis, a mesa de reprovações da §5.2 e o 409
do DELETE."""

import json

from ottima_core.models import Flow

GRAFO_VAZIO = {"nodes": [], "edges": []}
CAMPOS_LEVES = {"id", "project_id", "name", "ts_seconds", "desired_state", "updated_at"}
INF = float("inf")  # `json.dumps` emite `Infinity`, que o parser do corpo aceita


async def _projeto(client, headers, nome: str) -> int:
    r = await client.post("/api/projects", json={"name": nome}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _conexao(client, headers, project_id: int, nome: str = "plc") -> int:
    r = await client.post(
        "/api/connections",
        json={"project_id": project_id, "name": nome, "endpoint": "opc.tcp://x:4840"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _tag(client, headers, conn_id: int, nome: str, direcao: str, tipo: str = "float") -> int:
    r = await client.post(
        "/api/tags",
        json={
            "connection_id": conn_id,
            "name": nome,
            "node_id": f"ns=2;s={nome}",
            "direction": direcao,
            "data_type": tipo,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _flow(client, headers, project_id: int, nome: str = "Malha", ts: float = 1) -> dict:
    r = await client.post(
        "/api/flows",
        json={"project_id": project_id, "name": nome, "ts_seconds": ts},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _cenario(client, headers, nome: str) -> tuple[dict, int, int]:
    """Projeto com uma conexão, uma tag de leitura, uma de escrita e um flow vazio."""
    pid = await _projeto(client, headers, nome)
    cid = await _conexao(client, headers, pid)
    leitura = await _tag(client, headers, cid, f"FT-{nome}", "r")
    escrita = await _tag(client, headers, cid, f"FV-{nome}", "w")
    return await _flow(client, headers, pid), leitura, escrita


def _no(node_id: str, tipo: str, exec_order: int, **config) -> dict:
    return {
        "id": node_id,
        "type": tipo,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, **config},
    }


def _aresta(source: str, source_handle: str, target: str, target_handle: str, id_: str = "e1"):
    return {
        "id": id_,
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
    }


def _grafo_read_write(tag_r: int, tag_w: int, ordem_read: int = 1, ordem_write: int = 2) -> dict:
    """Read -> Write: o menor grafo que passa por toda a §5.2 sem reprovação."""
    return {
        "nodes": [
            _no("r1", "opc_read", ordem_read, tag_id=tag_r),
            _no("w1", "opc_write", ordem_write, tag_id=tag_w),
        ],
        "edges": [_aresta("r1", "out", "w1", "in")],
    }


async def _salvar(client, headers, flow_id: int, graph: dict, nome: str | None = None):
    corpo: dict = {"graph_json": graph}
    if nome is not None:
        corpo["name"] = nome
    return await client.put(f"/api/flows/{flow_id}", json=corpo, headers=headers)


def _mensagens(resposta) -> str:
    """Texto do 422 de domínio.

    O `detail` tem de ser **string**: o cliente descarta `detail` que não seja
    (`frontend/src/lib/api.ts`) e o engenheiro veria "Erro inesperado" no lugar da
    reprovação. Cada teste desta mesa passa por aqui, então a forma é asseverada em todos.
    """
    detail = resposta.json()["detail"]
    assert isinstance(detail, str), detail
    return detail


# ---------------------------------------------------------------------------------- CRUD


async def test_post_cria_com_grafo_vazio_e_get_le_o_detalhe(client, admin_headers):
    pid = await _projeto(client, admin_headers, "FlowsCria")
    r = await client.post(
        "/api/flows",
        json={"project_id": pid, "name": "Malha 1", "ts_seconds": 0.5},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    criado = r.json()
    assert criado["graph_json"] == GRAFO_VAZIO
    assert criado["ts_seconds"] == 0.5
    assert criado["desired_state"] == "stopped"

    detalhe = await client.get(f"/api/flows/{criado['id']}", headers=admin_headers)
    assert detalhe.status_code == 200
    assert detalhe.json() == criado


async def test_lista_e_leve_e_filtra_por_projeto(client, admin_headers, operator_headers):
    p1 = await _projeto(client, admin_headers, "FlowsP1")
    p2 = await _projeto(client, admin_headers, "FlowsP2")
    await _flow(client, admin_headers, p1, "Alfa")
    await _flow(client, admin_headers, p2, "Beta")

    r = await client.get(f"/api/flows?project_id={p1}", headers=operator_headers)
    assert r.status_code == 200
    lista = r.json()
    assert [f["name"] for f in lista] == ["Alfa"]
    assert "graph_json" not in lista[0]
    assert set(lista[0]) == CAMPOS_LEVES


async def test_nome_unico_por_projeto(client, admin_headers):
    p1 = await _projeto(client, admin_headers, "FlowsUniq1")
    p2 = await _projeto(client, admin_headers, "FlowsUniq2")
    await _flow(client, admin_headers, p1, "Mesmo nome")

    duplicado = await client.post(
        "/api/flows",
        json={"project_id": p1, "name": "Mesmo nome", "ts_seconds": 1},
        headers=admin_headers,
    )
    assert duplicado.status_code == 409
    assert duplicado.json()["detail"] == "Nome de flow já em uso neste projeto"

    outro_projeto = await client.post(
        "/api/flows",
        json={"project_id": p2, "name": "Mesmo nome", "ts_seconds": 1},
        headers=admin_headers,
    )
    assert outro_projeto.status_code == 201


async def test_ts_seconds_fora_da_lista_fixa_422(client, admin_headers):
    pid = await _projeto(client, admin_headers, "FlowsTs")
    for ts in (3, 0, 0.1, 61):
        r = await client.post(
            "/api/flows",
            json={"project_id": pid, "name": f"Ts {ts}", "ts_seconds": ts},
            headers=admin_headers,
        )
        assert r.status_code == 422, (ts, r.text)


async def test_post_com_projeto_inexistente_404(client, admin_headers):
    r = await client.post(
        "/api/flows",
        json={"project_id": 987654, "name": "Órfã", "ts_seconds": 1},
        headers=admin_headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Projeto não encontrado"


async def test_id_inexistente_404_e_id_fora_da_faixa_422(client, admin_headers):
    r = await client.get("/api/flows/987654", headers=admin_headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "Flow não encontrado"

    # BIGINT estourado precisa morrer na borda: chegar ao driver seria 500 (RNF de erro 4xx)
    gigante = 10**25
    for resposta in (
        await client.get(f"/api/flows/{gigante}", headers=admin_headers),
        await client.delete(f"/api/flows/{gigante}", headers=admin_headers),
        await client.get(f"/api/flows?project_id={gigante}", headers=admin_headers),
    ):
        assert resposta.status_code == 422, resposta.text


async def test_papeis_por_rota(client, admin_headers, operator_headers):
    flow, _, _ = await _cenario(client, admin_headers, "Papeis")

    assert (await client.get("/api/flows", headers=operator_headers)).status_code == 200
    assert (
        await client.get(f"/api/flows/{flow['id']}", headers=operator_headers)
    ).status_code == 200

    pid = flow["project_id"]
    proibidos = [
        await client.post(
            "/api/flows",
            json={"project_id": pid, "name": "Do operador", "ts_seconds": 1},
            headers=operator_headers,
        ),
        await _salvar(client, operator_headers, flow["id"], GRAFO_VAZIO),
        await client.delete(f"/api/flows/{flow['id']}", headers=operator_headers),
    ]
    for resposta in proibidos:
        assert resposta.status_code == 403, resposta.text

    assert (await client.get("/api/flows")).status_code == 401
    assert (
        await client.post("/api/flows", json={"project_id": pid, "name": "X", "ts_seconds": 1})
    ).status_code == 401


# ------------------------------------------------------------------- PUT e validação §5.2


async def test_put_grafo_valido_grava_e_nao_avisa(client, admin_headers):
    flow, leitura, escrita = await _cenario(client, admin_headers, "Valido")
    graph = _grafo_read_write(leitura, escrita)

    r = await _salvar(client, admin_headers, flow["id"], graph, nome="Renomeada")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["warnings"] == []
    assert corpo["flow"]["graph_json"] == graph
    assert corpo["flow"]["name"] == "Renomeada"

    relido = await client.get(f"/api/flows/{flow['id']}", headers=admin_headers)
    assert relido.json()["graph_json"] == graph


async def test_put_ciclo_422(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "Ciclo")
    script = {"n_inputs": 1, "n_outputs": 1, "code": "OUT1 = IN1"}
    graph = {
        "nodes": [_no("s1", "script", 1, **script), _no("s2", "script", 2, **script)],
        "edges": [
            _aresta("s1", "OUT1", "s2", "IN1", "e1"),
            _aresta("s2", "OUT1", "s1", "IN1", "e2"),
        ],
    }
    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422
    assert "ciclo detectado" in _mensagens(r)


async def test_put_exec_order_duplicado_e_com_buraco_422(client, admin_headers):
    flow, leitura, _ = await _cenario(client, admin_headers, "ExecOrder")

    duplicado = {
        "nodes": [
            _no("r1", "opc_read", 1, tag_id=leitura),
            _no("r2", "opc_read", 1, tag_id=leitura),
        ],
        "edges": [],
    }
    r = await _salvar(client, admin_headers, flow["id"], duplicado)
    assert r.status_code == 422
    assert "exec_order duplicado" in _mensagens(r)

    buraco = {
        "nodes": [
            _no("r1", "opc_read", 1, tag_id=leitura),
            _no("r2", "opc_read", 2, tag_id=leitura),
            _no("r3", "opc_read", 4, tag_id=leitura),
        ],
        "edges": [],
    }
    r = await _salvar(client, admin_headers, flow["id"], buraco)
    assert r.status_code == 422
    assert "contíguo de 1 a 3" in _mensagens(r)


async def test_put_tag_inexistente_422(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "TagFantasma")
    graph = {"nodes": [_no("r1", "opc_read", 1, tag_id=987654)], "edges": []}
    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422
    assert "não existe ou não pertence ao projeto do flow" in _mensagens(r)


async def test_put_tag_de_outro_projeto_422(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "Escopo")
    outro = await _projeto(client, admin_headers, "EscopoVizinho")
    conn_vizinha = await _conexao(client, admin_headers, outro, "plc-vizinho")
    tag_vizinha = await _tag(client, admin_headers, conn_vizinha, "FT-vizinha", "r")

    graph = {"nodes": [_no("r1", "opc_read", 1, tag_id=tag_vizinha)], "edges": []}
    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422
    assert f"a tag {tag_vizinha} não existe ou não pertence ao projeto do flow" in _mensagens(r)


async def test_put_tag_com_direcao_trocada_422(client, admin_headers):
    flow, leitura, _ = await _cenario(client, admin_headers, "Direcao")
    graph = {
        "nodes": [
            _no("r1", "opc_read", 1, tag_id=leitura),
            _no("w1", "opc_write", 2, tag_id=leitura),
        ],
        "edges": [_aresta("r1", "out", "w1", "in")],
    }
    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422
    assert "exige direção 'w'" in _mensagens(r)


async def test_put_no_mpc_422_citando_a_f4(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "Mpc")
    graph = {"nodes": [_no("m1", "mpc", 1)], "edges": []}
    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422
    assert "F4" in _mensagens(r)


async def test_put_entrada_obrigatoria_solta_422(client, admin_headers):
    flow, leitura, escrita = await _cenario(client, admin_headers, "Solta")
    graph = _grafo_read_write(leitura, escrita)
    graph["edges"] = []
    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422
    assert "a entrada 'in' é obrigatória e está desconectada" in _mensagens(r)


async def test_put_tipos_de_porta_incompativeis_422(client, admin_headers):
    pid = await _projeto(client, admin_headers, "Tipos")
    cid = await _conexao(client, admin_headers, pid)
    booleana = await _tag(client, admin_headers, cid, "DI-1", "r", tipo="bool")
    numerica = await _tag(client, admin_headers, cid, "AO-1", "w")
    flow = await _flow(client, admin_headers, pid)

    graph = _grafo_read_write(booleana, numerica)
    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422
    assert "booleana" in _mensagens(r) and "numérica" in _mensagens(r)


async def test_put_aresta_invertida_avisa_e_grava(client, admin_headers):
    flow, leitura, escrita = await _cenario(client, admin_headers, "Inversao")
    graph = _grafo_read_write(leitura, escrita, ordem_read=2, ordem_write=1)

    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["warnings"], corpo
    assert "varredura anterior" in corpo["warnings"][0]
    assert corpo["flow"]["graph_json"] == graph


async def test_put_grafo_malformado_422_sem_500(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "Malformado")
    for graph in ({"edges": []}, {"nodes": {}, "edges": []}, {}):
        r = await _salvar(client, admin_headers, flow["id"], graph)
        assert r.status_code == 422, r.text
        assert "nodes" in _mensagens(r)


async def test_put_junta_todas_as_reprovacoes_num_detail_so(client, admin_headers):
    """O `detail` string não pode custar defeitos: quem corrige precisa ver todos de uma vez.

    Três reprovações independentes (duas tags desconhecidas e uma entrada obrigatória solta)
    têm de aparecer no mesmo texto, separadas de forma legível.
    """
    flow, _, _ = await _cenario(client, admin_headers, "Junta")
    graph = {
        "nodes": [
            _no("r1", "opc_read", 1, tag_id=987654),
            _no("w1", "opc_write", 2, tag_id=987655),
        ],
        "edges": [],
    }
    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422
    texto = _mensagens(r)
    assert "a tag 987654 não existe" in texto
    assert "a tag 987655 não existe" in texto
    assert "a entrada 'in' é obrigatória e está desconectada" in texto
    # O separador entre reprovações não pode ser o "; " que as próprias mensagens usam
    assert texto.count(" | ") == 2


async def test_put_entradas_hostis_nao_viram_5xx(client, admin_headers):
    """Nenhuma rota de flows pode devolver 5xx para corpo de usuário (spec F1 §6.1)."""
    flow, leitura, _ = await _cenario(client, admin_headers, "Hostil")
    hostis = [
        [],
        "não é um objeto",
        # tag_id fora da faixa do BIGINT: não pode virar consulta com o valor cru
        {"nodes": [_no("r1", "opc_read", 1, tag_id=10**30)], "edges": []},
        # aresta apontando para nó que não existe
        {
            "nodes": [_no("r1", "opc_read", 1, tag_id=leitura)],
            "edges": [_aresta("r1", "out", "fantasma", "in")],
        },
    ]
    for graph in hostis:
        r = await _salvar(client, admin_headers, flow["id"], graph)
        assert r.status_code == 422, (graph, r.status_code, r.text)

    # `Infinity` é literal que o parser do corpo aceita mas o cliente httpx recusa serializar:
    # theta não-finito só chega por corpo cru, como chegaria de um cliente hostil.
    elemento = {"enabled": True, "kind": "iopdt", "params": {"Ki": 1.0, "theta": INF}}
    matriz = [[elemento, elemento], [elemento, elemento]]
    bruto = json.dumps({"graph_json": {"nodes": [_no("t1", "tfs", 1, matrix=matriz)], "edges": []}})
    r = await client.put(
        f"/api/flows/{flow['id']}",
        content=bruto,
        headers={**admin_headers, "content-type": "application/json"},
    )
    assert r.status_code == 422, r.text
    assert "finito" in _mensagens(r)


async def test_put_em_flow_inexistente_404(client, admin_headers):
    r = await _salvar(client, admin_headers, 987654, GRAFO_VAZIO)
    assert r.status_code == 404
    assert r.json()["detail"] == "Flow não encontrado"


async def test_put_reprovado_nao_grava(client, admin_headers, db_session):
    flow, leitura, escrita = await _cenario(client, admin_headers, "NaoGrava")
    valido = _grafo_read_write(leitura, escrita)
    assert (await _salvar(client, admin_headers, flow["id"], valido)).status_code == 200

    invalido = {"nodes": [_no("r1", "opc_read", 7, tag_id=leitura)], "edges": []}
    assert (
        await _salvar(client, admin_headers, flow["id"], invalido, "Nome novo")
    ).status_code == 422

    db_session.expire_all()  # força SELECT: o assert é sobre a linha no banco, não sobre o cache
    relido = (await client.get(f"/api/flows/{flow['id']}", headers=admin_headers)).json()
    assert relido["graph_json"] == valido
    assert relido["name"] == flow["name"]


# -------------------------------------------------------------------------------- DELETE


async def test_delete_flow_parado_204(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "Parado")
    assert (
        await client.delete(f"/api/flows/{flow['id']}", headers=admin_headers)
    ).status_code == 204

    lista = (
        await client.get(f"/api/flows?project_id={flow['project_id']}", headers=admin_headers)
    ).json()
    assert lista == []


async def test_delete_flow_rodando_409(client, admin_headers, db_session):
    flow, _, _ = await _cenario(client, admin_headers, "Rodando")
    # `desired_state` só muda por /deploy (tarefa 2.2); aqui o estado é montado no banco.
    linha = await db_session.get(Flow, flow["id"])
    linha.desired_state = "running"
    await db_session.commit()
    # `updated_at` tem onupdate SQL: sem o refresh o atributo fica expirado e a leitura
    # síncrona do response_model tentaria IO fora do greenlet.
    await db_session.refresh(linha)

    r = await client.delete(f"/api/flows/{flow['id']}", headers=admin_headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "Flow em execução; pare o flow antes de excluir"
    assert (await client.get(f"/api/flows/{flow['id']}", headers=admin_headers)).status_code == 200
