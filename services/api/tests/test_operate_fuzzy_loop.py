"""Rotas `/api/operate/loop*` para um bloco `fuzzy_loop` (SPEC_FUZZY secao 8).

Mesmo esqueleto auto-contido de `test_operate_fuzzy.py` (cada mesa de teste monta o proprio
projeto/conexao/tag/flow com `admin_headers`, porque o PUT do grafo exige admin).
"""

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL


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


async def _tag(client, headers, conn_id: int, nome: str) -> int:
    r = await client.post(
        "/api/tags",
        json={
            "connection_id": conn_id,
            "name": nome,
            "node_id": f"ns=2;s={nome}",
            "direction": "r",
            "data_type": "float",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _aresta(edge_id: str, source: str, target: str) -> dict:
    return {
        "id": edge_id,
        "source": source,
        "sourceHandle": "out",
        "target": target,
        "targetHandle": "in",
    }


async def _cenario(client, admin_headers, nome: str) -> tuple[int, str]:
    """Flow com `fl1` (fuzzy_loop, defaults da paleta), `pl1` (pid_loop) e `r1` alimentando PV.

    O projeto e ATIVADO: `GET /api/operate/loop` so projeta flows do projeto ativo.
    """
    pid = await _projeto(client, admin_headers, nome)
    cid = await _conexao(client, admin_headers, pid, f"plc-{nome}")
    r = await client.post(
        "/api/flows",
        json={"project_id": pid, "name": nome, "ts_seconds": 1},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    flow_id = r.json()["id"]
    tag_id = await _tag(client, admin_headers, cid, f"PV-{nome}")

    def no(node_id: str, tipo: str, ordem: int, **config) -> dict:
        return {
            "id": node_id,
            "type": tipo,
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": ordem, **config},
        }

    graph = {
        "nodes": [
            no("r1", "opc_read", 1, tag_id=tag_id),
            no("fl1", "fuzzy_loop", 2, sp_hi_lim=100.0, sp_lo_lim=0.0, ke=0.05, kde=0.0, ku=2.0),
            no("pl1", "pid_loop", 3, sp_hi_lim=100.0, sp_lo_lim=0.0, kc=1.0),
        ],
        "edges": [
            _aresta("e1", "r1", "fl1"),
            _aresta("e2", "r1", "pl1"),
        ],
    }
    r = await client.put(f"/api/flows/{flow_id}", json={"graph_json": graph}, headers=admin_headers)
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/projects/{pid}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text
    return flow_id, "fl1"


async def test_discovery_traz_o_tipo_de_cada_malha(client, admin_headers, operator_headers):
    flow_id, _ = await _cenario(client, admin_headers, "disc-fuzzy-loop")
    r = await client.get("/api/operate/loop", headers=operator_headers)
    assert r.status_code == 200, r.text
    por_id = {no["block_id"]: no["type"] for no in r.json() if no["flow_id"] == flow_id}
    assert por_id == {"fl1": "fuzzy_loop", "pl1": "pid_loop"}


async def test_detalhe_do_fuzzy_loop_traz_sintonia_do_kernel_fuzzy(
    client, admin_headers, operator_headers
):
    """A sintonia do faceplate e por TIPO: um `fuzzy_loop` nao tem KC/TI/TD."""
    flow_id, block_id = await _cenario(client, admin_headers, "det-fuzzy-loop")
    r = await client.get(f"/api/operate/loop/{flow_id}/{block_id}", headers=operator_headers)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["type"] == "fuzzy_loop"
    assert corpo["tuning"] == {
        "ke": 0.05,
        "kde": 0.0,
        "ku": 2.0,
        "tf_de": 1.0,
        "direct_acting": False,
    }


async def test_detalhe_do_pid_loop_segue_com_sintonia_isa(client, admin_headers, operator_headers):
    flow_id, _ = await _cenario(client, admin_headers, "det-pid-loop")
    r = await client.get(f"/api/operate/loop/{flow_id}/pl1", headers=operator_headers)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["type"] == "pid_loop"
    assert corpo["tuning"]["kc"] == 1.0


async def test_superficie_anonimo_401(client, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "sup-401")
    r = await client.get(f"/api/operate/loop/{flow_id}/{block_id}/surface")
    assert r.status_code == 401


async def test_superficie_amostrada_no_servidor(client, admin_headers, operator_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "sup-ok")
    r = await client.get(
        f"/api/operate/loop/{flow_id}/{block_id}/surface", headers=operator_headers
    )
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["resolution"] == 65
    valores = corpo["values"]
    assert len(valores) == 65 and all(len(linha) == 65 for linha in valores)
    # eixo 0 = de_n, eixo 1 = e_n: origem em repouso, sinal consistente nas bordas do erro
    assert abs(valores[32][32]) <= 0.02
    assert valores[32][64] > 0.0 > valores[32][0]


async def test_superficie_recusa_bloco_que_nao_e_fuzzy_loop(
    client, admin_headers, operator_headers
):
    flow_id, _ = await _cenario(client, admin_headers, "sup-nao-fuzzy")
    r = await client.get(f"/api/operate/loop/{flow_id}/pl1/surface", headers=operator_headers)
    assert r.status_code == 422
    assert "fuzzy_loop" in r.text


async def test_superficie_com_buraco_serializa_nan_como_null(
    client, admin_headers, operator_headers, db_session
):
    """JSON nao tem NaN (ADR-030): regiao sem regra viaja como `null`, nunca como 0.

    O `graph_json` e gravado DIRETO no banco de proposito: desde a fase K3 o portao NO_NAN
    reprova FLL com buraco no save (`PUT /api/flows`), e essa rede da rota continua sendo
    necessaria porque os portoes amostram em `lut_resolution` e a rota amostra em 65 — um
    buraco estreito pode aparecer so na malha mais fina.
    """
    from sqlalchemy import select

    from ottima_core.models import Flow

    flow_id, _ = await _cenario(client, admin_headers, "sup-buraco")
    com_buraco = FUZZY_LOOP_DEFAULT_FLL
    for regra in ("  rule: if e is PP then du is PP\n", "  rule: if e is PG then du is PG\n"):
        com_buraco = com_buraco.replace(regra, "")
    flow = await db_session.scalar(select(Flow).where(Flow.id == flow_id))
    grafo = dict(flow.graph_json)
    grafo["nodes"] = [
        {**no, "data": {**no["data"], "fll": com_buraco}} if no["id"] == "fl1" else no
        for no in grafo["nodes"]
    ]
    flow.graph_json = grafo
    await db_session.commit()

    r = await client.get(f"/api/operate/loop/{flow_id}/fl1/surface", headers=operator_headers)
    assert r.status_code == 200, r.text
    valores = r.json()["values"]
    assert valores[32][64] is None  # e_n = +1 sem regra
    assert valores[32][0] is not None  # o lado negativo segue coberto


# --------------------------------------------------------------- LUT content-addressed (K3)


async def _grafo_com_lut(client, admin_headers, nome: str, *, ku: float = 2.0) -> int:
    """Flow com um `fuzzy_loop` de `lut_enabled`, salvo — o save e quem gera a LUT."""
    pid = await _projeto(client, admin_headers, nome)
    cid = await _conexao(client, admin_headers, pid, f"plc-{nome}")
    r = await client.post(
        "/api/flows",
        json={"project_id": pid, "name": nome, "ts_seconds": 1},
        headers=admin_headers,
    )
    flow_id = r.json()["id"]
    tag_id = await _tag(client, admin_headers, cid, f"PV-{nome}")
    graph = {
        "nodes": [
            {
                "id": "r1",
                "type": "opc_read",
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": 1, "tag_id": tag_id},
            },
            {
                "id": "fl1",
                "type": "fuzzy_loop",
                "position": {"x": 0.0, "y": 0.0},
                "data": {
                    "exec_order": 2,
                    "sp_hi_lim": 100.0,
                    "sp_lo_lim": 0.0,
                    "ke": 0.05,
                    "ku": ku,
                    "lut_enabled": True,
                },
            },
        ],
        "edges": [_aresta("e1", "r1", "fl1")],
    }
    r = await client.put(f"/api/flows/{flow_id}", json={"graph_json": graph}, headers=admin_headers)
    assert r.status_code == 200, r.text
    return flow_id


async def test_save_persiste_a_lut_por_hash_do_fll(client, admin_headers, db_session):
    from sqlalchemy import select

    from ottima_core.models import FuzzySurfaceLut

    await _grafo_com_lut(client, admin_headers, "lut-grava")
    linhas = list(await db_session.scalars(select(FuzzySurfaceLut)))
    assert len(linhas) == 1
    linha = linhas[0]
    assert linha.resolution == 65
    assert len(linha.payload) == 65 * 65 * 4  # float32 C-order
    assert len(linha.fll_hash) == 64  # sha256 hex


async def test_lut_dedupa_entre_blocos_com_o_mesmo_fll(client, admin_headers, db_session):
    """Content-addressed (ADR-039 D11): mesmo `.fll` em flows diferentes = uma linha só."""
    from sqlalchemy import func, select

    from ottima_core.models import FuzzySurfaceLut

    await _grafo_com_lut(client, admin_headers, "lut-dedupe-a", ku=2.0)
    await _grafo_com_lut(client, admin_headers, "lut-dedupe-b", ku=9.0)  # sintonia difere
    total = await db_session.scalar(select(func.count()).select_from(FuzzySurfaceLut))
    assert total == 1


async def test_lut_nao_e_gerada_quando_desabilitada(client, admin_headers, db_session):
    from sqlalchemy import func, select

    from ottima_core.models import FuzzySurfaceLut

    await _cenario(client, admin_headers, "lut-off")  # lut_enabled fica no default (False)
    total = await db_session.scalar(select(func.count()).select_from(FuzzySurfaceLut))
    assert total == 0
