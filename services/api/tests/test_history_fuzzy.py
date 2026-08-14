"""Histórico colunar do bloco Fuzzy (ADR-030): raw/1m, RBAC, limites e formato de porta.

Mesmo esqueleto de `test_history_mpc.py` para o cenário (`_cenario`): projeto/conexão/tag/flow
com um bloco `fuzzy` (`fz1`) e um `opc_read` (`r1`) alimentando `IN1` — sempre com
`admin_headers` (PUT do grafo exige admin, F3 §5.1). Duplicado de propósito (cada mesa de
teste é auto-contida no projeto, ver test_history_mpc.py).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio import create_async_engine

from ottima_core.contracts_export import FUZZY_DEFAULT_FLL
from ottima_core.models import fuzzy_samples_table

BASE = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)

# literais de propósito: o texto pt-BR é o contrato, importá-lo do router tornaria o teste
# tautológico (passaria mesmo se a mensagem mudasse) — mesmo padrão de test_history_mpc.py
ERRO_VAZIO = "var_ids não pode ser vazio"
ERRO_MALFORMADO = "var_ids deve conter portas IN1..IN8/OUT1..OUT8 separadas por vírgula"

# O CAgg só materializa fora de transação; os limites vão bindados (nunca interpolados).
_REFRESH_FUZZY = text(
    "CALL refresh_continuous_aggregate('fuzzy_samples_1m',"
    " CAST(:i AS timestamptz), CAST(:f AS timestamptz))"
)


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


async def _cenario(client, admin_headers, nome: str) -> tuple[int, str]:
    """Flow salvo com um bloco `fuzzy` (`fz1`, paleta default RF-541/ADR-029) e um `opc_read`
    (`r1`) alimentando `IN1` — a única entrada é obrigatória. `r1` também serve o teste de
    "bloco não é Fuzzy" (mesmo esqueleto de test_history_mpc.py)."""
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


# ---------------------------------------------------------------------------- dados/fixtures


def _amostra_fuzzy(
    flow_id: int, block_id: str, var_id: str, offset_s: int, v: float
) -> dict[str, Any]:
    return {
        "ts": BASE + timedelta(seconds=offset_s),
        "flow_id": flow_id,
        "block_id": block_id,
        "var_id": var_id,
        "v": v,
    }


async def _inserir(db_session, linhas: list[dict[str, Any]]) -> None:
    await db_session.execute(insert(fuzzy_samples_table), linhas)
    await db_session.commit()  # SAVEPOINT do conftest raiz — não vaza


@pytest.fixture
async def seed_fuzzy_1m(migrated_database_url):
    """Semeia `fuzzy_samples` e materializa o CAgg fora de transação.

    `CALL refresh_continuous_aggregate` não roda dentro de transação e a `db_session` da F1
    vive num SAVEPOINT que sofre rollback — por isso o modo 1m usa conexão própria em
    AUTOCOMMIT (mesmo padrão de `test_history_mpc.py::seed_mpc_1m`).
    """
    engine = create_async_engine(migrated_database_url)
    chaves: set[tuple[int, str]] = set()
    janelas: list[tuple[datetime, datetime]] = []

    async def _seed(linhas: list[dict[str, Any]], start: datetime, end: datetime) -> None:
        janelas.append((start, end))
        chaves.update((linha["flow_id"], linha["block_id"]) for linha in linhas)
        async with engine.connect() as conn:
            ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await ac.execute(insert(fuzzy_samples_table), linhas)
            await ac.execute(_REFRESH_FUZZY, {"i": start, "f": end})

    yield _seed

    async with engine.connect() as conn:
        ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
        for flow_id, block_id in chaves:
            await ac.execute(
                delete(fuzzy_samples_table).where(
                    fuzzy_samples_table.c.flow_id == flow_id,
                    fuzzy_samples_table.c.block_id == block_id,
                )
            )
        for start, end in janelas:
            await ac.execute(_REFRESH_FUZZY, {"i": start, "f": end})
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
    return await client.get("/api/history/fuzzy", params=params, headers=headers)


# ---------------------------------------------------------------------------------- testes


async def test_defaults_janela_de_uma_hora_ate_agora(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyDefaults")
    antes = datetime.now(UTC)
    r = await _get(client, operator_headers, flow_id, block_id, "IN1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "raw"
    start = datetime.fromisoformat(body["start"])
    end = datetime.fromisoformat(body["end"])
    assert end - start == timedelta(hours=1)
    assert antes <= end <= datetime.now(UTC)


async def test_switch_raw_para_1m_em_duas_horas(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyBoundary")
    end = BASE
    start_raw = end - timedelta(hours=2)
    dentro_raw = await _get(client, operator_headers, flow_id, block_id, "IN1", start_raw, end)
    assert dentro_raw.json()["mode"] == "raw"
    mais_um_min = await _get(
        client, operator_headers, flow_id, block_id, "IN1", start_raw - timedelta(minutes=1), end
    )
    assert mais_um_min.json()["mode"] == "1m"


async def test_shape_colunar_raw_sem_v_min_v_max_nem_campos_de_mpc(
    client, operator_headers, admin_headers, db_session
):
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyRawShape")
    await _inserir(
        db_session,
        [
            _amostra_fuzzy(flow_id, block_id, "IN1", 0, 1.0),
            _amostra_fuzzy(flow_id, block_id, "IN1", 30, 2.0),
        ],
    )
    r = await _get(
        client,
        operator_headers,
        flow_id,
        block_id,
        "IN1",
        BASE - timedelta(minutes=1),
        BASE + timedelta(minutes=1),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "raw"
    serie = body["series"][0]
    assert serie["var_id"] == "IN1"
    assert serie["v"] == [1.0, 2.0]
    assert "v_min" not in serie and "v_max" not in serie
    assert "sp" not in serie and "auto" not in serie and "q" not in serie


async def test_shape_colunar_1m_com_avg_min_max(
    client, operator_headers, admin_headers, seed_fuzzy_1m
):
    flow_id, block_id = await _cenario(client, admin_headers, "Fuzzy1mShape")
    linhas = [
        _amostra_fuzzy(flow_id, block_id, "OUT1", 5, 1.0),
        _amostra_fuzzy(flow_id, block_id, "OUT1", 25, 3.0),
    ]
    await seed_fuzzy_1m(linhas, BASE - timedelta(hours=1), BASE + timedelta(hours=3))

    r = await _get(
        client, operator_headers, flow_id, block_id, "OUT1", BASE, BASE + timedelta(hours=3)
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "1m"
    serie = body["series"][0]
    assert serie["v"] == [2.0]  # avg(1.0, 3.0)
    assert serie["v_min"] == [1.0]
    assert serie["v_max"] == [3.0]


async def test_uma_serie_por_var_id_na_ordem_pedida_mesmo_sem_dado(
    client, operator_headers, admin_headers, db_session
):
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyOrdem")
    await _inserir(db_session, [_amostra_fuzzy(flow_id, block_id, "OUT1", 0, 1.0)])
    r = await _get(
        client,
        operator_headers,
        flow_id,
        block_id,
        "IN1,OUT2,OUT1",
        BASE - timedelta(minutes=1),
        BASE + timedelta(minutes=1),
    )
    assert r.status_code == 200, r.text
    series = r.json()["series"]
    assert [s["var_id"] for s in series] == ["IN1", "OUT2", "OUT1"]
    assert series[0]["v"] == []
    assert series[1]["v"] == []
    assert series[2]["v"] == [1.0]


async def test_var_ids_repetidos_sao_deduplicados(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyDedup")
    r = await _get(client, operator_headers, flow_id, block_id, "IN1,IN1,OUT1")
    assert [s["var_id"] for s in r.json()["series"]] == ["IN1", "OUT1"]


async def test_todas_as_16_portas_em_uma_unica_consulta(client, operator_headers, admin_headers):
    """`MAX_FUZZY_VARS = 16` é exatamente o total de portas possíveis (IN1..IN8/OUT1..OUT8,
    ADR-029) — o teto nunca é excedido por uma consulta com portas válidas, só confirmado no
    limite exato."""
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyTeto")
    todas = ",".join([f"IN{i}" for i in range(1, 9)] + [f"OUT{i}" for i in range(1, 9)])
    r = await _get(client, operator_headers, flow_id, block_id, todas)
    assert r.status_code == 200, r.text
    assert len(r.json()["series"]) == 16


async def test_janela_maxima_de_31_dias(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyJanela")
    dentro = await _get(
        client, operator_headers, flow_id, block_id, "IN1", BASE - timedelta(days=31), BASE
    )
    assert dentro.status_code == 200, dentro.text
    excesso = await _get(
        client, operator_headers, flow_id, block_id, "IN1", BASE - timedelta(days=32), BASE
    )
    assert excesso.status_code == 422
    assert excesso.json()["detail"] == "janela não pode exceder 31 dias"


async def test_validacoes_de_janela_422_em_pt_br(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyInvertido")
    igual = await _get(client, operator_headers, flow_id, block_id, "IN1", BASE, BASE)
    assert igual.status_code == 422
    assert igual.json()["detail"] == "start deve ser anterior a end"


@pytest.mark.parametrize(
    ("var_ids", "detalhe"),
    [
        ("", ERRO_VAZIO),
        ("   ", ERRO_VAZIO),
        (",", ERRO_MALFORMADO),
        ("IN1,", ERRO_MALFORMADO),
        (",IN1", ERRO_MALFORMADO),
        ("IN1,,OUT1", ERRO_MALFORMADO),
        ("pv", ERRO_MALFORMADO),  # var_id livre do MPC não vale para o Fuzzy (ADR-029)
        ("in1", ERRO_MALFORMADO),  # minúsculo não casa `^(IN|OUT)[1-8]$`
        ("IN9", ERRO_MALFORMADO),  # fora do intervalo 1..8
        ("OUT0", ERRO_MALFORMADO),  # fora do intervalo 1..8
    ],
)
async def test_var_ids_malformado_nunca_5xx_e_422_pt_br(client, operator_headers, var_ids, detalhe):
    """Checagem estrutural roda antes de tocar flow/banco: flow inexistente aqui não
    interfere no 422 de forma — prova a ordem de validação, não só o texto."""
    r = await _get(client, operator_headers, 999_999, "x", var_ids)
    assert r.status_code == 422
    assert r.json()["detail"] == detalhe


async def test_flow_inexistente_404(client, operator_headers):
    r = await _get(client, operator_headers, 999_999, "fz1", "IN1")
    assert r.status_code == 404
    assert r.json()["detail"] == "Flow não encontrado"


async def test_block_id_inexistente_422(client, operator_headers, admin_headers):
    flow_id, _ = await _cenario(client, admin_headers, "FuzzyBlocoNope")
    r = await _get(client, operator_headers, flow_id, "nope", "IN1")
    assert r.status_code == 422
    assert "nope" in r.json()["detail"]


async def test_block_id_nao_e_fuzzy_422(client, operator_headers, admin_headers):
    flow_id, _ = await _cenario(client, admin_headers, "FuzzyBlocoNaoFuzzy")
    r = await _get(client, operator_headers, flow_id, "r1", "IN1")  # r1 é o opc_read do cenário
    assert r.status_code == 422
    assert "Fuzzy" in r.json()["detail"]


async def test_operador_le_e_sem_token_401(client, operator_headers, admin_headers):
    flow_id, block_id = await _cenario(client, admin_headers, "FuzzyRbac")
    assert (await _get(client, operator_headers, flow_id, block_id, "IN1")).status_code == 200
    assert (await _get(client, None, flow_id, block_id, "IN1")).status_code == 401
