"""Bloco `mpc` nas rotas `/api/flows` (spec F4 §2.1/§2.2, plano F4a tarefa 3.1).

`validate_graph` já tipa e valida o config MPC por inteiro (tarefa 1.2) — a mesa completa
de 422/warnings da matriz, dos tetos e dos horizontes mora em
`packages/ottima-core/tests/test_flowgraph_mpc.py`. Este arquivo prova só a integração:
que as rotas existentes (nenhuma nova) devolvem 422 pt-BR string única, avisos no mesmo
canal do PUT (F3) e que o esqueleto normativo §2.1 sobrevive a um round-trip POST/PUT/GET.
"""


async def _projeto(client, headers, nome: str) -> int:
    r = await client.post("/api/projects", json={"name": nome}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _conexao(client, headers, project_id: int, nome: str = "mpc-plc") -> int:
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


async def _flow(client, headers, project_id: int, nome: str = "MalhaMpc", ts: float = 1) -> dict:
    r = await client.post(
        "/api/flows",
        json={"project_id": project_id, "name": nome, "ts_seconds": ts},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _cenario_mpc(client, headers, nome: str, *, ts: float = 1) -> tuple[dict, int]:
    """Projeto com uma conexão (tags dinâmicas do bloco `mpc` nascem dela) e um flow vazio."""
    pid = await _projeto(client, headers, nome)
    cid = await _conexao(client, headers, pid, f"plc-{nome}")
    flow = await _flow(client, headers, pid, ts=ts)
    return flow, cid


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


async def _salvar(client, headers, flow_id: int, graph: dict):
    return await client.put(f"/api/flows/{flow_id}", json={"graph_json": graph}, headers=headers)


def _mensagens(resposta) -> str:
    """Texto do 422 de domínio — sempre string (padrão `api.ts`, ver test_flows.py)."""
    detail = resposta.json()["detail"]
    assert isinstance(detail, str), detail
    return detail


# ---------------------------------------------------------------------------------------
# Construtores do esqueleto §2.1 (mesmo padrão de test_flowgraph_mpc.py, com tags reais)
# ---------------------------------------------------------------------------------------


def _pid(write: int, mode_cmd: int, readback: int, mode_read: int | None = None) -> dict:
    binding = {
        "write_tag_id": write,
        "target_mode": "rcas",
        "mode_cmd_tag_id": mode_cmd,
        "readback_tag_id": readback,
        "mode_values": {"auto": 1, "target": 3},
    }
    if mode_read is not None:
        binding["mode_read_tag_id"] = mode_read
    return binding


async def _pid_tags(client, headers, conn_id: int, *, with_mode_read: bool = True) -> dict:
    """Amarra um `pid` completo a 4 tags reais do projeto (write/mode_cmd = w; resto = r)."""
    write = await _tag(client, headers, conn_id, "PID-W", "w")
    mode_cmd = await _tag(client, headers, conn_id, "PID-MODE-CMD", "w")
    readback = await _tag(client, headers, conn_id, "PID-RB", "r")
    mode_read = await _tag(client, headers, conn_id, "PID-MODE-R", "r") if with_mode_read else None
    return _pid(write, mode_cmd, readback, mode_read)


def _mv(suffix: str, *, pid: dict | None = None, **overrides) -> dict:
    node = {
        "id": f"mv_{suffix}",
        "name": f"MV {suffix}",
        "eu": "m3/h",
        "limits": {"min": 0.0, "max": 100.0},
        "du_max": 5.0,
        "initial_value": 0.0,
    }
    if pid is not None:
        node["pid"] = pid
    node.update(overrides)
    return node


def _cv(
    suffix: str, *, kind: str = "selfreg", tss: float = 30.0, weight: float = 1.0, **overrides
) -> dict:
    node = {
        "id": f"cv_{suffix}",
        "name": f"CV {suffix}",
        "eu": "C",
        "kind": kind,
        "tss": tss,
        "weight": weight,
        "sp_limits": {"min": 80.0, "max": 120.0},
    }
    node.update(overrides)
    return node


def _dv(suffix: str) -> dict:
    return {"id": f"dv_{suffix}", "name": f"DV {suffix}", "eu": "m3/h"}


def _selfreg_params(**overrides: float) -> dict:
    return {"K": 1.2, "tau1": 10.0, "tau2": 2.0, "theta": 15.0, **overrides}


def _pair(*, enabled: bool = True, **param_overrides: float) -> dict:
    return {"enabled": enabled, "params": _selfreg_params(**param_overrides)}


def _auto_models(rows: list[dict], columns: list[dict]) -> dict:
    """Matriz totalmente conectada (selfreg) — isola os testes de caps/horizontes/pid."""
    return {row["id"]: {col["id"]: _pair() for col in columns} for row in rows}


def _mpc_data(
    *,
    mvs: list[dict] | None = None,
    cvs: list[dict] | None = None,
    constraints: list[dict] | None = None,
    dvs: list[dict] | None = None,
    models: dict | None = None,
    multiplier: int = 1,
    name: str = "MPC teste",
) -> dict:
    mvs = [_mv("a")] if mvs is None else mvs
    cvs = [_cv("a")] if cvs is None else cvs
    constraints = constraints or []
    dvs = dvs or []
    if models is None:
        models = _auto_models([*cvs, *constraints], [*mvs, *dvs])
    return {
        "name": name,
        "multiplier": multiplier,
        "variables": {"mvs": mvs, "cvs": cvs, "constraints": constraints, "dvs": dvs},
        "models": models,
    }


async def _grafo_mpc(client, headers, conn_id: int, data: dict, *, node_id: str = "m1") -> dict:
    """Grafo com um único bloco `mpc`; cada porta de entrada dinâmica (CV/Restrição/DV, decisão
    A-10) ganha um leitor OPC dedicado com tag real do projeto."""
    variables = data["variables"]
    input_ids = [v["id"] for v in (*variables["cvs"], *variables["constraints"], *variables["dvs"])]
    sources: list[dict] = []
    edges: list[dict] = []
    for index, input_id in enumerate(input_ids, start=1):
        tag_id = await _tag(client, headers, conn_id, f"IN-{index}", "r")
        source_id = f"r{index}"
        sources.append(_no(source_id, "opc_read", index, tag_id=tag_id))
        edges.append(_aresta(source_id, "out", node_id, input_id, id_=f"e{index}"))
    mpc = _no(node_id, "mpc", len(sources) + 1, **data)
    return {"nodes": [*sources, mpc], "edges": edges}


# ---------------------------------------------------------------------------------------
# 422s (spec §2.2)
# ---------------------------------------------------------------------------------------


async def test_put_matriz_incoerente_linha_so_com_dv_422(client, admin_headers):
    """CV movida só por DV é incontrolável (spec §2.2-3): precisa de ≥1 par com coluna MV."""
    flow, cid = await _cenario_mpc(client, admin_headers, "MpcMatriz")
    m, c, d = _mv("a"), _cv("a"), _dv("a")
    models = {c["id"]: {m["id"]: _pair(enabled=False), d["id"]: _pair()}}
    data = _mpc_data(mvs=[m], cvs=[c], dvs=[d], models=models)
    graph = await _grafo_mpc(client, admin_headers, cid, data)

    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422, r.text
    assert "cuja coluna é MV" in _mensagens(r)


async def test_put_np_acima_do_teto_422(client, admin_headers):
    """Np>120 reprova (spec §2.2-5, [NOVA])."""
    flow, cid = await _cenario_mpc(client, admin_headers, "MpcNp")
    data = _mpc_data(multiplier=1, cvs=[_cv("a", tss=121.0)])  # Ts_mpc=1 -> Np=121
    graph = await _grafo_mpc(client, admin_headers, cid, data)

    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422, r.text
    assert "aumente o multiplicador ou reduza o TSS" in _mensagens(r)


async def test_put_pid_tag_direcao_errada_422(client, admin_headers):
    """`write_tag_id` exige direção 'w' (spec §2.2-6) — aqui aponta pra tag de leitura."""
    flow, cid = await _cenario_mpc(client, admin_headers, "MpcPidDirecao")
    pid = await _pid_tags(client, admin_headers, cid)
    pid["write_tag_id"] = pid["readback_tag_id"]
    data = _mpc_data(mvs=[_mv("a", pid=pid)])
    graph = await _grafo_mpc(client, admin_headers, cid, data)

    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422, r.text
    assert "direção" in _mensagens(r)


async def test_put_pid_incompleto_422(client, admin_headers):
    """`pid` presente exige os campos obrigatórios do §2.1-3 — falta `mode_cmd_tag_id`."""
    flow, cid = await _cenario_mpc(client, admin_headers, "MpcPidIncompleto")
    pid = await _pid_tags(client, admin_headers, cid)
    del pid["mode_cmd_tag_id"]
    data = _mpc_data(mvs=[_mv("a", pid=pid)])
    graph = await _grafo_mpc(client, admin_headers, cid, data)

    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422, r.text
    texto = _mensagens(r)
    assert "F4 §2.1" in texto
    assert "mode_cmd_tag_id" in texto


async def test_put_teto_de_mvs_violado_422(client, admin_headers):
    """Teto de MVs é 1..4 (spec §2.2-2, [NOVA]) — 5 MVs reprova."""
    flow, cid = await _cenario_mpc(client, admin_headers, "MpcTeto")
    data = _mpc_data(mvs=[_mv(letra) for letra in "abcde"], cvs=[_cv("a")])
    graph = await _grafo_mpc(client, admin_headers, cid, data)

    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 422, r.text
    assert "teto do bloco é 1..4" in _mensagens(r)


# ---------------------------------------------------------------------------------------
# Warnings não-bloqueantes no PUT (mesmo canal do aviso de inversão da F3, spec §2.2-7)
# ---------------------------------------------------------------------------------------


async def test_put_np_acima_de_60_avisa_e_grava(client, admin_headers):
    flow, cid = await _cenario_mpc(client, admin_headers, "MpcNpWarn")
    data = _mpc_data(multiplier=1, cvs=[_cv("a", tss=61.0)])  # Ts_mpc=1 -> Np=61
    graph = await _grafo_mpc(client, admin_headers, cid, data)

    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert any("Np=61" in aviso and "acima de 60" in aviso for aviso in corpo["warnings"])
    assert corpo["flow"]["graph_json"] == graph


async def test_put_dimensao_acima_de_120_avisa_e_grava(client, admin_headers):
    flow, cid = await _cenario_mpc(client, admin_headers, "MpcDimWarn")
    m, c = _mv("a"), _cv("a")
    models = {c["id"]: {m["id"]: _pair(theta=118.0)}}  # dimensão = 2 + round(118/1) + 1 = 121
    data = _mpc_data(mvs=[m], cvs=[c], multiplier=1, models=models)
    graph = await _grafo_mpc(client, admin_headers, cid, data)

    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert any(
        "dimensão de estados" in aviso and "acima de 120" in aviso for aviso in corpo["warnings"]
    )
    assert corpo["flow"]["graph_json"] == graph


async def test_put_mpc_com_pid_e_watchdog_desabilitado_avisa_e_grava(client, admin_headers):
    """TD-004 (revisado, ADR-009): a MV com `pid` escreve pelas próprias tags do binding
    (sem depender de aresta) — com watchdog desabilitado no flow, `writes.py` (opc-worker)
    recusa toda escrita."""
    flow, cid = await _cenario_mpc(client, admin_headers, "MpcSemWatchdog")
    pid = await _pid_tags(client, admin_headers, cid)
    data = _mpc_data(mvs=[_mv("a", pid=pid)])
    graph = await _grafo_mpc(client, admin_headers, cid, data)

    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["warnings"] == [
        "Este flow escreve em planta mas o watchdog está desabilitado: as escritas serão "
        "recusadas (somente leitura de fato)."
    ]
    assert corpo["flow"]["graph_json"] == graph


# ---------------------------------------------------------------------------------------
# Round-trip do esqueleto normativo (spec F4 §2.1)
# ---------------------------------------------------------------------------------------


async def test_post_put_get_esqueleto_2_1_verbatim_round_trip(client, admin_headers):
    """POST cria, PUT grava o esqueleto §2.1 verbatim (tags e chaves de `models` reais no
    lugar dos placeholders de tag/`<linha_id>`/`<coluna_id>` do documento) e GET devolve
    exatamente o mesmo `graph_json`."""
    flow, cid = await _cenario_mpc(client, admin_headers, "MpcRoundtrip", ts=10)
    pid = await _pid_tags(client, admin_headers, cid)
    data = {
        "name": "MPC da coluna",
        "multiplier": 5,
        "variables": {
            "mvs": [
                {
                    "id": "mv_x7k2",
                    "name": "Vazão de refluxo",
                    "eu": "m3/h",
                    "limits": {"min": 0.0, "max": 100.0},
                    "du_max": 5.0,
                    "initial_value": 0.0,
                    "pid": pid,
                }
            ],
            "cvs": [
                {
                    "id": "cv_a1b2",
                    "name": "Temperatura de topo",
                    "eu": "C",
                    "kind": "selfreg",
                    "tss": 600.0,
                    "weight": 1.0,
                    "sp_limits": {"min": 80.0, "max": 120.0},
                }
            ],
            "constraints": [
                {
                    "id": "co_c3d4",
                    "name": "Nível do vaso",
                    "eu": "%",
                    "kind": "integrating",
                    "tss": 900.0,
                    "range": {"low": 20.0, "high": 80.0},
                    "priority": 1,
                }
            ],
            "dvs": [{"id": "dv_e5f6", "name": "Vazão de carga", "eu": "m3/h"}],
        },
        "models": {
            "cv_a1b2": {
                "mv_x7k2": {
                    "enabled": True,
                    "params": {"K": 1.2, "tau1": 120.0, "tau2": 30.0, "theta": 15.0},
                },
                "dv_e5f6": {
                    "enabled": True,
                    "params": {"K": 1.2, "tau1": 120.0, "tau2": 30.0, "theta": 15.0},
                },
            },
            "co_c3d4": {"mv_x7k2": {"enabled": True, "params": {"Ki": 0.5, "theta": 10.0}}},
        },
    }
    graph = await _grafo_mpc(client, admin_headers, cid, data)

    r = await _salvar(client, admin_headers, flow["id"], graph)
    assert r.status_code == 200, r.text
    assert r.json()["flow"]["graph_json"] == graph

    relido = await client.get(f"/api/flows/{flow['id']}", headers=admin_headers)
    assert relido.status_code == 200, relido.text
    assert relido.json()["graph_json"] == graph
