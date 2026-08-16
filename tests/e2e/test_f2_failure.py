"""Camada L2 da F2 (spec §11.2): falha de comunicação, bloqueio de escrita e recuperação.

Cenários E2E-F2-04, 05 e 06 contra o compose real. O E2E-F2-04 é o aceite do PRD §8-F2:
o Δt entre congelar o rung do watchdog e o alarme é medido em tempo real.
"""

import time
from collections.abc import Callable

import pytest
import redis

from opcsim import NODE_MIRROR_FLOAT
from ottima_core.bus import KIND_COMM_FAILURE, KIND_COMM_RESTORED, KIND_WRITE_BLOCKED

from .conftest import (
    RUN_ID,
    Ambiente,
    EventStream,
    OpcSim,
    compose,
    esperar_ate,
    esperar_conexao,
    evento_de,
    publicar_escrita,
    revivar_watchdog_de_flow,
    valor_unico,
)

pytestmark = pytest.mark.e2e

# Aceite do PRD §8-F2: da detecção ao alarme, menos de 12 s.
ORCAMENTO_DO_ALARME_S = 12.0


def test_e2e_f2_04_watchdog_congelado_alarma_dentro_do_orcamento(
    projeto_com_conexao: Ambiente,
    eventos: EventStream,
    opcsim_client: OpcSim,
    redis_bus: redis.Redis,
    congelar_watchdog: Callable[[bool], None],
) -> None:
    """RF-206/207: `comm_failure(watchdog_timeout)` com Δt < 12 s; escrita em falha é bloqueada."""
    conn_id = projeto_com_conexao.conn_id
    esperar_conexao(conn_id)
    espelho_antes = opcsim_client.read(NODE_MIRROR_FLOAT)

    # A assinatura de `events` já está aberta (fixture): o Δt é medido do ato ao evento no
    # barramento, sem somar a latência de gravação do recorder.
    inicio = time.monotonic()
    congelar_watchdog(True)
    falha = eventos.esperar(
        evento_de(KIND_COMM_FAILURE, conn_id),
        timeout=30.0,
        descricao="comm_failure após congelar o rung do watchdog",
    )
    delta = time.monotonic() - inicio
    # O número medido é o aceite: fica no relatório da rodada, não só na mensagem de falha.
    print(f"\nE2E-F2-04: Δt do alarme = {delta:.2f}s (teto {ORCAMENTO_DO_ALARME_S:.0f}s)")

    assert falha["payload"]["reason"] == "watchdog_timeout"
    assert falha["severity"] == "alarm"
    assert delta < ORCAMENTO_DO_ALARME_S, (
        f"aceite do PRD §8-F2 violado: alarme em {delta:.2f}s (teto {ORCAMENTO_DO_ALARME_S}s)"
    )

    publicar_escrita(
        redis_bus,
        conn_id=conn_id,
        tag_id=projeto_com_conexao.w_float,
        flow_id=projeto_com_conexao.flow_id,
        value=valor_unico(),
        source=f"e2e-{RUN_ID}-04",
    )
    bloqueio = eventos.esperar(
        evento_de(KIND_WRITE_BLOCKED, conn_id),
        timeout=30.0,
        descricao="write_blocked com a conexão em falha",
    )
    assert bloqueio["payload"]["reason"] in {"session_down", "watchdog_dead"}
    assert opcsim_client.read(NODE_MIRROR_FLOAT) == pytest.approx(espelho_antes), (
        "o valor chegou ao opcsim apesar do gate fechado (ADR-009/010/017)"
    )


def test_e2e_f2_05_descongelar_restaura_e_reabre_o_gate(
    projeto_com_conexao: Ambiente,
    eventos: EventStream,
    opcsim_client: OpcSim,
    redis_bus: redis.Redis,
    congelar_watchdog: Callable[[bool], None],
    parar_opcsim: Callable[[], None],
) -> None:
    """§3.3/§3.4: com o watchdog do flow vivo, uma sessão nova depois de descongelar
    restaura a comunicação e reabre o gate de escrita sem ação manual.

    ADR-009 revisado: a task de watchdog de um flow se encerra sozinha na 1ª detecção de
    congelamento — só uma sessão nova volta a observar o bit (opc-worker `watchdog.py`),
    então a recuperação sempre passa por uma queda e religada real da sessão, nunca só por
    descongelar o rung. O E2E-F2-04, se rodou antes neste módulo, já deixou este watchdog
    morto; a chamada abaixo cobre os dois casos.
    """
    conn_id = projeto_com_conexao.conn_id
    flow_id = projeto_com_conexao.flow_id
    revivar_watchdog_de_flow(conn_id, flow_id, eventos=eventos, parar_opcsim=parar_opcsim)

    congelar_watchdog(True)
    eventos.esperar(
        evento_de(KIND_COMM_FAILURE, conn_id),
        timeout=30.0,
        descricao="comm_failure que abre o período de bloqueio",
    )

    congelar_watchdog(False)
    revivar_watchdog_de_flow(conn_id, flow_id, eventos=eventos, parar_opcsim=parar_opcsim)

    # Gate stateless (§3.4): a primeira alternância do watchdog já reabre a escrita.
    valor = valor_unico()
    publicar_escrita(
        redis_bus,
        conn_id=conn_id,
        tag_id=projeto_com_conexao.w_float,
        flow_id=flow_id,
        value=valor,
        source=f"e2e-{RUN_ID}-05",
    )
    esperar_ate(
        lambda: opcsim_client.read(NODE_MIRROR_FLOAT) == pytest.approx(valor),
        timeout=30.0,
        intervalo=0.5,
        descricao=f"espelho do opcsim assumir {valor} após a recuperação",
    )


def test_e2e_f2_06_queda_dura_do_opcsim(
    projeto_com_conexao: Ambiente,
    eventos: EventStream,
    parar_opcsim: Callable[[], None],
) -> None:
    """§2.2-2: servidor derrubado ⇒ `session_lost`; religado ⇒ `comm_restored`."""
    conn_id = projeto_com_conexao.conn_id
    esperar_conexao(conn_id, timeout=120.0)

    parar_opcsim()
    falha = eventos.esperar(
        evento_de(KIND_COMM_FAILURE, conn_id),
        timeout=60.0,
        descricao="comm_failure após parar o container do opcsim",
    )
    assert falha["payload"]["reason"] == "session_lost"

    compose("start", "opcsim")
    eventos.esperar(
        evento_de(KIND_COMM_RESTORED, conn_id),
        timeout=180.0,
        descricao="comm_restored após religar o opcsim",
    )
    esperar_conexao(conn_id, timeout=60.0)
