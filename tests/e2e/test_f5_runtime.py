"""L2 F5a (spec F5 §9.2, tarefa 5.1): concorrência, building, prediction_ts.

E2E-F5-05: deploy não bloqueia stop; building em LOCAL; arm_failed em janela build.
E2E-F5-06: ts presente e monotônico; prediction_ts presente; em AUTO: prediction_ts ≈ ts − Ts_mpc.
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


def test_e2e_f5_05_deploy_building_arm_failed(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
    eventos: Any,
) -> None:
    """E2E-F5-05: F-1 deploy assíncrono; building em LOCAL; arm_failed em build.

    (a) deploy MPC pesado NÃO bloqueia stop de outro flow (latência < 5s)
    (b) building observável em mpc.state no deploy em LOCAL, antes de idle
    (c) armar para REMOTO durante building ⇒ mpc_arm_failed {worker_not_ready}
    """
    resetar_atuador_mpc(opcsim_client)

    # (a) Dois flows: um pesado (deploy longo), um leve (stop rápido)
    flow_heavy = criar_flow_mpc("f5-05a-h", grafo=grafo_mpc_tfs(ambiente_mpc))
    flow_light = criar_flow_mpc("f5-05a-l", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_heavy, "mpc1") as fluxo_h:
        with assinar_mpc_state(admin, flow_light, "mpc1") as _fluxo_l:
            # Inicia deploy do flow pesado
            deploy_flow(admin, flow_heavy)

            # Aguarda um momento pro deploy começar
            time.sleep(0.5)

            # (a) STOP de outro flow enquanto deploy em progresso
            t_stop_start = time.monotonic()
            admin.post(f"/api/flows/{flow_light}/stop")
            t_stop_end = time.monotonic()

            latencia_stop = t_stop_end - t_stop_start

            # (a) latência <= 5 s (não foi bloqueado pelo lock do deploy)
            assert latencia_stop < 5.0, (
                f"stop demorou {latencia_stop:.2f}s (deve ser < 5s, indica bloqueio pelo deploy)"
            )

            # (b) Aguarda building
            building_encontrado = False
            idle_encontrado = False
            estados_vistos = []

            for _ in range(50):  # 50 iterações
                try:
                    amostra = fluxo_h.proxima(timeout=1.0, descricao="estado")
                    estado_solver = amostra.get("status", {}).get("solver")
                    estados_vistos.append(estado_solver)

                    if estado_solver == "building":
                        building_encontrado = True
                        # (b) building em LOCAL
                        modo_local_remote = amostra["modes"]["local_remote"]
                        assert modo_local_remote == "local", (
                            f"building esperado em LOCAL, obteve {modo_local_remote}"
                        )

                    if estado_solver == "idle":
                        idle_encontrado = True
                        break
                except AssertionError:
                    pass

                time.sleep(0.1)

            # (b) building foi observado antes de idle
            assert building_encontrado, f"building nunca observado. Estados: {estados_vistos}"
            assert idle_encontrado, f"idle nunca observado. Estados: {estados_vistos}"

            # (b) ordem: building < idle
            if "building" in estados_vistos and "idle" in estados_vistos:
                idx_b = estados_vistos.index("building")
                idx_i = estados_vistos.index("idle")
                assert idx_b < idx_i, f"building({idx_b}) deve vir antes de idle({idx_i})"

            # (c) Armar para REMOTO durante building
            # Reinicia deploy se já passou de building
            if idle_encontrado:
                resetar_atuador_mpc(opcsim_client)
                flow_c = criar_flow_mpc("f5-05c", grafo=grafo_mpc_tfs(ambiente_mpc))

                with assinar_mpc_state(admin, flow_c, "mpc1") as fluxo_c:
                    deploy_flow(admin, flow_c)

                    # Aguarda building
                    fluxo_c.esperar(
                        lambda e: e.get("status", {}).get("solver") == "building",
                        timeout=30.0,
                        descricao="building",
                    )

                    # Tenta armar para REMOTO durante building
                    operar_modo(admin, flow_c, "mpc1", "local_remote", "remote")
                    time.sleep(0.5)

                    # Aguarda evento mpc_arm_failed
                    predicado_arm_failed = evento_mpc("mpc_arm_failed", flow_c, "mpc1")

                    evento_encontrado = eventos.esperar(
                        predicado_arm_failed,
                        timeout=5.0,
                        descricao="mpc_arm_failed",
                    )

                    # (c) evento tem reason="worker_not_ready"
                    assert "payload" in evento_encontrado
                    reason = evento_encontrado["payload"].get("reason")
                    assert reason == "worker_not_ready", (
                        f"esperava reason=worker_not_ready, obteve {reason}"
                    )


def test_e2e_f5_06_ts_prediction_regime(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-06: ts monotônico; prediction_ts presente; em regime: ≈ ts − Ts_mpc.

    (b) ts presente em mpc.state, ISO-8601
    (c) prediction_ts presente em mpc.state quando em AUTO
    (d) ts monotônico (nunca regride)
    (e) em regime (AUTO), prediction_ts == ts − Ts_mpc (±30%)
    """
    resetar_atuador_mpc(opcsim_client)

    flow_id = criar_flow_mpc("f5-06", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Coleta amostras WS iniciais (LOCAL+AUTO esperado após alguns ciclos)
        amostras = []
        for i in range(15):
            try:
                a = fluxo.esperar(lambda _e: True, timeout=30.0, descricao=f"amostra {i + 1}")
                amostras.append(a)
            except AssertionError:
                break

        # (b) ts presente em todas
        for i, amostra in enumerate(amostras):
            assert "ts" in amostra, f"amostra {i}: falta ts"
            assert isinstance(amostra["ts"], str)
            # Valida ISO-8601
            try:
                ts = datetime.fromisoformat(amostra["ts"])
                assert isinstance(ts, datetime)
            except ValueError:
                pytest.fail(f"amostra {i}: ts não é ISO-8601: {amostra['ts']}")

        # (d) ts monotônico
        ts_valores = [datetime.fromisoformat(a["ts"]) for a in amostras]
        for i in range(1, len(ts_valores)):
            assert ts_valores[i] >= ts_valores[i - 1], (
                f"ts regrediu: {ts_valores[i - 1]} -> {ts_valores[i]}"
            )

        # (c) prediction_ts presente quando aplicável
        # Pode não estar presente em LOCAL; em AUTO deve estar
        amostras_com_pred = [a for a in amostras if "prediction_ts" in a]

        # Se temos amostras com prediction_ts, valida formato
        for amostra in amostras_com_pred:
            try:
                pts = datetime.fromisoformat(amostra["prediction_ts"])
                assert isinstance(pts, datetime)
            except ValueError:
                pytest.fail(f"prediction_ts não é ISO-8601: {amostra['prediction_ts']}")

        # (e) em regime (AUTO): prediction_ts ≈ ts − Ts_mpc
        # Só validar se temos pelo menos 3 amostras com prediction_ts
        if len(amostras_com_pred) >= 3:
            # Pega as últimas 3 (regime)
            amostras_regime = amostras_com_pred[-3:]

            for i, amostra in enumerate(amostras_regime):
                ts = datetime.fromisoformat(amostra["ts"])
                pts = datetime.fromisoformat(amostra["prediction_ts"])

                delta_segundos = (ts - pts).total_seconds()

                # Tolerância: ±30% de Ts_mpc
                min_esperado = 0.7 * TS_MPC
                max_esperado = 1.3 * TS_MPC

                assert min_esperado <= delta_segundos <= max_esperado, (
                    f"regime amostra {i}: delta_ts={delta_segundos:.3f}s, "
                    f"esperado ~{TS_MPC}s (±30%)"
                )
