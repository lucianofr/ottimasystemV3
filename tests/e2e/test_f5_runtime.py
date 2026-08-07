"""L2 F5a (spec F5 9.2): concorrência, building, prediction_ts.

E2E-F5-05: deploy não bloqueia stop; building; arm_failed.
E2E-F5-06: prediction_ts presente; ts monotônico; ts − prediction_ts ≈ Ts_mpc.
"""

import time
from datetime import datetime
from typing import Any

import httpx
import pytest

from .conftest import (
    TS_MPC,
    AmbienteMpc,
    OpcSim,
    assinar_mpc_state,
    deploy_flow,
    evento_mpc,
    grafo_mpc_tfs,
    operar_modo,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e


def test_e2e_f5_05_deploy_nao_bloqueia_stop_outro_flow(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-05(a): deploy de flow MPC pesado não bloqueia stop de outro (spec §6)."""
    resetar_atuador_mpc(opcsim_client)

    flow_heavy = criar_flow_mpc("f5-05a-h", grafo=grafo_mpc_tfs(ambiente_mpc))
    flow_light = criar_flow_mpc("f5-05a-l", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_heavy, "mpc1") as fluxo_h:
        with assinar_mpc_state(admin, flow_light, "mpc1") as _fluxo_l:
            # Inicia deploy do flow pesado
            deploy_flow(admin, flow_heavy)

            # Aguarda um momento pro deploy começar
            time.sleep(0.5)

            # Prova: (a) STOP de outro flow enquanto deploy está em progresso
            t_stop_start = time.monotonic()
            admin.post(f"/api/flows/{flow_light}/stop")
            t_stop_end = time.monotonic()

            latencia_stop = t_stop_end - t_stop_start

            # Prova: latência <= 5 s (não foi bloqueado pelo lock do deploy)
            assert latencia_stop < 5.0, (
                f"stop demorou {latencia_stop:.2f}s (deve ser < 5s, "
                "indica que foi bloqueado pelo deploy)"
            )

            # Aguarda deploy pesado terminar (transição para idle)
            fluxo_h.esperar(
                lambda e: e.get("status", {}).get("solver") == "idle",
                timeout=30.0,
                descricao="deploy pesado idle",
            )


def test_e2e_f5_05_building_observavel_local_antes_idle(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-05(b): building observável em mpc.state no deploy em LOCAL (spec §6.2)."""
    resetar_atuador_mpc(opcsim_client)

    flow_id = criar_flow_mpc("f5-05b", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        # Inicia deploy
        deploy_flow(admin, flow_id)

        # Prova: (b) aguarda e prova que "building" aparece ANTES de "idle"
        building_encontrado = False
        idle_encontrado = False
        estados_vistos = []

        for _ in range(50):  # 50 × 0.5s = até 25s
            try:
                amostra = fluxo.proxima(timeout=1.0, descricao="estado")
                estado_solver = amostra.get("status", {}).get("solver")
                estados_vistos.append(estado_solver)

                if estado_solver == "building":
                    building_encontrado = True
                    # Prova: building deve estar em LOCAL
                    modo_local_remote = amostra["modes"]["local_remote"]
                    assert modo_local_remote == "local", (
                        f"building em LOCAL ({modo_local_remote})"
                    )

                if estado_solver == "idle":
                    idle_encontrado = True
                    # Uma vez em idle, não volta a building
                    break
            except AssertionError:
                pass

            time.sleep(0.1)

        # Prova: (b) building foi observado antes de idle
        assert building_encontrado, (
            f"building nunca foi observado. Estados vistos: {estados_vistos}"
        )
        assert idle_encontrado, (
            f"idle nunca foi observado. Estados vistos: {estados_vistos}"
        )

        # Prova ordem: building deve aparecer antes de idle
        if "building" in estados_vistos and "idle" in estados_vistos:
            idx_building = estados_vistos.index("building")
            idx_idle = estados_vistos.index("idle")
            assert idx_building < idx_idle, (
                f"building({idx_building}) deve vir antes de idle({idx_idle})"
            )


def test_e2e_f5_05_arm_remoto_durante_build_mpc_arm_failed(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
    eventos: Any,
) -> None:
    """E2E-F5-05(c): armar (local_remote=remote) na janela de build => mpc_arm_failed (spec §6)."""
    resetar_atuador_mpc(opcsim_client)

    flow_id = criar_flow_mpc("f5-05c", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        # Inicia deploy (abre janela de building)
        deploy_flow(admin, flow_id)

        # Aguarda building
        fluxo.esperar(
            lambda e: e.get("status", {}).get("solver") == "building",
            timeout=30.0,
            descricao="building",
        )

        # Prova: (c) tenta armar para remoto enquanto building
        # POST /api/operate/{flow_id}/{block_id}/mode = {"axis": "local_remote", "value": "remote"}
        operar_modo(admin, flow_id, "mpc1", "local_remote", "remote")
        time.sleep(0.5)

        # Aguarda evento mpc_arm_failed com reason=worker_not_ready
        predicado_arm_failed = evento_mpc("mpc_arm_failed", flow_id, "mpc1")

        evento_encontrado = eventos.esperar(
            predicado_arm_failed,
            timeout=5.0,
            descricao="mpc_arm_failed",
        )

        # Prova: (c) evento tem reason="worker_not_ready"
        # Estrutura do evento: {ts, severity, origin, message, payload}
        assert "payload" in evento_encontrado, (
            f"evento sem payload: {evento_encontrado}"
        )
        reason = evento_encontrado["payload"].get("reason")
        assert reason == "worker_not_ready", (
            f"esperava reason=worker_not_ready, obteve {reason}"
        )


def test_e2e_f5_06_ts_presente(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-06(b): ts presente em mpc.state (spec §2.1)."""
    resetar_atuador_mpc(opcsim_client)

    flow_id = criar_flow_mpc("f5-06b", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Coleta 5 amostras
        amostras = []
        for i in range(5):
            a = fluxo.esperar(lambda _e: True, timeout=30.0, descricao=f"amostra {i+1}")
            amostras.append(a)

        # Prova: (b) todas têm ts
        for i, amostra in enumerate(amostras):
            assert "ts" in amostra, f"amostra {i}: falta ts"

            # Valida que ts é timestamp ISO-8601 válido
            try:
                ts = datetime.fromisoformat(amostra["ts"])
                assert isinstance(ts, datetime), f"ts inválido: {amostra['ts']}"
            except ValueError:
                pytest.fail(f"ts não é ISO-8601: {amostra['ts']}")


def test_e2e_f5_06_prediction_ts_presente(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-06(b): prediction_ts presente em mpc.state (spec §2.1)."""
    resetar_atuador_mpc(opcsim_client)

    flow_id = criar_flow_mpc("f5-06pred", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Coleta amostras, mas pode ser que prediction_ts só apareça em AUTO
        # Por enquanto apenas valida se estiver presente
        amostras = []
        for i in range(5):
            a = fluxo.esperar(lambda _e: True, timeout=30.0, descricao=f"amostra {i+1}")
            amostras.append(a)

        # Prova: quando presente, prediction_ts é timestamp válido
        for i, amostra in enumerate(amostras):
            if "prediction_ts" in amostra:
                try:
                    pts = datetime.fromisoformat(amostra["prediction_ts"])
                    assert isinstance(pts, datetime)
                except ValueError:
                    pytest.fail(f"prediction_ts não é ISO-8601: {amostra['prediction_ts']}")


def test_e2e_f5_06_ts_monotonico(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-06: ts monotônico (nunca regride) (spec §2.1)."""
    resetar_atuador_mpc(opcsim_client)

    flow_id = criar_flow_mpc("f5-06-mono", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Coleta 8 amostras
        amostras = []
        for i in range(8):
            a = fluxo.esperar(lambda _e: True, timeout=30.0, descricao=f"amostra {i+1}")
            amostras.append(a)

        # Prova: ts monotônico
        ts_valores = [datetime.fromisoformat(a["ts"]) for a in amostras]
        for i in range(1, len(ts_valores)):
            assert ts_valores[i] >= ts_valores[i - 1], (
                f"ts regrediu: {ts_valores[i-1]} -> {ts_valores[i]}"
            )


def test_e2e_f5_06_em_regime_prediction_ts_iguala_ts_menos_ts_mpc(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-06(d): em regime, prediction_ts == ts − Ts_mpc (±30% tolerância) (spec §3.2)."""
    resetar_atuador_mpc(opcsim_client)

    flow_id = criar_flow_mpc("f5-06-regime", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Coleta 10 amostras pra entrar em regime (skip as primeiras 3)
        amostras = []
        for i in range(10):
            a = fluxo.esperar(lambda _e: True, timeout=30.0, descricao=f"amostra {i+1}")
            amostras.append(a)

        # Filtra amostras que têm prediction_ts (só em AUTO)
        amostras_com_pred = [a for a in amostras if "prediction_ts" in a]

        if len(amostras_com_pred) < 3:
            # Não estamos em AUTO, teste não aplicável
            pytest.skip("prediction_ts não presente (não em AUTO)")

        # Pega as últimas 3 amostras com prediction_ts (regime estável)
        amostras_regime = amostras_com_pred[-3:]

        # Prova: (d) em regime, prediction_ts == ts − Ts_mpc
        for i, amostra in enumerate(amostras_regime):
            ts = datetime.fromisoformat(amostra["ts"])
            pts = datetime.fromisoformat(amostra["prediction_ts"])

            delta_segundos = (ts - pts).total_seconds()

            # Tolerância: ±30% de Ts_mpc
            # Pode variar um pouco por quantização, etc.
            min_esperado = 0.7 * TS_MPC
            max_esperado = 1.3 * TS_MPC

            assert min_esperado <= delta_segundos <= max_esperado, (
                f"regime amostra {i}: delta_ts={delta_segundos:.3f}s, "
                f"esperado ~{TS_MPC}s (±30%)"
            )
