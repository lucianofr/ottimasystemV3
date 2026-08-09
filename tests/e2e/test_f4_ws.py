"""Camada L2 da F4b (spec F4 §9.2, tarefa 4.2): shed por `mode_read`, fanout WS e hot-swap.

Dois cenários (E2E-F4-09/10). E2E-F4-09 reutiliza a malha `grafo_mpc_tfs` (precisa do `pid`
físico via opcsim para o `mode_read`). E2E-F4-10 usa um grafo PRÓPRIO com dois blocos `mpc`
diretos (sem `pid`) — um recebe o hot-swap, o outro é o irmão de controle que nunca muda
(spec §4.1-3): prova que o hot-swap troca só quem mudou, preservando o resto.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from asyncua import ua

from opcsim import NODE_MIRROR_INT, NODE_W_INT
from ottima_core.bus import KIND_MPC_MODE_CHANGED, KIND_MPC_SHED

from .conftest import (
    DU_MAX_MV,
    GANHO_CV,
    LIMITES_MV,
    LIMITES_SP_CV,
    MULTIPLICADOR_MPC,
    TAU1_CV,
    TAU2_CV,
    TS_MPC,
    TSS_MALHA,
    AmbienteMpc,
    EventStream,
    OpcSim,
    armar_ate_remoto,
    armar_auto_com_retentativa,
    armar_remoto_direto,
    assinar_mpc_state,
    criar_tag_leitura_dummy,
    deploy_flow,
    esperar_ate,
    evento_mpc,
    grafo_mpc_tfs,
    mpc_block_health,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e


# --------------------------------------------------------------------------------------
# E2E-F4-09 — shed por `mode_read` divergente (RF-604, spec §4.5)
# --------------------------------------------------------------------------------------


def test_e2e_f4_09_shed_por_mode_read_divergente(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
    eventos: EventStream,
) -> None:
    """E2E-F4-09 (spec §9.2/§4.5, RF-604): com o bloco armado e confirmado em REMOTO, o
    watchdog (`mpc_arming.watch_arm`) tica a cada Ts_mpc e sheda depois de EXATAMENTE 2
    ticks consecutivos com `mode_read != target`. `mode_read` mapeia pro espelho
    `sim.mirror.int` — NÃO gravável por cliente OPC (`BadUserAccessDenied`: só o próprio
    servidor escreve nos espelhos). Pra divergir de verdade, escrevemos na tag de ORIGEM
    do espelho (`sim.w.int`, o mesmo node físico de `mode_cmd`): o loop do opcsim
    (`VALUES_PERIOD=0,2s`) copia pro espelho, e como nada mais volta a escrever `mode_cmd`
    até a próxima transição de modo, a divergência PERSISTE (contexto da tarefa: "a
    escrita precisa persistir") sem precisar congelar nada."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f4-09", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        fluxo.esperar(
            lambda e: e["modes"]["local_remote"] == "local", timeout=30.0, descricao="boot em LOCAL"
        )
        armar_ate_remoto(admin, fluxo, flow_id, "mpc1")

        opcsim_client.write(
            NODE_W_INT, 1, variant_type=ua.VariantType.Int32
        )  # auto(1) != target(3)
        esperar_ate(
            lambda: opcsim_client.read(NODE_MIRROR_INT) == 1.0 or None,
            timeout=2.0,
            intervalo=0.2,
            descricao="mode_read refletir a divergência no opcsim",
        )

        evento = eventos.esperar(
            evento_mpc(KIND_MPC_SHED, flow_id, "mpc1"),
            timeout=TS_MPC * 6 + 15.0,
            descricao="mpc_shed após 2 execuções com mode_read divergente",
        )
        estado_local = fluxo.esperar(
            lambda e: e["modes"]["local_remote"] == "local",
            timeout=10.0,
            descricao="shed materializar LOCAL",
        )

    assert evento["severity"] == "alarm"
    assert evento["payload"] == {"kind": KIND_MPC_SHED}
    assert estado_local["modes"]["local_remote"] == "local"


# --------------------------------------------------------------------------------------
# E2E-F4-10 — fanout WS de `mpc.state` + hot-swap ⇒ shed + worker novo
# --------------------------------------------------------------------------------------

_TSS_LEVE = TSS_MALHA


def _config_mpc_leve(*, mv_id: str, cv_id: str, weight: float) -> dict:
    """Config MPC leve e direto (sem `pid`) — mesmo tamanho de `_config_mpc_malha` (Np=10,
    Nc=3, dimensão pequena): host fica pronto e resolve rápido, só o peso da CV muda entre
    a versão pré e pós hot-swap (spec §4.7)."""
    return {
        "name": f"MPC leve {mv_id}",
        "multiplier": MULTIPLICADOR_MPC,
        "variables": {
            "mvs": [
                {
                    "id": mv_id,
                    "name": f"MV {mv_id}",
                    "eu": "%",
                    "limits": dict(LIMITES_MV),
                    "du_max": DU_MAX_MV,
                    "initial_value": 0.0,
                }
            ],
            "cvs": [
                {
                    "id": cv_id,
                    "name": f"CV {cv_id}",
                    "eu": "C",
                    "kind": "selfreg",
                    "tss": _TSS_LEVE,
                    "weight": weight,
                    "sp_limits": dict(LIMITES_SP_CV),
                }
            ],
            "constraints": [],
            "dvs": [],
        },
        "models": {
            cv_id: {
                mv_id: {
                    "enabled": True,
                    "params": {"K": GANHO_CV, "tau1": TAU1_CV, "tau2": TAU2_CV, "theta": 0.0},
                }
            }
        },
    }


def _grafo_hot_swap(admin: httpx.Client, ambiente: AmbienteMpc, *, peso_mpc1: float) -> dict:
    """Dois blocos `mpc` independentes e diretos: `mpc1` recebe o hot-swap (peso variável),
    `mpc2` é o irmão que nunca muda — prova de preservação de estado (spec §4.1-3/§4.7).
    Entradas dummy (`NODE_SINE`), mesmo padrão de `_grafo_validacao` (`test_f4_mpc.py`)."""
    tag1 = criar_tag_leitura_dummy(admin, ambiente.conn_id, "hs-cv1")
    tag2 = criar_tag_leitura_dummy(admin, ambiente.conn_id, "hs-cv2")
    nodes = [
        {
            "id": "r1",
            "type": "opc_read",
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": 1, "tag_id": tag1},
        },
        {
            "id": "r2",
            "type": "opc_read",
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": 2, "tag_id": tag2},
        },
        {
            "id": "mpc1",
            "type": "mpc",
            "position": {"x": 0.0, "y": 0.0},
            "data": {
                "exec_order": 3,
                **_config_mpc_leve(mv_id="mv_1", cv_id="cv_1", weight=peso_mpc1),
            },
        },
        {
            "id": "mpc2",
            "type": "mpc",
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": 4, **_config_mpc_leve(mv_id="mv_2", cv_id="cv_2", weight=1.0)},
        },
    ]
    edges = [
        {
            "id": "e1",
            "source": "r1",
            "sourceHandle": "out",
            "target": "mpc1",
            "targetHandle": "cv_1",
        },
        {
            "id": "e2",
            "source": "r2",
            "sourceHandle": "out",
            "target": "mpc2",
            "targetHandle": "cv_2",
        },
    ]
    return {"nodes": nodes, "edges": edges}


@pytest.mark.rnf09
def test_e2e_f4_10_ws_fanout_e_hot_swap(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    eventos: EventStream,
) -> None:
    """E2E-F4-10 (spec §9.2/§6.2/§4.7): (a) o `/ws` entrega o payload §5.1 exato, nenhuma
    chave a mais/a menos; (b) hot-swap (PUT de um peso com o flow rodando) muda só `mpc1` —
    sheda a LOCAL, publica `mpc_mode_changed{reason:hot_swap}`, ganha um `MpcHost` NOVO
    (`worker.last_solve_ms` reseta a `None` — só um host recém-nascido faz isso; um
    respawn interno do MESMO host preserva o último valor) — e `mpc2` (irmão não alterado)
    preserva estado (segue REMOTO+AUTO); o flow inteiro segue rodando nos dois blocos."""
    flow_id = criar_flow_mpc("f4-10", grafo=_grafo_hot_swap(admin, ambiente_mpc, peso_mpc1=1.0))

    with (
        assinar_mpc_state(admin, flow_id, "mpc1") as fluxo1,
        assinar_mpc_state(admin, flow_id, "mpc2") as fluxo2,
    ):
        deploy_flow(admin, flow_id)

        # (a) fanout do /ws — payload §5.1 exato.
        amostra = fluxo1.esperar(
            lambda _e: True, timeout=30.0, descricao="1ª amostra de mpc1 pós-deploy"
        )
        assert set(amostra.keys()) == {"modes", "status", "vars", "cost", "prediction", "ts"}
        assert set(amostra["modes"].keys()) == {"local_remote", "man_auto"}
        assert set(amostra["status"].keys()) == {
            "solver",
            "overruns",
            "last_solve_ms",
            "armed",
            "input_valid",
        }
        assert set(amostra["prediction"].keys()) == {"t", "cv", "mv", "ts"}
        for estado_var in amostra["vars"].values():
            assert set(estado_var.keys()) == {"v", "sp"}

        fluxo1.esperar(
            lambda e: e["modes"]["local_remote"] == "local",
            timeout=10.0,
            descricao="mpc1 boot em LOCAL",
        )
        fluxo2.esperar(
            lambda e: e["modes"]["local_remote"] == "local",
            timeout=10.0,
            descricao="mpc2 boot em LOCAL",
        )

        # Arma os dois pra AUTO — mpc1 é quem recebe o hot-swap, mpc2 é o irmão de controle.
        armar_remoto_direto(admin, fluxo1, flow_id, "mpc1")
        armar_remoto_direto(admin, fluxo2, flow_id, "mpc2")
        armar_auto_com_retentativa(admin, fluxo1, flow_id, "mpc1")
        armar_auto_com_retentativa(admin, fluxo2, flow_id, "mpc2")

        # Espera um solve de verdade nos dois — health com `last_solve_ms` populado é o
        # baseline "worker vivo" contra o qual comparamos o pós-swap.
        estado_ok_1 = fluxo1.esperar(
            lambda e: e["status"]["solver"] == "ok",
            timeout=TS_MPC * 10 + 15.0,
            descricao="mpc1 1º solve ok",
        )
        assert estado_ok_1["modes"] == {"local_remote": "remote", "man_auto": "auto"}
        fluxo2.esperar(
            lambda e: e["status"]["solver"] == "ok",
            timeout=TS_MPC * 10 + 15.0,
            descricao="mpc2 1º solve ok",
        )

        pre_health_1 = mpc_block_health(flow_id, "mpc1")
        assert pre_health_1 is not None and pre_health_1["worker"]["last_solve_ms"] is not None, (
            f"mpc1 não tinha um solve real antes do hot-swap: {pre_health_1}"
        )

        # Hot-swap: PUT muda só o peso de mpc1, com o flow rodando (spec §4.1/§4.7).
        grafo_novo = _grafo_hot_swap(admin, ambiente_mpc, peso_mpc1=5.0)
        r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo_novo})
        assert r.status_code == 200, f"PUT do hot-swap: HTTP {r.status_code} {r.text}"

        origem_mpc1 = evento_mpc(KIND_MPC_MODE_CHANGED, flow_id, "mpc1")
        evento = eventos.esperar(
            lambda e: origem_mpc1(e) and e["payload"].get("reason") == "hot_swap",
            timeout=20.0,
            descricao="mpc_mode_changed{reason: hot_swap} de mpc1 (não a transição de armar)",
        )
        estado_local_1 = fluxo1.esperar(
            lambda e: e["modes"]["local_remote"] == "local",
            timeout=15.0,
            descricao="mpc1 shedar pra LOCAL",
        )

        # Flow segue rodando: mpc.state dos dois blocos continua chegando normalmente.
        pos_swap_2 = fluxo2.esperar(
            lambda _e: True, timeout=10.0, descricao="mpc2 mpc.state pós-swap"
        )
        fluxo1.esperar(lambda _e: True, timeout=10.0, descricao="mpc1 mpc.state pós-swap")

    assert evento["payload"] == {"kind": KIND_MPC_MODE_CHANGED, "reason": "hot_swap"}
    assert estado_local_1["modes"]["local_remote"] == "local"

    # mpc2 (irmão não alterado) preserva estado — nunca sheda (spec §4.1-3).
    assert pos_swap_2["modes"] == {"local_remote": "remote", "man_auto": "auto"}

    # "Worker novo": `/health` de mpc1 reflete um `MpcHost` recém-nascido, não o mesmo
    # processo que já tinha resolvido antes do swap.
    pos_health_1 = mpc_block_health(flow_id, "mpc1")
    assert pos_health_1 is not None
    assert pos_health_1["worker"]["last_solve_ms"] is None, (
        f"mpc1 não ganhou worker novo — last_solve_ms sobreviveu ao hot-swap: {pos_health_1}"
    )
    assert pos_health_1["worker"]["alive"] is True, f"worker novo de mpc1 não subiu: {pos_health_1}"
