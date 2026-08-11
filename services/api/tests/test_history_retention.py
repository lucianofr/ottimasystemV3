"""Retenção configurável de histórico de variáveis (ADR-003 revisado): RBAC, limites 1-120,
reprogramação das 4 estruturas de variável (samples/samples_1m/mpc_samples/mpc_samples_1m) sem
tocar `events` (ADR-020), e liberação imediata de espaço via drop_chunks."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select, text

from ottima_core.models import samples_table

PATH = "/api/history-retention"

# Mesmo idioma do LEFT JOIN + COALESCE de deploy/smoke.sh (E2E-04) e
# packages/ottima-core/tests/test_timescale.py: a policy de um CAgg é registrada contra o
# nome interno da hypertable materializada, não contra o view_name.
_JOBS_DROP_AFTER = text(
    "SELECT COALESCE(ca.view_name, j.hypertable_name) AS nome,"
    "       (j.config->>'drop_after')::interval AS drop_after"
    "  FROM timescaledb_information.jobs j"
    "  LEFT JOIN timescaledb_information.continuous_aggregates ca"
    "    ON ca.materialization_hypertable_name = j.hypertable_name"
    " WHERE j.proc_name = 'policy_retention'"
)


async def _drop_after_por_estrutura(db_session) -> dict[str, timedelta]:
    rows = await db_session.execute(_JOBS_DROP_AFTER)
    return {r.nome: r.drop_after for r in rows}


async def test_get_default_30_dias_operador_le(client, operator_headers):
    r = await client.get(PATH, headers=operator_headers)
    assert r.status_code == 200
    assert r.json()["retention_days"] == 30


async def test_get_sem_token_401(client):
    assert (await client.get(PATH)).status_code == 401


async def test_put_exige_admin_403_para_operador(client, operator_headers):
    r = await client.put(PATH, json={"retention_days": 45}, headers=operator_headers)
    assert r.status_code == 403


async def test_put_valida_limites_1_a_120(client, admin_headers):
    fora = [
        await client.put(PATH, json={"retention_days": v}, headers=admin_headers)
        for v in (0, 121)
    ]
    assert [r.status_code for r in fora] == [422, 422]

    dentro = [
        await client.put(PATH, json={"retention_days": v}, headers=admin_headers)
        for v in (1, 120)
    ]
    assert [r.status_code for r in dentro] == [200, 200]


async def test_put_persiste_o_novo_valor(client, admin_headers):
    r = await client.put(PATH, json={"retention_days": 45}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["retention_days"] == 45
    assert (await client.get(PATH, headers=admin_headers)).json()["retention_days"] == 45


async def test_put_reprograma_as_4_estruturas_de_variavel_sem_tocar_events(
    client, admin_headers, db_session
):
    antes = await _drop_after_por_estrutura(db_session)
    assert antes["events"] == timedelta(days=30)  # ADR-020, fora de escopo desta rota

    r = await client.put(PATH, json={"retention_days": 45}, headers=admin_headers)
    assert r.status_code == 200

    depois = await _drop_after_por_estrutura(db_session)
    for estrutura in ("samples", "samples_1m", "mpc_samples", "mpc_samples_1m"):
        assert depois[estrutura] == timedelta(days=45), estrutura
    # events (ADR-020) continua com a política original: log de alarmes, não variável.
    assert depois["events"] == timedelta(days=30)


async def test_put_libera_espaco_imediatamente_via_drop_chunks(client, admin_headers, db_session):
    """Encolher a janela não pode esperar o próximo ciclo agendado do Timescale: o pedido é
    liberar espaço já ("dados mais antigos... devem ser descartados liberando espaço")."""
    antiga = datetime.now(UTC) - timedelta(days=200)
    await db_session.execute(
        insert(samples_table), [{"ts": antiga, "tag_id": 555, "value": 1.0, "quality": 0}]
    )
    await db_session.commit()
    presente_antes = await db_session.scalar(
        select(samples_table.c.value).where(samples_table.c.tag_id == 555)
    )
    assert presente_antes == 1.0

    r = await client.put(PATH, json={"retention_days": 30}, headers=admin_headers)
    assert r.status_code == 200

    restante = await db_session.scalar(
        select(samples_table.c.value).where(samples_table.c.tag_id == 555)
    )
    assert restante is None
