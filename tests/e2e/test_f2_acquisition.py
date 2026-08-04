"""Camada L2 da F2 (spec §11.2): aquisição, histórico, escrita e reconciliação.

Cenários E2E-F2-01, 02, 03, 08 e 09 contra o compose real.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import redis

from opcsim import NODE_MIRROR_FLOAT
from ottima_core.bus import KIND_COMM_FAILURE, KIND_CONNECTION_UPDATED, KIND_OPC_WRITE

from .conftest import (
    RUN_ID,
    Ambiente,
    EventStream,
    OpcSim,
    esperar_ate,
    esperar_conexao,
    evento_de,
    publicar_escrita,
    valor_unico,
)

pytestmark = pytest.mark.e2e


def _historico(
    admin: httpx.Client,
    tag_id: int,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    params: dict[str, str] = {"tag_ids": str(tag_id)}
    if start is not None:
        params["start"] = start.isoformat()
    if end is not None:
        params["end"] = end.isoformat()
    r = admin.get("/api/history", params=params)
    assert r.status_code == 200, f"/api/history falhou: HTTP {r.status_code} {r.text}"
    return r.json()


def _serie(admin: httpx.Client, tag_id: int, **janela: datetime | None) -> dict[str, Any]:
    corpo = _historico(admin, tag_id, **janela)
    assert len(corpo["series"]) == 1, "uma série por tag pedida, sempre"
    return corpo["series"][0]


def _pontos(admin: httpx.Client, tag_id: int, **janela: datetime | None) -> int:
    return len(_serie(admin, tag_id, **janela)["t"])


def _evento_na_api(
    admin: httpx.Client, *, origin: str, kind: str, conn_id: int | None = None
) -> dict[str, Any] | None:
    r = admin.get("/api/events", params={"origin": origin, "limit": 200})
    assert r.status_code == 200, f"/api/events falhou: HTTP {r.status_code} {r.text}"
    for evento in r.json():
        payload = evento["payload"]
        if payload.get("kind") != kind:
            continue
        if conn_id is not None and payload.get("conn_id") != conn_id:
            continue
        return evento
    return None


def test_e2e_f2_01_amostras_crescem_no_historico(
    admin: httpx.Client, projeto_com_conexao: Ambiente
) -> None:
    """RF-204/801: as amostras da senoide chegam ao trend e a série cresce no tempo."""
    tag = projeto_com_conexao.sine
    primeira = _pontos(admin, tag)
    assert primeira > 0, "nenhuma amostra da senoide chegou ao histórico"

    def cresceu() -> int | None:
        atual = _pontos(admin, tag)
        return atual if atual > primeira else None

    segunda = esperar_ate(
        cresceu, timeout=30.0, intervalo=2.0, descricao="segunda leitura do histórico"
    )
    assert segunda > primeira


def test_e2e_f2_02_downsampling_por_janela(
    admin: httpx.Client, projeto_com_conexao: Ambiente
) -> None:
    """RF-802: janela de 2 h serve bruto; acima disso, o contínuo de 1 min."""
    tag = projeto_com_conexao.sine
    fim = datetime.now(UTC)

    bruto = _historico(admin, tag, start=fim - timedelta(hours=2), end=fim)
    assert bruto["mode"] == "raw"
    serie_bruta = bruto["series"][0]
    assert "v_min" not in serie_bruta and "v_max" not in serie_bruta
    assert len(serie_bruta["t"]) == len(serie_bruta["v"]) == len(serie_bruta["q"])

    agregado = _historico(admin, tag, start=fim - timedelta(hours=3), end=fim)
    assert agregado["mode"] == "1m"
    # O CAgg materializa a cada minuto e pode estar vazio: o que se prova aqui é o
    # switch de modo e o shape colunar, não a quantidade de pontos.
    serie_1m = agregado["series"][0]
    assert serie_1m["tag_id"] == tag
    assert len(serie_1m["v_min"]) == len(serie_1m["v_max"]) == len(serie_1m["t"])


def test_e2e_f2_03_escrita_pelo_barramento(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    redis_bus: redis.Redis,
    opcsim_client: OpcSim,
) -> None:
    """RF-205: `opc.writes` chega ao opcsim (espelho R) e vira evento `opc_write` ok."""
    origem = f"e2e-{RUN_ID}-03"
    valor = valor_unico()
    publicar_escrita(
        redis_bus,
        conn_id=projeto_com_conexao.conn_id,
        tag_id=projeto_com_conexao.w_float,
        value=valor,
        source=origem,
    )

    esperar_ate(
        lambda: opcsim_client.read(NODE_MIRROR_FLOAT) == pytest.approx(valor),
        timeout=30.0,
        intervalo=0.5,
        descricao=f"espelho do opcsim assumir {valor}",
    )
    evento = esperar_ate(
        lambda: _evento_na_api(admin, origin=origem, kind=KIND_OPC_WRITE),
        timeout=30.0,
        intervalo=1.0,
        descricao=f"evento opc_write com origin={origem}",
    )
    assert evento["payload"]["status"] == "ok"
    assert evento["payload"]["conn_id"] == projeto_com_conexao.conn_id
    assert evento["payload"]["tag_id"] == projeto_com_conexao.w_float


def test_e2e_f2_08_heartbeat_da_tag_estatica_e_qualidade_em_falha(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    eventos: EventStream,
    congelar_watchdog: Callable[[bool], None],
) -> None:
    """§2.2-6: tag que nunca muda tem heartbeat; em falha, as amostras novas são `q=2`."""
    conn_id = projeto_com_conexao.conn_id
    tag = projeto_com_conexao.static
    esperar_conexao(conn_id)

    marco = datetime.now(UTC)

    def dois_pontos() -> list[str] | None:
        instantes = _serie(admin, tag, start=marco)["t"]
        return instantes if len(instantes) >= 2 else None

    # Heartbeat de 10 s (spec §2.2-6): em 45 s de orçamento devem sobrar pontos de folga.
    instantes = esperar_ate(
        dois_pontos, timeout=45.0, intervalo=5.0, descricao="heartbeat da tag estática"
    )
    momentos = [datetime.fromisoformat(t) for t in instantes]
    intervalos = [(b - a).total_seconds() for a, b in zip(momentos, momentos[1:], strict=False)]
    assert max(intervalos) < 60.0, f"heartbeat mais lento que 1 amostra/min: {intervalos}"

    congelar_watchdog(True)
    eventos.esperar(
        evento_de(KIND_COMM_FAILURE, conn_id),
        timeout=30.0,
        descricao="comm_failure após congelar o watchdog",
    )

    inicio_da_falha = datetime.now(UTC)

    def amostras_em_falha() -> list[int] | None:
        serie = _serie(admin, tag, start=inicio_da_falha)
        return serie["q"] if serie["q"] else None

    qualidades = esperar_ate(
        amostras_em_falha,
        timeout=45.0,
        intervalo=2.0,
        descricao="amostras publicadas com a conexão em falha",
    )
    assert set(qualidades) == {2}, f"amostra em falha deveria ser quality=2: {qualidades}"


def test_e2e_f2_09_edicao_da_conexao_reconciliada(
    admin: httpx.Client, projeto_com_conexao: Ambiente
) -> None:
    """§2.2-1/§7.2: PATCH audita `connection_updated` e o worker reconstrói a sessão."""
    conn_id = projeto_com_conexao.conn_id
    # O cenário anterior deixou a conexão voltando de uma falha induzida.
    antes = esperar_conexao(conn_id, timeout=120.0)
    sessao_anterior = antes["session_up_since"]

    r = admin.patch(f"/api/connections/{conn_id}", json={"watchdog_period_ms": 1200})
    assert r.status_code == 200, f"PATCH da conexão falhou: HTTP {r.status_code} {r.text}"
    assert r.json()["watchdog_period_ms"] == 1200

    esperar_ate(
        lambda: _evento_na_api(
            admin,
            origin=f"user:{admin.get('/api/auth/me').json()['id']}",
            kind=KIND_CONNECTION_UPDATED,
            conn_id=conn_id,
        ),
        timeout=30.0,
        intervalo=1.0,
        descricao="evento de auditoria connection_updated",
    )
    # A dica de reconciliação torna isto quase imediato; o poll de 10 s é o teto.
    esperar_conexao(conn_id, session_up_since_diferente_de=sessao_anterior, timeout=60.0)
