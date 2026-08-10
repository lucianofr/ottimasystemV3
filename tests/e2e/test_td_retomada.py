"""L2 do fechamento de tech debts — retomada automática após `comm_restored` (TD-005).

Cenários E2E-TD-04/05. A política fixada nesta entrega (ADR-025) é retomada COMPLETA: com
`desired_state == "running"`, uma queda de comunicação passa a ser transitória — o flow
redeploya sozinho e o MPC volta ao modo e aos setpoints de antes da queda, com rearme
bumpless. O `stop` do operador durante a queda continua sendo definitivo.

O ADR-017 (boot parado) não é tocado: o escopo aqui é queda de comunicação, não partida.

Estes cenários existem porque a campanha de 14 h precisou de um supervisor externo
(`planta_virtual/supervisor_mpc.py`) para sobreviver a duas quedas nos primeiros 40 min.
"""

import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from ottima_core.bus import KIND_COMM_FAILURE, KIND_COMM_RESTORED, KIND_FLOW_RESUMED

from .conftest import (
    AmbienteMpc,
    EventStream,
    OpcSim,
    armar_ate_remoto,
    armar_auto_com_retentativa,
    assinar_mpc_state,
    compose,
    deploy_flow,
    esperar_ate,
    evento_de,
    evento_mpc,
    grafo_mpc_tfs,
    operar_sp,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e

SP_ANTES_DA_QUEDA = 42.0
"""SP comandado antes da queda: valor distinto do default para a restauração ser inequívoca."""

TIMEOUT_QUEDA_S = 90.0
TIMEOUT_RELIGA_S = 240.0
"""Religar o opcsim e reconectar leva bem mais que derrubar — o `comm_restored` do worker só
sai depois de a sessão OPC-UA voltar a valer."""


def evento_de_flow(kind: str, flow_id: int) -> Callable[[dict[str, Any]], bool]:
    """`origin` de evento de flow é `flow:<id>` exato; o `kind` mora no payload."""

    def casa(evento: dict[str, Any]) -> bool:
        return (
            evento.get("origin") == f"flow:{flow_id}"
            and evento.get("payload", {}).get("kind") == kind
        )

    return casa


def estado_desejado(admin: httpx.Client, flow_id: int) -> str:
    resposta = admin.get(f"/api/flows/{flow_id}")
    assert resposta.status_code == 200, f"GET do flow: HTTP {resposta.status_code}"
    return str(resposta.json()["desired_state"])


def _armar_em_auto_com_sp(
    admin: httpx.Client, fluxo: Any, flow_id: int, block_id: str = "mpc1"
) -> dict[str, Any]:
    """REMOTO -> AUTO -> SP comandado; devolve o quadro que confirma o SP no ar."""
    armar_ate_remoto(admin, fluxo, flow_id, block_id)
    armar_auto_com_retentativa(admin, fluxo, flow_id, block_id)
    operar_sp(admin, flow_id, block_id, "cv_1", SP_ANTES_DA_QUEDA)
    return fluxo.esperar(
        lambda estado: estado["vars"]["cv_1"]["sp"] == pytest.approx(SP_ANTES_DA_QUEDA),
        timeout=30.0,
        descricao="SP comandado materializado antes da queda",
    )


def test_e2e_td_04_flow_retoma_sozinho_com_modos_e_sps_de_antes(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Callable[..., int],
    opcsim_client: OpcSim,
    eventos: EventStream,
    parar_opcsim: Callable[[], None],
) -> None:
    """E2E-TD-04: queda de comunicação e volta — o flow retoma sem comando manual nenhum."""
    resetar_atuador_mpc(opcsim_client)
    conn_id = ambiente_mpc.conn_id
    flow_id = criar_flow_mpc("td-04", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        antes = _armar_em_auto_com_sp(admin, fluxo, flow_id)
        modos_antes = antes["modes"]
        assert modos_antes == {"local_remote": "remote", "man_auto": "auto"}

        parar_opcsim()
        eventos.esperar(
            evento_de(KIND_COMM_FAILURE, conn_id),
            timeout=TIMEOUT_QUEDA_S,
            descricao="comm_failure após parar o opcsim",
        )
        eventos.esperar(
            evento_de_flow("flow_failed", flow_id),
            timeout=TIMEOUT_QUEDA_S,
            descricao="flow_failed derivado da queda de comunicação",
        )

        compose("start", "opcsim")
        eventos.esperar(
            evento_de(KIND_COMM_RESTORED, conn_id),
            timeout=TIMEOUT_RELIGA_S,
            descricao="comm_restored após religar o opcsim",
        )
        retomada = eventos.esperar(
            evento_de_flow(KIND_FLOW_RESUMED, flow_id),
            timeout=TIMEOUT_RELIGA_S,
            descricao="flow_resumed — retomada automática sem comando manual",
        )
        assert retomada["payload"].get("conn_id") == conn_id

        eventos.esperar(
            evento_mpc("mpc_mode_changed", flow_id, "mpc1"),
            timeout=TIMEOUT_RELIGA_S,
            descricao="auditoria da restauração de modo",
        )

        # O estado é o de antes da queda, não o de um bloco recém-nascido (que seria LOCAL/MAN).
        depois = fluxo.esperar(
            lambda estado: estado["modes"] == modos_antes,
            timeout=TIMEOUT_RELIGA_S,
            descricao="modos restaurados ao que eram antes da queda",
        )
        assert depois["modes"]["local_remote"] == "remote"
        assert depois["modes"]["man_auto"] == "auto"

        restaurado = fluxo.esperar(
            lambda estado: estado["vars"]["cv_1"]["sp"] == pytest.approx(SP_ANTES_DA_QUEDA),
            timeout=TIMEOUT_RELIGA_S,
            descricao="SP restaurado ao valor de antes da queda",
        )
        assert restaurado["vars"]["cv_1"]["sp"] == pytest.approx(SP_ANTES_DA_QUEDA)

    assert estado_desejado(admin, flow_id) == "running"


def test_e2e_td_05_stop_durante_a_queda_impede_a_retomada(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Callable[..., int],
    opcsim_client: OpcSim,
    eventos: EventStream,
    parar_opcsim: Callable[[], None],
) -> None:
    """E2E-TD-05: `POST /stop` durante a falha vence a retomada — a intenção do operador manda.

    Sem esta guarda, parar um flow durante uma queda de comunicação seria desfeito sozinho
    assim que a comunicação voltasse: o operador teria de parar duas vezes, sem saber por quê.
    """
    resetar_atuador_mpc(opcsim_client)
    conn_id = ambiente_mpc.conn_id
    flow_id = criar_flow_mpc("td-05", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        _armar_em_auto_com_sp(admin, fluxo, flow_id)

        parar_opcsim()
        eventos.esperar(
            evento_de(KIND_COMM_FAILURE, conn_id),
            timeout=TIMEOUT_QUEDA_S,
            descricao="comm_failure após parar o opcsim",
        )

        resposta = admin.post(f"/api/flows/{flow_id}/stop")
        assert resposta.status_code == 202, f"stop durante a falha: HTTP {resposta.status_code}"
        esperar_ate(
            lambda: estado_desejado(admin, flow_id) == "stopped",
            timeout=30.0,
            intervalo=1.0,
            descricao="desired_state gravado como stopped",
        )

        compose("start", "opcsim")
        eventos.esperar(
            evento_de(KIND_COMM_RESTORED, conn_id),
            timeout=TIMEOUT_RELIGA_S,
            descricao="comm_restored após religar o opcsim",
        )

    # Janela generosa DEPOIS do comm_restored: a retomada, se acontecesse, aconteceria aqui.
    time.sleep(15.0)
    assert estado_desejado(admin, flow_id) == "stopped", (
        "o flow parado pelo operador foi retomado sozinho — a intenção manual foi ignorada"
    )
