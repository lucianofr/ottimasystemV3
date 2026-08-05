"""Rotas `/api/operate` — modo, SP e MV do bloco MPC (spec F4 §6.1, plano F4b tarefa 3.1).

A API valida só forma e faixa contra o `graph_json` (Regra do Estado Publicado): não conhece
o modo vigente, então "flow existe" / "bloco é mpc" / faixa entram no mesmo canal 422 pt-BR
string única das demais reprovações de domínio (spec §6.1, brief da tarefa). Sucesso publica
`FlowCommand` em `flow.commands` e responde 202 sem emitir evento (§4.8) — o runtime audita.

O cenário (`_cenario`) sempre nasce com `admin_headers` (PUT do grafo exige admin, F3 §5.1);
as rotas `/operate` em si são exercitadas com `operator_headers` — o papel que a tarefa cobre.
"""

import json

import pytest
from redis.asyncio import Redis

from ottima_core.bus import CHANNEL_FLOW_COMMANDS

# ------------------------------------------------------------------------- fixtures locais


@pytest.fixture
async def comandos(redis_url):
    """Assinante de `flow.commands`, mesmo padrão de test_flow_commands.py (§2.2-7)."""
    sub = Redis.from_url(redis_url, decode_responses=True)
    pubsub = sub.pubsub()
    await pubsub.subscribe(CHANNEL_FLOW_COMMANDS)
    await pubsub.get_message(timeout=5)  # confirmação do SUBSCRIBE

    async def recebidos() -> list[dict]:
        msgs = []
        while (
            m := await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        ) is not None:
            msgs.append(json.loads(m["data"]))
        return msgs

    yield recebidos
    await pubsub.aclose()
    await sub.aclose()


# --------------------------------------------------------------- construtores do cenário MPC
# Mesmo esqueleto §2.1 de test_flows_mpc.py — duplicado aqui de propósito (cada mesa de teste
# é auto-contida no projeto; ver test_flow_commands.py vs. test_flows.py).


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


def _mv(suffix: str, **overrides) -> dict:
    node = {
        "id": f"mv_{suffix}",
        "name": f"MV {suffix}",
        "eu": "m3/h",
        "limits": {"min": 0.0, "max": 100.0},
        "du_max": 5.0,
        "initial_value": 0.0,
    }
    node.update(overrides)
    return node


def _cv(suffix: str, **overrides) -> dict:
    node = {
        "id": f"cv_{suffix}",
        "name": f"CV {suffix}",
        "eu": "C",
        "kind": "selfreg",
        "tss": 30.0,
        "weight": 1.0,
        "sp_limits": {"min": 80.0, "max": 120.0},
    }
    node.update(overrides)
    return node


def _selfreg_params(**overrides: float) -> dict:
    return {"K": 1.2, "tau1": 10.0, "tau2": 2.0, "theta": 15.0, **overrides}


def _mpc_data(*, mvs: list[dict], cvs: list[dict], name: str = "MPC teste") -> dict:
    """Matriz totalmente conectada (selfreg) — só CVs/MVs, sem Restrição/DV (foco do bloco)."""
    models = {
        cv["id"]: {mv["id"]: {"enabled": True, "params": _selfreg_params()} for mv in mvs}
        for cv in cvs
    }
    return {
        "name": name,
        "multiplier": 1,
        "variables": {"mvs": mvs, "cvs": cvs, "constraints": [], "dvs": []},
        "models": models,
    }


async def _grafo_mpc(client, headers, conn_id: int, data: dict, node_id: str = "m1") -> dict:
    """Grafo com um bloco `mpc` + um leitor OPC por CV (porta de entrada, decisão A-10)."""
    sources: list[dict] = []
    edges: list[dict] = []
    for index, cv in enumerate(data["variables"]["cvs"], start=1):
        tag_id = await _tag(client, headers, conn_id, f"IN-{index}", "r")
        source_id = f"r{index}"
        sources.append(_no(source_id, "opc_read", index, tag_id=tag_id))
        edges.append(_aresta(source_id, "out", node_id, cv["id"], id_=f"e{index}"))
    mpc = _no(node_id, "mpc", len(sources) + 1, **data)
    return {"nodes": [*sources, mpc], "edges": edges}


async def _salvar(client, headers, flow_id: int, graph: dict):
    r = await client.put(f"/api/flows/{flow_id}", json={"graph_json": graph}, headers=headers)
    assert r.status_code == 200, r.text
    return r


async def _id_do_usuario(client, headers) -> int:
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _cenario(client, admin_headers, nome: str) -> tuple[int, str]:
    """Flow salvo com um bloco `mpc` (`m1`: MV `mv_a`, CV `cv_a`) e um `opc_read` (`r1`)
    alimentando a porta da CV — `r1` também serve os testes de "bloco não é MPC".

    Sempre construído com `admin_headers`: criar projeto/flow e gravar o grafo exige admin
    (F1/F3 §6.1) — só o comando `/operate` em si é do papel operator.
    """
    pid = await _projeto(client, admin_headers, nome)
    cid = await _conexao(client, admin_headers, pid, f"plc-{nome}")
    flow = await _flow(client, admin_headers, pid, nome)
    data = _mpc_data(mvs=[_mv("a")], cvs=[_cv("a")])
    graph = await _grafo_mpc(client, admin_headers, cid, data)
    await _salvar(client, admin_headers, flow["id"], graph)
    return flow["id"], "m1"


def _mensagem(resposta) -> str:
    """422 de domínio: `detail` é sempre string única (padrão `api.ts`, ver test_flows.py)."""
    detail = resposta.json()["detail"]
    assert isinstance(detail, str), detail
    return detail


# --------------------------------------------------------------------------------- /mode


async def test_mode_operator_publica_comando_202(client, admin_headers, operator_headers, comandos):
    flow_id, block_id = await _cenario(client, admin_headers, "ModeOk")
    user_id = await _id_do_usuario(client, operator_headers)

    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mode",
        json={"axis": "local_remote", "value": "remote"},
        headers=operator_headers,
    )

    assert r.status_code == 202, r.text
    assert r.text == ""  # sem corpo — comando é intenção, quem confirma é o estado publicado
    publicados = await comandos()
    assert len(publicados) == 1
    assert publicados[0]["flow_id"] == flow_id
    assert publicados[0]["cmd"] == "mpc_mode"
    assert publicados[0]["args"] == {
        "block_id": block_id,
        "axis": "local_remote",
        "value": "remote",
    }
    assert publicados[0]["user"] == f"user:{user_id}"
    assert publicados[0]["ts"]


async def test_mode_anonimo_401(client, comandos):
    """Sem token, `require_operator` reprova antes de qualquer leitura no banco (spec §6.1)."""
    r = await client.post(
        "/api/operate/1/m1/mode",
        json={"axis": "local_remote", "value": "remote"},
    )
    assert r.status_code == 401
    assert await comandos() == []


async def test_mode_admin_tambem_pode(client, admin_headers, comandos):
    """`require_operator` aceita admin também (ADR-015: admin faz tudo)."""
    flow_id, block_id = await _cenario(client, admin_headers, "ModeAdmin")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mode",
        json={"axis": "man_auto", "value": "man"},
        headers=admin_headers,
    )
    assert r.status_code == 202, r.text
    assert len(await comandos()) == 1


async def test_mode_eixo_valor_incompativel_422(client, admin_headers, operator_headers, comandos):
    """`man`/`auto` não pertencem ao eixo `local_remote` (spec §4.8, ADR-010)."""
    flow_id, block_id = await _cenario(client, admin_headers, "ModeIncompat")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mode",
        json={"axis": "local_remote", "value": "man"},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert "man" in _mensagem(r)
    assert await comandos() == []


async def test_mode_axis_invalido_422(client, admin_headers, operator_headers, comandos):
    """Eixo fora do vocabulário `local_remote|man_auto` — 422 do schema (Literal), sem publicar."""
    flow_id, block_id = await _cenario(client, admin_headers, "AxisInvalido")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mode",
        json={"axis": "temperatura", "value": "remote"},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert await comandos() == []


async def test_mode_valor_invalido_422(client, admin_headers, operator_headers, comandos):
    """`value` fora do vocabulário `local|remote|man|auto` — 422 do schema, sem publicar."""
    flow_id, block_id = await _cenario(client, admin_headers, "ValueInvalido")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mode",
        json={"axis": "local_remote", "value": "ligado"},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert await comandos() == []


async def test_mode_flow_inexistente_422(client, operator_headers, comandos):
    r = await client.post(
        "/api/operate/999999/m1/mode",
        json={"axis": "local_remote", "value": "remote"},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert "Flow" in _mensagem(r)
    assert await comandos() == []


async def test_mode_bloco_inexistente_422(client, admin_headers, operator_headers, comandos):
    flow_id, _ = await _cenario(client, admin_headers, "ModeSemBloco")
    r = await client.post(
        f"/api/operate/{flow_id}/nope/mode",
        json={"axis": "local_remote", "value": "remote"},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert "nope" in _mensagem(r)
    assert await comandos() == []


async def test_mode_bloco_nao_e_mpc_422(client, admin_headers, operator_headers, comandos):
    flow_id, _ = await _cenario(client, admin_headers, "ModeNaoMpc")
    r = await client.post(
        f"/api/operate/{flow_id}/r1/mode",  # r1 é o opc_read gerado por _grafo_mpc
        json={"axis": "local_remote", "value": "remote"},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert "MPC" in _mensagem(r)
    assert await comandos() == []


async def test_mode_nao_emite_evento(client, admin_headers, operator_headers, comandos, eventos):
    flow_id, block_id = await _cenario(client, admin_headers, "SemEvento")
    await eventos()  # drena os eventos de CRUD do cenário (connection/flow/tag) antes do gate
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mode",
        json={"axis": "local_remote", "value": "remote"},
        headers=operator_headers,
    )
    assert r.status_code == 202
    assert len(await comandos()) == 1
    assert await eventos() == []


# --------------------------------------------------------------------------------- /sp


async def test_sp_operator_publica_comando_202(client, admin_headers, operator_headers, comandos):
    flow_id, block_id = await _cenario(client, admin_headers, "SpOk")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/sp",
        json={"var_id": "cv_a", "value": 100.0},
        headers=operator_headers,
    )
    assert r.status_code == 202, r.text
    publicados = await comandos()
    assert publicados[0]["cmd"] == "mpc_sp"
    assert publicados[0]["args"] == {"block_id": block_id, "var_id": "cv_a", "value": 100.0}


async def test_sp_fora_da_faixa_422(client, admin_headers, operator_headers, comandos):
    flow_id, block_id = await _cenario(client, admin_headers, "SpFaixa")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/sp",
        json={"var_id": "cv_a", "value": 200.0},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert "cv_a" in _mensagem(r)
    assert await comandos() == []


async def test_sp_var_nao_e_cv_422(client, admin_headers, operator_headers, comandos):
    """`mv_a` existe no bloco, mas não é CV — /sp só aceita CV (spec §6.1)."""
    flow_id, block_id = await _cenario(client, admin_headers, "SpCategoria")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/sp",
        json={"var_id": "mv_a", "value": 100.0},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert "mv_a" in _mensagem(r)
    assert await comandos() == []


async def test_sp_var_inexistente_422(client, admin_headers, operator_headers, comandos):
    flow_id, block_id = await _cenario(client, admin_headers, "SpInexistente")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/sp",
        json={"var_id": "cv_nope", "value": 100.0},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert "cv_nope" in _mensagem(r)
    assert await comandos() == []


# --------------------------------------------------------------------------------- /mv


async def test_mv_operator_publica_comando_202(client, admin_headers, operator_headers, comandos):
    flow_id, block_id = await _cenario(client, admin_headers, "MvOk")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mv",
        json={"var_id": "mv_a", "value": 50.0},
        headers=operator_headers,
    )
    assert r.status_code == 202, r.text
    publicados = await comandos()
    assert publicados[0]["cmd"] == "mpc_mv"
    assert publicados[0]["args"] == {"block_id": block_id, "var_id": "mv_a", "value": 50.0}


async def test_mv_fora_da_faixa_422(client, admin_headers, operator_headers, comandos):
    flow_id, block_id = await _cenario(client, admin_headers, "MvFaixa")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mv",
        json={"var_id": "mv_a", "value": 150.0},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert "mv_a" in _mensagem(r)
    assert await comandos() == []


async def test_mv_var_nao_e_mv_422(client, admin_headers, operator_headers, comandos):
    """`cv_a` existe no bloco, mas não é MV — /mv só aceita MV (spec §6.1)."""
    flow_id, block_id = await _cenario(client, admin_headers, "MvCategoria")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mv",
        json={"var_id": "cv_a", "value": 50.0},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert "cv_a" in _mensagem(r)
    assert await comandos() == []


async def test_mv_var_inexistente_422(client, admin_headers, operator_headers, comandos):
    flow_id, block_id = await _cenario(client, admin_headers, "MvInexistente")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mv",
        json={"var_id": "mv_nope", "value": 50.0},
        headers=operator_headers,
    )
    assert r.status_code == 422
    assert "mv_nope" in _mensagem(r)
    assert await comandos() == []
