"""Rotas `/api/operate` — modo, SP e MV do bloco MPC (spec F4 §6.1; emenda §1.3-3).

A API valida forma e faixa contra o `graph_json` (Regra do Estado Publicado): não conhece o
modo vigente. Flow inexistente é 404 (mesma constante de `flows.py`, decisão A-9); "bloco é
mpc" / faixa / categoria seguem no canal 422 pt-BR string única (spec §6.1). Sucesso publica
`FlowCommand` em `flow.commands` e responde 202 sem emitir evento (§4.8) — o runtime audita.

O cenário (`_cenario`) sempre nasce com `admin_headers` (PUT do grafo exige admin, F3 §5.1);
as rotas `/operate` em si são exercitadas com `operator_headers` — o papel que a tarefa cobre.
"""

import json
import logging

import pytest
from redis.asyncio import Redis

from ottima_core.bus import CHANNEL_FLOW_COMMANDS
from ottima_core.models import Flow

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


async def test_mode_flow_inexistente_404(client, operator_headers, comandos):
    r = await client.post(
        "/api/operate/999999/m1/mode",
        json={"axis": "local_remote", "value": "remote"},
        headers=operator_headers,
    )
    assert r.status_code == 404
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


async def test_sp_flow_inexistente_404(client, operator_headers, comandos):
    r = await client.post(
        "/api/operate/999999/m1/sp",
        json={"var_id": "cv_a", "value": 100.0},
        headers=operator_headers,
    )
    assert r.status_code == 404
    assert "Flow" in _mensagem(r)
    assert await comandos() == []


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


async def test_mv_flow_inexistente_404(client, operator_headers, comandos):
    r = await client.post(
        "/api/operate/999999/m1/mv",
        json={"var_id": "mv_a", "value": 50.0},
        headers=operator_headers,
    )
    assert r.status_code == 404
    assert "Flow" in _mensagem(r)
    assert await comandos() == []


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


# --------------------------------------------------------------------------------- /mpcs


async def test_mpcs_anonimo_401(client):
    """Sem token, `require_operator` reprova antes de qualquer leitura no banco (spec §6.1)."""
    r = await client.get("/api/operate/mpcs")
    assert r.status_code == 401


async def test_mpcs_sem_projeto_ativo_lista_vazia(client, admin_headers, operator_headers):
    """Existe bloco `mpc` no banco, mas nenhum projeto foi ativado (spec §4.1-4)."""
    await _cenario(client, admin_headers, "MpcsSemAtivo")

    r = await client.get("/api/operate/mpcs", headers=operator_headers)

    assert r.status_code == 200, r.text
    assert r.json() == []


async def test_mpcs_so_do_projeto_ativo(client, admin_headers, operator_headers):
    """Dois projetos com bloco `mpc`; só o ativo aparece na projeção (spec §4.1, decisão A-7)."""
    flow_a, block_a = await _cenario(client, admin_headers, "MpcsAtivo")
    await _cenario(client, admin_headers, "MpcsInativo")
    detalhe = await client.get(f"/api/flows/{flow_a}", headers=admin_headers)
    project_a = detalhe.json()["project_id"]
    r = await client.post(f"/api/projects/{project_a}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text

    r = await client.get("/api/operate/mpcs", headers=operator_headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert [item["flow_id"] for item in body] == [flow_a]
    assert body[0]["block_id"] == block_a


async def test_mpcs_projecao_verbatim_sem_pid_nem_models(client, admin_headers, operator_headers):
    """Response §4.1-1 verbatim: mvs/cvs/constraints/dvs projetados, sem `pid`/`models`/pesos/
    TSS/`initial_value` (§4.1-3) — a MV `mv_a` tem `pid` amarrado de propósito, para provar que
    ele nunca vaza."""
    project_id = await _projeto(client, admin_headers, "MpcsProjecao")
    conn_id = await _conexao(client, admin_headers, project_id, "plc-projecao")
    flow = await _flow(client, admin_headers, project_id, "MpcsProjecao")

    tag_in_cv = await _tag(client, admin_headers, conn_id, "IN-CV", "r")
    tag_in_co = await _tag(client, admin_headers, conn_id, "IN-CO", "r")
    tag_in_dv = await _tag(client, admin_headers, conn_id, "IN-DV", "r")
    tag_pid_w = await _tag(client, admin_headers, conn_id, "PID-W", "w")
    tag_pid_cmd = await _tag(client, admin_headers, conn_id, "PID-CMD", "w")
    tag_pid_rb = await _tag(client, admin_headers, conn_id, "PID-RB", "r")

    mv_a = _mv(
        "a",
        pid={
            "write_tag_id": tag_pid_w,
            "target_mode": "cas",
            "mode_cmd_tag_id": tag_pid_cmd,
            "readback_tag_id": tag_pid_rb,
            "mode_values": {"auto": 0, "target": 1},
        },
    )
    mv_b = _mv("b")
    cv_a = _cv("a")
    co_a = {
        "id": "co_a",
        "name": "Restrição A",
        "eu": "kPa",
        "kind": "selfreg",
        "tss": 20.0,
        "range": {"low": 0.0, "high": 10.0},
        "priority": 1,
    }
    dv_a = {"id": "dv_a", "name": "DV A", "eu": "C"}
    params = _selfreg_params()

    data = {
        "name": "MPC Projecao",
        "multiplier": 1,
        "variables": {"mvs": [mv_a, mv_b], "cvs": [cv_a], "constraints": [co_a], "dvs": [dv_a]},
        "models": {
            "cv_a": {
                "mv_a": {"enabled": True, "params": params},
                "mv_b": {"enabled": True, "params": params},
                "dv_a": {"enabled": True, "params": params},
            },
            "co_a": {"mv_a": {"enabled": True, "params": params}},
        },
    }
    graph = {
        "nodes": [
            _no("r1", "opc_read", 1, tag_id=tag_in_cv),
            _no("r2", "opc_read", 2, tag_id=tag_in_co),
            _no("r3", "opc_read", 3, tag_id=tag_in_dv),
            _no("m1", "mpc", 4, **data),
        ],
        "edges": [
            _aresta("r1", "out", "m1", "cv_a", id_="e1"),
            _aresta("r2", "out", "m1", "co_a", id_="e2"),
            _aresta("r3", "out", "m1", "dv_a", id_="e3"),
        ],
    }
    await _salvar(client, admin_headers, flow["id"], graph)
    r = await client.post(f"/api/projects/{project_id}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text

    r = await client.get("/api/operate/mpcs", headers=operator_headers)

    assert r.status_code == 200, r.text
    assert r.json() == [
        {
            "flow_id": flow["id"],
            "flow_name": "MpcsProjecao",
            "flow_ts_seconds": 1.0,
            "block_id": "m1",
            "name": "MPC Projecao",
            "multiplier": 1,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_a",
                        "name": "MV a",
                        "eu": "m3/h",
                        "limits": {"min": 0.0, "max": 100.0},
                        "du_max": 5.0,
                    },
                    {
                        "id": "mv_b",
                        "name": "MV b",
                        "eu": "m3/h",
                        "limits": {"min": 0.0, "max": 100.0},
                        "du_max": 5.0,
                    },
                ],
                "cvs": [
                    {
                        "id": "cv_a",
                        "name": "CV a",
                        "eu": "C",
                        "sp_limits": {"min": 80.0, "max": 120.0},
                    }
                ],
                "constraints": [
                    {
                        "id": "co_a",
                        "name": "Restrição A",
                        "eu": "kPa",
                        "range": {"low": 0.0, "high": 10.0},
                    }
                ],
                "dvs": [{"id": "dv_a", "name": "DV A", "eu": "C", "range": None}],
            },
        }
    ]


async def test_mpcs_projecao_de_dv_com_range(client, admin_headers, operator_headers):
    """DV com `range` explícito projeta `{low, high}`; DV sem `range` projeta `null` (spec
    §4.2, RF-702) — mesmo bloco, para provar que a ausência não vaza de uma DV para a outra."""
    project_id = await _projeto(client, admin_headers, "MpcsDvRange")
    conn_id = await _conexao(client, admin_headers, project_id, "plc-dv-range")
    flow = await _flow(client, admin_headers, project_id, "MpcsDvRange")

    tag_cv = await _tag(client, admin_headers, conn_id, "IN-CV", "r")
    tag_dv_sem = await _tag(client, admin_headers, conn_id, "IN-DV-SEM", "r")
    tag_dv_com = await _tag(client, admin_headers, conn_id, "IN-DV-COM", "r")

    mv_a = _mv("a")
    cv_a = _cv("a")
    dv_sem = {"id": "dv_sem", "name": "DV sem faixa", "eu": "C"}
    dv_com = {
        "id": "dv_com",
        "name": "DV com faixa",
        "eu": "C",
        "range": {"low": 0.0, "high": 50.0},
    }
    params = _selfreg_params()

    data = {
        "name": "MPC DV Range",
        "multiplier": 1,
        "variables": {"mvs": [mv_a], "cvs": [cv_a], "constraints": [], "dvs": [dv_sem, dv_com]},
        "models": {
            "cv_a": {
                "mv_a": {"enabled": True, "params": params},
                "dv_sem": {"enabled": True, "params": params},
                "dv_com": {"enabled": True, "params": params},
            }
        },
    }
    graph = {
        "nodes": [
            _no("r1", "opc_read", 1, tag_id=tag_cv),
            _no("r2", "opc_read", 2, tag_id=tag_dv_sem),
            _no("r3", "opc_read", 3, tag_id=tag_dv_com),
            _no("m1", "mpc", 4, **data),
        ],
        "edges": [
            _aresta("r1", "out", "m1", "cv_a", id_="e1"),
            _aresta("r2", "out", "m1", "dv_sem", id_="e2"),
            _aresta("r3", "out", "m1", "dv_com", id_="e3"),
        ],
    }
    await _salvar(client, admin_headers, flow["id"], graph)
    r = await client.post(f"/api/projects/{project_id}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text

    r = await client.get("/api/operate/mpcs", headers=operator_headers)

    assert r.status_code == 200, r.text
    dvs = r.json()[0]["variables"]["dvs"]
    assert dvs == [
        {"id": "dv_sem", "name": "DV sem faixa", "eu": "C", "range": None},
        {"id": "dv_com", "name": "DV com faixa", "eu": "C", "range": {"low": 0.0, "high": 50.0}},
    ]


async def test_mpcs_graph_invalido_pulado_com_log(
    client, admin_headers, operator_headers, db_session, caplog
):
    """`graph_json` que não parseia é pulado, nunca 5xx — o resto da projeção segue normal
    (spec §4.1-4, defesa em profundidade)."""
    project_id = await _projeto(client, admin_headers, "MpcsGraphInvalido")
    r = await client.post(f"/api/projects/{project_id}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text

    # Inserido direto no banco: só assim o `graph_json` fica estruturalmente inválido, já que
    # `PUT /api/flows/{id}` nunca grava um grafo que não passe por `parse_graph`/`validate_graph`.
    flow_corrompido = Flow(
        project_id=project_id,
        name="Corrompido",
        ts_seconds=1,
        graph_json={"nodes": "not-a-list", "edges": []},
    )
    db_session.add(flow_corrompido)
    await db_session.commit()
    await db_session.refresh(flow_corrompido)

    with caplog.at_level(logging.WARNING, logger="ottima_api.routers.operate"):
        r = await client.get("/api/operate/mpcs", headers=operator_headers)

    assert r.status_code == 200, r.text
    assert r.json() == []
    assert any(
        record.levelno == logging.WARNING and str(flow_corrompido.id) in record.getMessage()
        for record in caplog.records
    )


async def test_mpcs_bloco_mpc_invalido_pulado_com_log(
    client, admin_headers, operator_headers, db_session, caplog
):
    """`graph_json` estruturalmente válido (passa por `parse_graph`), mas o bloco `mpc` não
    tem `variables` — `MpcConfig.model_validate` rejeita com `pydantic.ValidationError`. Só é
    possível gravar assim inserindo direto no banco: `PUT /api/flows/{id}` roda
    `validate_graph` (que já tipa o bloco via `MpcConfig`) antes de gravar. Mesma postura de
    `test_mpcs_graph_invalido_pulado_com_log`, agora no nível do bloco, não do grafo inteiro."""
    project_id = await _projeto(client, admin_headers, "MpcsBlocoInvalido")
    r = await client.post(f"/api/projects/{project_id}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text

    graph = {
        "nodes": [
            {
                "id": "m1",
                "type": "mpc",
                "position": {"x": 0.0, "y": 0.0},
                "data": {
                    "exec_order": 1,
                    "name": "MPC Quebrado",
                    "multiplier": 1,
                    "models": {},
                    # 'variables' ausente de propósito: campo obrigatório de MpcConfig.
                },
            }
        ],
        "edges": [],
    }
    flow_corrompido = Flow(
        project_id=project_id, name="BlocoInvalido", ts_seconds=1, graph_json=graph
    )
    db_session.add(flow_corrompido)
    await db_session.commit()
    await db_session.refresh(flow_corrompido)

    with caplog.at_level(logging.WARNING, logger="ottima_api.routers.operate"):
        r = await client.get("/api/operate/mpcs", headers=operator_headers)

    assert r.status_code == 200, r.text
    assert r.json() == []
    assert any(
        record.levelno == logging.WARNING and str(flow_corrompido.id) in record.getMessage()
        for record in caplog.records
    )
