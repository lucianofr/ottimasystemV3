"""Histórico colunar do bloco MPC (spec F5 §2.4; F5R-10/23): raw/1m, RBAC e limites.

Mesmo esqueleto de `test_operate.py` para o cenário (`_cenario`): projeto/conexão/tag/flow
com um bloco `mpc` (`m1`) e um `opc_read` (`r1`) alimentando a porta da CV — sempre com
`admin_headers` (PUT do grafo exige admin, F3 §5.1). Duplicado de propósito (cada mesa de
teste é auto-contida no projeto, ver test_operate.py).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio import create_async_engine

from ottima_core.models import mpc_samples_table

BASE = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)

# literais de propósito: o texto pt-BR é o contrato, importá-lo do router tornaria o teste
# tautológico (passaria mesmo se a mensagem mudasse) — mesmo padrão de test_history.py
ERRO_VAZIO = "var_ids não pode ser vazio"
ERRO_MALFORMADO = "var_ids deve conter valores não vazios separados por vírgula"

# O CAgg só materializa fora de transação; os limites vão bindados (nunca interpolados).
_REFRESH_MPC = text(
    "CALL refresh_continuous_aggregate('mpc_samples_1m',"
    " CAST(:i AS timestamptz), CAST(:f AS timestamptz))"
)


# --------------------------------------------------------------- construtores do cenário MPC


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


async def _flow(client, headers, project_id: int, nome: str) -> dict:
    r = await client.post(
        "/api/flows",
        json={"project_id": project_id, "name": nome, "ts_seconds": 1},
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


def _mpc_data() -> dict:
    """Bloco MPC mínimo válido (1 MV + 1 CV, sem Restrição/DV): só a forma importa aqui — o
    histórico não valida `var_id` contra o config do bloco (spec §2.4, "var_id desconhecido
    ⇒ série vazia"), então os `var_id` usados nas amostras dos testes não precisam bater com
    `mv_a`/`cv_a` daqui."""
    mv = {
        "id": "mv_a",
        "name": "MV a",
        "eu": "m3/h",
        "limits": {"min": 0.0, "max": 100.0},
        "max_rate": 5.0,
        "initial_value": 0.0,
    }
    cv = {
        "id": "cv_a",
        "name": "CV a",
        "eu": "C",
        "kind": "selfreg",
        "tss": 30.0,
        "weight": 1.0,
        "sp_limits": {"min": 80.0, "max": 120.0},
    }
    models = {
        "cv_a": {
            "mv_a": {
                "enabled": True,
                "params": {"K": 1.2, "tau1": 10.0, "tau2": 2.0, "theta": 15.0},
            }
        }
    }
    return {
        "name": "MPC teste",
        "multiplier": 1,
        "variables": {"mvs": [mv], "cvs": [cv], "constraints": [], "dvs": []},
        "models": models,
    }


async def _cenario(client, admin_headers, nome: str) -> tuple[int, str]:
    """Flow salvo com um bloco `mpc` (`m1`) e um `opc_read` (`r1`) alimentando a porta da CV
    — `r1` também serve o teste de "bloco não é MPC" (mesmo esqueleto de test_operate.py)."""
    pid = await _projeto(client, admin_headers, nome)
    cid = await _conexao(client, admin_headers, pid, f"plc-{nome}")
    flow = await _flow(client, admin_headers, pid, nome)
    tag_id = await _tag(client, admin_headers, cid, "IN-1", "r")
    graph = {
        "nodes": [_no("r1", "opc_read", 1, tag_id=tag_id), _no("m1", "mpc", 2, **_mpc_data())],
        "edges": [_aresta("r1", "out", "m1", "cv_a", "e1")],
    }
    r = await client.put(
        f"/api/flows/{flow['id']}", json={"graph_json": graph}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    return flow["id"], "m1"


# ---------------------------------------------------------------------------- dados/fixtures


def _amostra_mpc(
    flow_id: int, block_id: str, var_id: str, offset_s: int, v: float, sp: float | None, auto: bool
) -> dict[str, Any]:
    return {
        "ts": BASE + timedelta(seconds=offset_s),
        "flow_id": flow_id,
        "block_id": block_id,
        "var_id": var_id,
        "v": v,
        "sp": sp,
        "auto": auto,
    }


async def _inserir(db_session, linhas: list[dict[str, Any]]) -> None:
    await db_session.execute(insert(mpc_samples_table), linhas)
    await db_session.commit()  # SAVEPOINT do conftest raiz — não vaza


@pytest.fixture
async def seed_mpc_1m(migrated_database_url):
    """Semeia `mpc_samples` e materializa o CAgg fora de transação.

    `CALL refresh_continuous_aggregate` não roda dentro de transação e a `db_session` da F1
    vive num SAVEPOINT que sofre rollback — por isso o modo 1m usa conexão própria em
    AUTOCOMMIT (mesmo padrão de `test_history.py::seed_1m`). A limpeza é por `(flow_id,
    block_id)` real (não uma constante mágica): o flow nasce dentro do SAVEPOINT do teste e
    só existe ali, mas a tabela `mpc_samples` não tem FK — a chave usada na semeadura basta
    para a limpeza, sem depender do flow ainda existir.
    """
    engine = create_async_engine(migrated_database_url)
    chaves: set[tuple[int, str]] = set()
    janelas: list[tuple[datetime, datetime]] = []

    async def _seed(linhas: list[dict[str, Any]], start: datetime, end: datetime) -> None:
        janelas.append((start, end))
        chaves.update((linha["flow_id"], linha["block_id"]) for linha in linhas)
        async with engine.connect() as conn:
            ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await ac.execute(insert(mpc_samples_table), linhas)
            await ac.execute(_REFRESH_MPC, {"i": start, "f": end})

    yield _seed

    async with engine.connect() as conn:
        ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
        for flow_id, block_id in chaves:
            await ac.execute(
                delete(mpc_samples_table).where(
                    mpc_samples_table.c.flow_id == flow_id,
                    mpc_samples_table.c.block_id == block_id,
                )
            )
        for start, end in janelas:
            await ac.execute(_REFRESH_MPC, {"i": start, "f": end})
    await engine.dispose()


async def _get(client, headers, flow_id, block_id: str, var_ids: str, start=None, end=None):
    params: dict[str, str] = {
        "flow_id": str(flow_id),
        "block_id": block_id,
        "var_ids": var_ids,
    }
    if start is not None:
        params["start"] = start.isoformat()
    if end is not None:
        params["end"] = end.isoformat()
    return await client.get("/api/history/mpc", params=params, headers=headers)


def _instantes(serie: dict[str, Any]) -> list[datetime]:
    return [datetime.fromisoformat(t) for t in serie["t"]]


# ---------------------------------------------------------------------------------- testes


async def test_defaults_janela_de_uma_hora_ate_agora(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "MpcDefaults")
    antes = datetime.now(UTC)
    r = await _get(client, operator_headers, flow_id, block_id, "pv")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["mode"] == "raw"
    start, end = datetime.fromisoformat(corpo["start"]), datetime.fromisoformat(corpo["end"])
    assert end - start == timedelta(hours=1)
    assert antes <= end <= datetime.now(UTC)


async def test_switch_raw_para_1m_em_duas_horas(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "MpcBoundary")
    duas_h = await _get(
        client, operator_headers, flow_id, block_id, "pv", BASE, BASE + timedelta(hours=2)
    )
    mais_um_min = await _get(
        client,
        operator_headers,
        flow_id,
        block_id,
        "pv",
        BASE,
        BASE + timedelta(hours=2, minutes=1),
    )
    assert duas_h.json()["mode"] == "raw"
    assert mais_um_min.json()["mode"] == "1m"


async def test_shape_colunar_raw_com_sp_e_auto_sem_v_min_v_max(
    client, operator_headers, admin_headers, db_session
):
    flow_id, block_id = await _cenario(client, admin_headers, "MpcRawShape")
    await _inserir(
        db_session,
        [
            _amostra_mpc(flow_id, block_id, "pv", 30, 3.0, None, False),
            _amostra_mpc(flow_id, block_id, "pv", 10, 1.0, 50.0, True),
            _amostra_mpc(flow_id, block_id, "pv", 20, 2.0, 50.0, True),
        ],
    )
    r = await _get(
        client, operator_headers, flow_id, block_id, "pv", BASE, BASE + timedelta(hours=1)
    )
    serie = r.json()["series"][0]
    assert _instantes(serie) == [BASE + timedelta(seconds=s) for s in (10, 20, 30)]
    assert serie["v"] == [1.0, 2.0, 3.0]
    assert serie["sp"] == [50.0, 50.0, None]
    assert serie["auto"] == [True, True, False]
    assert "v_min" not in serie and "v_max" not in serie


async def test_shape_colunar_1m_com_avg_min_max_e_bool_or(
    client, operator_headers, admin_headers, seed_mpc_1m
):
    flow_id, block_id = await _cenario(client, admin_headers, "Mpc1mShape")
    await seed_mpc_1m(
        [
            _amostra_mpc(flow_id, block_id, "pv", 5, 1.0, 10.0, True),
            _amostra_mpc(flow_id, block_id, "pv", 25, 2.0, 10.0, False),
            _amostra_mpc(flow_id, block_id, "pv", 45, 3.0, 10.0, False),
            _amostra_mpc(flow_id, block_id, "pv", 65, 10.0, 20.0, False),
            _amostra_mpc(flow_id, block_id, "pv", 85, 20.0, 20.0, False),
        ],
        BASE - timedelta(hours=1),
        BASE + timedelta(hours=3),
    )
    r = await _get(
        client, operator_headers, flow_id, block_id, "pv", BASE, BASE + timedelta(hours=3)
    )
    corpo = r.json()
    assert corpo["mode"] == "1m"
    serie = corpo["series"][0]
    assert _instantes(serie) == [BASE, BASE + timedelta(minutes=1)]
    assert serie["v"] == [2.0, 15.0]
    assert serie["v_min"] == [1.0, 10.0]
    assert serie["v_max"] == [3.0, 20.0]
    assert serie["sp"] == [10.0, 20.0]
    assert serie["auto"] == [True, False]  # bool_or do bucket (spec §2.4)


async def test_uma_serie_por_var_id_na_ordem_pedida_mesmo_sem_dado(
    client, operator_headers, admin_headers, db_session
):
    flow_id, block_id = await _cenario(client, admin_headers, "MpcOrdem")
    await _inserir(
        db_session,
        [
            _amostra_mpc(flow_id, block_id, "cv_a", 0, 1.0, 100.0, True),
            _amostra_mpc(flow_id, block_id, "mv_a", 0, 2.0, None, False),
        ],
    )
    r = await _get(
        client,
        operator_headers,
        flow_id,
        block_id,
        "mv_a,dv_nope,cv_a",
        BASE,
        BASE + timedelta(hours=1),
    )
    series = r.json()["series"]
    assert [s["var_id"] for s in series] == ["mv_a", "dv_nope", "cv_a"]
    assert series[1] == {"var_id": "dv_nope", "t": [], "v": [], "sp": [], "auto": []}
    assert series[0]["v"] == [2.0]
    assert series[2]["v"] == [1.0]


async def test_var_ids_repetidos_sao_deduplicados(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "MpcDedup")
    r = await _get(client, operator_headers, flow_id, block_id, "pv,pv,sp")
    assert [s["var_id"] for s in r.json()["series"]] == ["pv", "sp"]


async def test_teto_de_14_variaveis(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "MpcTeto")
    var_ids_14 = ",".join(f"v{i}" for i in range(14))
    ok = await _get(client, operator_headers, flow_id, block_id, var_ids_14)
    assert ok.status_code == 200
    assert len(ok.json()["series"]) == 14
    excesso = await _get(client, operator_headers, flow_id, block_id, var_ids_14 + ",v14")
    assert excesso.status_code == 422
    assert excesso.json()["detail"] == "no máximo 14 variáveis por consulta"


async def test_janela_maxima_de_31_dias(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "MpcJanela")
    fim = BASE + timedelta(days=31)
    assert (
        await _get(client, operator_headers, flow_id, block_id, "pv", BASE, fim)
    ).status_code == 200
    excesso = await _get(
        client, operator_headers, flow_id, block_id, "pv", BASE, BASE + timedelta(days=32)
    )
    assert excesso.status_code == 422
    assert excesso.json()["detail"] == "janela não pode exceder 31 dias"


async def test_validacoes_de_janela_422_em_pt_br(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "MpcInvertido")
    invertido = await _get(
        client, operator_headers, flow_id, block_id, "pv", BASE + timedelta(hours=1), BASE
    )
    assert invertido.status_code == 422
    assert invertido.json()["detail"] == "start deve ser anterior a end"

    igual = await _get(client, operator_headers, flow_id, block_id, "pv", BASE, BASE)
    assert igual.status_code == 422
    assert igual.json()["detail"] == "start deve ser anterior a end"


@pytest.mark.parametrize(
    ("var_ids", "detalhe"),
    [
        ("", ERRO_VAZIO),
        ("   ", ERRO_VAZIO),
        (",", ERRO_MALFORMADO),
        ("pv,", ERRO_MALFORMADO),
        (",pv", ERRO_MALFORMADO),
        ("pv,,sp", ERRO_MALFORMADO),
    ],
)
async def test_var_ids_malformado_nunca_5xx_e_422_pt_br(client, operator_headers, var_ids, detalhe):
    """Checagem estrutural roda antes de tocar flow/banco (spec §2.4): flow inexistente aqui
    não interfere no 422 de forma — prova a ordem de validação, não só o texto."""
    r = await _get(client, operator_headers, 999_999, "x", var_ids)
    assert r.status_code == 422
    assert r.json()["detail"] == detalhe


async def test_flow_inexistente_404(client, operator_headers):
    r = await _get(client, operator_headers, 999_999, "m1", "pv")
    assert r.status_code == 404
    assert r.json()["detail"] == "Flow não encontrado"


async def test_block_id_inexistente_422(client, operator_headers, admin_headers):
    flow_id, _ = await _cenario(client, admin_headers, "MpcBlocoNope")
    r = await _get(client, operator_headers, flow_id, "nope", "pv")
    assert r.status_code == 422
    assert "nope" in r.json()["detail"]


async def test_block_id_nao_e_mpc_422(client, operator_headers, admin_headers):
    flow_id, _ = await _cenario(client, admin_headers, "MpcBlocoNaoMpc")
    r = await _get(client, operator_headers, flow_id, "r1", "pv")  # r1 é o opc_read do cenário
    assert r.status_code == 422
    assert "MPC" in r.json()["detail"]


async def test_operador_le_e_sem_token_401(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "MpcRbac")
    assert (await _get(client, operator_headers, flow_id, block_id, "pv")).status_code == 200
    assert (await _get(client, None, flow_id, block_id, "pv")).status_code == 401
