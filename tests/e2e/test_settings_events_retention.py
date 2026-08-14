"""E2E — retenção de `events` configurável (RF-803, ADR-020 revisado).

Prova contra o Timescale real do stack e2e: o PUT reprograma a retention policy da
hypertable `events` (consulta em `timescaledb_information.jobs`) e o `drop_chunks`
imediato remove um evento mais velho que a janela nova na mesma chamada. Restaura 30 dias
no fim — a suíte divide o stack com outros testes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from .conftest import _conf, compose

pytestmark = pytest.mark.e2e


def _psql(sql: str) -> str:
    """psql dentro do container do Timescale (a porta 5432 não é publicada no host e2e)."""
    senha = _conf("POSTGRES_PASSWORD", "")
    usuario = _conf("POSTGRES_USER", "ottima")
    banco = _conf("POSTGRES_DB", "ottima")
    url = f"postgresql://{usuario}:{senha}@localhost:5432/{banco}"
    return compose(
        "exec", "-T", "timescaledb", "psql", url, "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql
    )


def _drop_after_events() -> str:
    return _psql(
        "SELECT config->>'drop_after' FROM timescaledb_information.jobs "
        "WHERE hypertable_name = 'events' AND proc_name = 'policy_retention'"
    ).strip()


def test_put_reprograma_policy_e_descarta_chunks_antigos_na_hora(admin: httpx.Client) -> None:
    antigo = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    marcador = f"e2e-retencao-{datetime.now(UTC).timestamp()}"
    _psql(
        "INSERT INTO events (ts, severity, origin, message, payload) VALUES "
        f"('{antigo}', 'info', 'e2e', '{marcador}', '{{}}')"
    )

    try:
        r = admin.put("/api/history-retention", json={"events_retention_days": 3})
        assert r.status_code == 200, r.text

        # A policy de `events` agora é 3 dias…
        assert _drop_after_events() == "3 days"
        # …e o drop_chunks imediato já removeu o evento de 40 dias (sem esperar o scheduler).
        restantes = _psql(f"SELECT count(*) FROM events WHERE message = '{marcador}'").strip()
        assert restantes == "0"

        # GET reflete o valor novo.
        r_get = admin.get("/api/history-retention")
        assert r_get.status_code == 200
        assert r_get.json()["events_retention_days"] == 3
    finally:
        admin.put("/api/history-retention", json={"events_retention_days": 30})


def test_validacao_da_faixa_e_retencao_independente_das_amostras(admin: httpx.Client) -> None:
    """Fora de 1–90 ⇒ 422; PUT só de eventos não toca a retenção de variáveis."""
    antes = admin.get("/api/history-retention").json()
    r = admin.put("/api/history-retention", json={"events_retention_days": 91})
    assert r.status_code == 422
    r = admin.put("/api/history-retention", json={"events_retention_days": 0})
    assert r.status_code == 422

    r = admin.put("/api/history-retention", json={"events_retention_days": 45})
    assert r.status_code == 200, r.text
    depois = r.json()
    assert depois["events_retention_days"] == 45
    assert depois["retention_days"] == antes["retention_days"]
    assert _drop_after_events() == "45 days"
    admin.put("/api/history-retention", json={"events_retention_days": 30})
