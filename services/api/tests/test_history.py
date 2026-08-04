"""Histórico colunar (RF-802): switch raw/1m, shape uPlot, limites e papéis (ADR-015)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio import create_async_engine

from ottima_core.models import samples_table

BASE = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
TAG_1M = 990101  # fora do alcance dos testes que rodam em SAVEPOINT

# literais de propósito: o texto pt-BR é o contrato, importá-lo do router tornaria o teste
# tautológico (passaria mesmo se a mensagem mudasse)
ERRO_VAZIO = "tag_ids não pode ser vazio"
ERRO_NAO_INTEIRO = "tag_ids deve conter apenas inteiros separados por vírgula"

# O CAgg só materializa fora de transação; os limites vão bindados (nunca interpolados).
# CAST(...) em vez de `::`: o `::` cola no nome do bind e o text() deixa de reconhecê-lo.
_REFRESH = text(
    "CALL refresh_continuous_aggregate('samples_1m',"
    " CAST(:i AS timestamptz), CAST(:f AS timestamptz))"
)


def _amostra(tag_id: int, offset_s: int, value: float, quality: int = 0) -> dict[str, Any]:
    return {
        "ts": BASE + timedelta(seconds=offset_s),
        "tag_id": tag_id,
        "value": value,
        "quality": quality,
    }


async def _inserir(db_session, linhas: list[dict[str, Any]]) -> None:
    await db_session.execute(insert(samples_table), linhas)
    await db_session.commit()  # SAVEPOINT do conftest raiz — não vaza


async def _get(client, headers, tag_ids: str, start=None, end=None):
    params: dict[str, str] = {"tag_ids": tag_ids}
    if start is not None:
        params["start"] = start.isoformat()
    if end is not None:
        params["end"] = end.isoformat()
    return await client.get("/api/history", params=params, headers=headers)


def _instantes(serie: dict[str, Any]) -> list[datetime]:
    return [datetime.fromisoformat(t) for t in serie["t"]]


@pytest.fixture
async def seed_1m(migrated_database_url):
    """Semeia `samples` e materializa o CAgg fora de transação.

    `CALL refresh_continuous_aggregate` não roda dentro de transação e a `db_session` da F1
    vive num SAVEPOINT que sofre rollback — por isso o modo 1m usa conexão própria em
    AUTOCOMMIT. A limpeza é explícita: DELETE das linhas semeadas seguido de um novo refresh
    da mesma janela, que esvazia os buckets já materializados.
    """
    engine = create_async_engine(migrated_database_url)
    janelas: list[tuple[datetime, datetime]] = []

    async def _seed(linhas: list[dict[str, Any]], start: datetime, end: datetime) -> None:
        janelas.append((start, end))
        async with engine.connect() as conn:
            ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await ac.execute(insert(samples_table), linhas)
            await ac.execute(_REFRESH, {"i": start, "f": end})

    yield _seed

    async with engine.connect() as conn:
        ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await ac.execute(delete(samples_table).where(samples_table.c.tag_id == TAG_1M))
        for start, end in janelas:
            await ac.execute(_REFRESH, {"i": start, "f": end})
    await engine.dispose()


async def test_defaults_janela_de_uma_hora_ate_agora(client, operator_headers):
    antes = datetime.now(UTC)
    r = await _get(client, operator_headers, "1")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["mode"] == "raw"
    start, end = datetime.fromisoformat(corpo["start"]), datetime.fromisoformat(corpo["end"])
    assert end - start == timedelta(hours=1)
    assert antes <= end <= datetime.now(UTC)


async def test_switch_raw_para_1m_em_duas_horas(client, operator_headers):
    duas_h = await _get(client, operator_headers, "1", BASE, BASE + timedelta(hours=2))
    mais_um_min = await _get(
        client, operator_headers, "1", BASE, BASE + timedelta(hours=2, minutes=1)
    )
    assert duas_h.json()["mode"] == "raw"
    assert mais_um_min.json()["mode"] == "1m"


async def test_shape_colunar_raw_sem_v_min_v_max(client, operator_headers, db_session):
    await _inserir(db_session, [_amostra(1, s, float(s), 1) for s in (30, 10, 20)])
    r = await _get(client, operator_headers, "1", BASE, BASE + timedelta(hours=1))
    serie = r.json()["series"][0]
    assert _instantes(serie) == [BASE + timedelta(seconds=s) for s in (10, 20, 30)]
    assert serie["v"] == [10.0, 20.0, 30.0]
    assert serie["q"] == [1, 1, 1]
    assert "v_min" not in serie and "v_max" not in serie


async def test_shape_colunar_1m_com_avg_min_max_e_pior_qualidade(client, operator_headers, seed_1m):
    await seed_1m(
        [
            _amostra(TAG_1M, 5, 1.0),
            _amostra(TAG_1M, 25, 2.0),
            _amostra(TAG_1M, 45, 3.0, quality=2),
            _amostra(TAG_1M, 65, 10.0),
            _amostra(TAG_1M, 85, 20.0),
        ],
        BASE - timedelta(hours=1),
        BASE + timedelta(hours=3),
    )
    r = await _get(client, operator_headers, str(TAG_1M), BASE, BASE + timedelta(hours=3))
    corpo = r.json()
    assert corpo["mode"] == "1m"
    serie = corpo["series"][0]
    assert _instantes(serie) == [BASE, BASE + timedelta(minutes=1)]
    assert serie["v"] == [2.0, 15.0]
    assert serie["q"] == [2, 0]
    assert serie["v_min"] == [1.0, 10.0]
    assert serie["v_max"] == [3.0, 20.0]


async def test_uma_serie_por_tag_na_ordem_pedida_mesmo_sem_dado(
    client, operator_headers, db_session
):
    await _inserir(db_session, [_amostra(7, 0, 1.0), _amostra(9, 0, 2.0)])
    r = await _get(client, operator_headers, "9,8,7", BASE, BASE + timedelta(hours=1))
    series = r.json()["series"]
    assert [s["tag_id"] for s in series] == [9, 8, 7]
    assert series[1] == {"tag_id": 8, "t": [], "v": [], "q": []}
    assert series[0]["v"] == [2.0]


async def test_limite_de_seis_tags(client, operator_headers):
    ok = await _get(client, operator_headers, "1,2,3,4,5,6")
    assert ok.status_code == 200
    assert len(ok.json()["series"]) == 6
    excesso = await _get(client, operator_headers, "1,2,3,4,5,6,7")
    assert excesso.status_code == 422
    assert excesso.json()["detail"] == "no máximo 6 tags por consulta"


async def test_janela_maxima_de_31_dias(client, operator_headers):
    fim = BASE + timedelta(days=31)
    assert (await _get(client, operator_headers, "1", BASE, fim)).status_code == 200
    excesso = await _get(client, operator_headers, "1", BASE, BASE + timedelta(days=32))
    assert excesso.status_code == 422
    assert excesso.json()["detail"] == "janela não pode exceder 31 dias"


async def test_validacoes_de_janela_422_em_pt_br(client, operator_headers):
    invertido = await _get(client, operator_headers, "1", BASE + timedelta(hours=1), BASE)
    assert invertido.status_code == 422
    assert invertido.json()["detail"] == "start deve ser anterior a end"

    igual = await _get(client, operator_headers, "1", BASE, BASE)
    assert igual.status_code == 422
    assert igual.json()["detail"] == "start deve ser anterior a end"


@pytest.mark.parametrize(
    ("tag_ids", "detalhe"),
    [
        ("", ERRO_VAZIO),
        ("   ", ERRO_VAZIO),
        (",", ERRO_NAO_INTEIRO),
        ("1,", ERRO_NAO_INTEIRO),
        (",1", ERRO_NAO_INTEIRO),
        ("1,,2", ERRO_NAO_INTEIRO),
        ("-1", ERRO_NAO_INTEIRO),
        ("0", ERRO_NAO_INTEIRO),
        ("1.5", ERRO_NAO_INTEIRO),
        ("1,a", ERRO_NAO_INTEIRO),
        ("\u00b2", ERRO_NAO_INTEIRO),  # isdigit True, int() levanta ValueError
        ("1,\u2460", ERRO_NAO_INTEIRO),  # idem, dentro de uma lista válida
        ("9" * 25, ERRO_NAO_INTEIRO),  # decimal válido, mas estoura o BIGINT no bind
        # >4300 dígitos: int() do CPython levanta ValueError (sys.get_int_max_str_digits)
        ("9" * 5000, ERRO_NAO_INTEIRO),
        (str(2**63), ERRO_NAO_INTEIRO),  # primeiro valor acima do BIGINT
        (str(2**63 - 1), None),  # fronteira: maior BIGINT ainda é id válido
        ("\u0663", None),  # decimal árabe: isdecimal e int() o converte para 3
    ],
)
async def test_tag_ids_nunca_5xx_e_422_pt_br_quando_invalido(
    client, operator_headers, tag_ids, detalhe
):
    """`detalhe=None` marca entrada aceita; a regra dura vale para todos: nunca 5xx."""
    r = await _get(client, operator_headers, tag_ids)
    assert r.status_code < 500
    if detalhe is None:
        assert r.status_code == 200
    else:
        assert r.status_code == 422
        assert r.json()["detail"] == detalhe


async def test_ids_repetidos_sao_deduplicados(client, operator_headers):
    r = await _get(client, operator_headers, "1,1,2")
    assert [s["tag_id"] for s in r.json()["series"]] == [1, 2]


async def test_operador_le_e_sem_token_401(client, operator_headers):
    assert (await _get(client, operator_headers, "1")).status_code == 200
    assert (await _get(client, None, "1")).status_code == 401


async def test_filtro_de_janela_morde(client, operator_headers, db_session):
    await _inserir(db_session, [_amostra(3, s, float(s)) for s in (-600, 0, 600)])
    r = await _get(
        client, operator_headers, "3", BASE - timedelta(seconds=1), BASE + timedelta(seconds=1)
    )
    assert r.json()["series"][0]["v"] == [0.0]
