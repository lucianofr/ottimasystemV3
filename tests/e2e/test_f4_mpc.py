"""Camada L2 da F4b (spec F4 §9.2, tarefa 4.1): malha fechada MPC↔TFS via API + WS + opcsim.

Cinco cenários (E2E-F4-01..05); 03 e 05 são literalmente o aceite da fase (PRD §8-F4) —
tolerâncias declaradas, sem folga arbitrária (brief da tarefa). `mv_pid` é a MV que fecha a
malha física via OPC (ADR-022); `mv_direta` só participa da matriz `models` pra passar no
teto §2.2-3 e nunca sai do LOCAL. Ver `conftest.py` (seção "F4b") pro desenho completo da
malha (`grafo_mpc_tfs`) e os ganhos escolhidos.
"""

import time
from typing import Any

import httpx
import pytest

from .conftest import (
    DU_MAX_MV,
    FAIXA_CO,
    LIMITES_SP_CV,
    TS_MPC,
    AmbienteMpc,
    OpcSim,
    assinar_mpc_state,
    criar_tag_leitura_dummy,
    deploy_flow,
    grafo_mpc_tfs,
    operar_modo,
    operar_sp,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e


# --------------------------------------------------------------------------------------
# Construtores locais de validação (E2E-F4-02) — espelham o esqueleto §2.1, mesmo padrão
# de `test_flows_mpc.py`; cópia local de propósito (mesa de teste autocontida).
# --------------------------------------------------------------------------------------


def _mv_e2e(letra: str, *, pid: dict | None = None) -> dict:
    node = {
        "id": f"mv_{letra}",
        "name": f"MV {letra}",
        "eu": "m3/h",
        "limits": {"min": 0.0, "max": 100.0},
        "du_max": 5.0,
        "initial_value": 0.0,
    }
    if pid is not None:
        node["pid"] = pid
    return node


def _cv_e2e(letra: str, *, tss: float = 30.0) -> dict:
    return {
        "id": f"cv_{letra}",
        "name": f"CV {letra}",
        "eu": "C",
        "kind": "selfreg",
        "tss": tss,
        "weight": 1.0,
        "sp_limits": {"min": 0.0, "max": 100.0},
    }


def _co_e2e(letra: str) -> dict:
    return {
        "id": f"co_{letra}",
        "name": f"Restrição {letra}",
        "eu": "%",
        "kind": "integrating",
        "tss": 30.0,
        "range": {"low": 0.0, "high": 100.0},
        "priority": 1,
    }


def _dv_e2e(letra: str) -> dict:
    return {"id": f"dv_{letra}", "name": f"DV {letra}", "eu": "m3/h"}


def _grafo_validacao(
    admin: httpx.Client, ambiente: AmbienteMpc, dados: dict, *, mpc_id: str = "m1"
) -> dict:
    """Grafo mínimo com um bloco `mpc` — cada entrada dinâmica (CV/Restrição/DV) ganha um
    `opc_read` dedicado (mesmo padrão de `_grafo_mpc`, `test_flows_mpc.py`): as reprovações
    destes cenários são da matriz/horizontes/tags do `pid`, nunca de porta solta."""
    variables = dados["variables"]
    ids_entrada = [
        v["id"] for v in (*variables["cvs"], *variables["constraints"], *variables["dvs"])
    ]
    nodes: list[dict] = []
    edges: list[dict] = []
    for indice, var_id in enumerate(ids_entrada, start=1):
        tag_id = criar_tag_leitura_dummy(admin, ambiente.conn_id, f"val-in-{indice}")
        source_id = f"r{indice}"
        nodes.append(
            {
                "id": source_id,
                "type": "opc_read",
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": indice, "tag_id": tag_id},
            }
        )
        edges.append(
            {
                "id": f"e{indice}",
                "source": source_id,
                "sourceHandle": "out",
                "target": mpc_id,
                "targetHandle": var_id,
            }
        )
    nodes.append(
        {
            "id": mpc_id,
            "type": "mpc",
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": len(nodes) + 1, **dados},
        }
    )
    return {"nodes": nodes, "edges": edges}


# --------------------------------------------------------------------------------------
# E2E-F4-01 — deploy, cadência de `mpc.state`, boot em LOCAL
# --------------------------------------------------------------------------------------


def test_e2e_f4_01_deploy_publica_mpc_state_e_boot_em_local(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F4-01 (spec §9.2): `mpc.state` publica em cadência ~Ts_mpc; boot sempre em LOCAL
    (RNF-03, decisão A-4). `status.solver` fica `building`/`idle` fora de AUTO — nunca um
    status de solver ativo (spec F5 §6.2, tarefa 4.1 F5a — F-1: `building` precede `idle`
    em QUALQUER modo enquanto o host não estiver pronto, LOCAL inclusive)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f4-01", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        amostras = [
            fluxo.esperar(lambda _e: True, timeout=30.0, descricao="1º mpc.state após deploy")
        ]
        chegada = [time.monotonic()]
        for _ in range(3):
            amostras.append(
                fluxo.esperar(lambda _e: True, timeout=15.0, descricao="mpc.state seguinte")
            )
            chegada.append(time.monotonic())

    primeira = amostras[0]
    assert primeira["modes"] == {"local_remote": "local", "man_auto": "man"}
    assert primeira["status"]["armed"] is False
    assert primeira["prediction"] == {
        "t": [],
        "cv": [],
        "mv": [],
        "ts": primeira["prediction"]["ts"],
    }
    solvers = [e["status"]["solver"] for e in amostras]
    assert all(s in ("building", "idle") for s in solvers), (
        f"solver fora de building/idle em LOCAL: {solvers}"
    )

    deltas = [b - a for a, b in zip(chegada, chegada[1:], strict=False)]
    assert all(TS_MPC * 0.7 <= d <= TS_MPC * 1.5 for d in deltas), (
        f"cadência fora de [{TS_MPC * 0.7:.2f}, {TS_MPC * 1.5:.2f}]s (Ts_mpc={TS_MPC}s): {deltas}"
    )


# --------------------------------------------------------------------------------------
# E2E-F4-02 — 422s de validação (spec §2.2)
# --------------------------------------------------------------------------------------


def test_e2e_f4_02_reprovacoes_422_de_validacao(
    admin: httpx.Client, ambiente_mpc: AmbienteMpc, criar_flow_mpc: Any
) -> None:
    """E2E-F4-02 (spec §9.2): matriz incoerente, Np>120 e tag do `pid` com direção errada —
    os três 422s de validação do PUT de flow, contra o stack real (não a mesa pura)."""
    flow_id = criar_flow_mpc("f4-02", ts_seconds=1.0)

    # (a) matriz incoerente — linha só com DV é incontrolável (spec §2.2-3: precisa de ≥1
    # par habilitado cuja coluna é MV; o par de `mv_a` entra desabilitado de propósito).
    mv_a, co_a, dv_a = _mv_e2e("a"), _co_e2e("a"), _dv_e2e("a")
    dados_matriz = {
        "name": "Matriz incoerente",
        "multiplier": 1,
        "variables": {"mvs": [mv_a], "cvs": [], "constraints": [co_a], "dvs": [dv_a]},
        "models": {
            co_a["id"]: {
                mv_a["id"]: {"enabled": False, "params": {"Ki": 1.0, "theta": 0.0}},
                dv_a["id"]: {"enabled": True, "params": {"Ki": 1.0, "theta": 0.0}},
            }
        },
    }
    grafo_matriz = _grafo_validacao(admin, ambiente_mpc, dados_matriz)
    r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo_matriz})
    assert r.status_code == 422, r.text
    assert "cuja coluna é MV" in r.json()["detail"]

    # (b) Np>120 — Ts_mpc = multiplier(1) × Ts_flow(1) = 1s; tss=121 -> Np=121 (spec §2.2-5).
    dados_np = {
        "name": "Np acima do teto",
        "multiplier": 1,
        "variables": {
            "mvs": [_mv_e2e("b")],
            "cvs": [_cv_e2e("b", tss=121.0)],
            "constraints": [],
            "dvs": [],
        },
        "models": {
            "cv_b": {
                "mv_b": {
                    "enabled": True,
                    "params": {"K": 1.0, "tau1": 10.0, "tau2": 2.0, "theta": 0.0},
                }
            }
        },
    }
    grafo_np = _grafo_validacao(admin, ambiente_mpc, dados_np)
    r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo_np})
    assert r.status_code == 422, r.text
    assert "aumente o multiplicador ou reduza o TSS" in r.json()["detail"]

    # (c) tag do `pid` com direção errada — `write_tag_id` exige 'w' e aponta pra uma tag
    # de leitura (`readback`, direção 'r'); spec §2.2-6.
    pid_errado = {
        "write_tag_id": ambiente_mpc.readback,
        "target_mode": "rcas",
        "mode_cmd_tag_id": ambiente_mpc.mode_cmd,
        "mode_read_tag_id": ambiente_mpc.mode_read,
        "readback_tag_id": ambiente_mpc.readback,
        "mode_values": {"auto": 1, "target": 3},
    }
    dados_pid = {
        "name": "PID direção errada",
        "multiplier": 1,
        "variables": {
            "mvs": [_mv_e2e("c", pid=pid_errado)],
            "cvs": [_cv_e2e("c")],
            "constraints": [],
            "dvs": [],
        },
        "models": {
            "cv_c": {
                "mv_c": {
                    "enabled": True,
                    "params": {"K": 1.0, "tau1": 10.0, "tau2": 2.0, "theta": 0.0},
                }
            }
        },
    }
    grafo_pid = _grafo_validacao(admin, ambiente_mpc, dados_pid)
    r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo_pid})
    assert r.status_code == 422, r.text
    assert "direção" in r.json()["detail"]


# --------------------------------------------------------------------------------------
# Helper de cenário — arma LOCAL→REMOTO(MAN)→AUTO, confirmando cada passo pelo `mpc.state`
# --------------------------------------------------------------------------------------


def _armar_ate_remoto(admin: httpx.Client, fluxo: Any, flow_id: int, block_id: str) -> None:
    """LOCAL→REMOTO(MAN) com confirmação — espera a transição aparecer no `mpc.state` e
    depois confere que ela NÃO reverte dentro da janela de confirmação (2×Ts_mpc, spec
    §4.4): reverter é `mpc_arm_failed{reason: no_confirm}`, o oposto do que este helper
    afirma."""
    # Precondição (tarefa 4.1): aguardar host pronto antes de armar
    fluxo.esperar(
        lambda e: e.get("status", {}).get("solver") != "building",
        timeout=60.0,
        descricao=f"{block_id} host ready (não building)",
    )
    operar_modo(admin, flow_id, block_id, "local_remote", "remote")
    fluxo.esperar(
        lambda e: e["modes"]["local_remote"] == "remote",
        timeout=10.0,
        descricao="transição pra REMOTO",
    )
    janela = fluxo.coletar(
        quantidade=3, timeout=TS_MPC * 3 + 5.0, descricao="janela de confirmação do arme (2×Ts_mpc)"
    )
    assert all(e["modes"]["local_remote"] == "remote" for e in janela), (
        "reverteu pra LOCAL durante a janela de confirmação — mpc_arm_failed(no_confirm)? "
        f"série: {[e['modes']['local_remote'] for e in janela]}"
    )


def _armar_ate_auto(admin: httpx.Client, fluxo: Any, flow_id: int, block_id: str) -> None:
    _armar_ate_remoto(admin, fluxo, flow_id, block_id)
    operar_modo(admin, flow_id, block_id, "man_auto", "auto")
    fluxo.esperar(
        lambda e: e["modes"]["man_auto"] == "auto", timeout=5.0, descricao="transição pra AUTO"
    )


# --------------------------------------------------------------------------------------
# E2E-F4-03 — ACEITE: arme sem salto de MV (PRD §8-F4)
# --------------------------------------------------------------------------------------


@pytest.mark.rnf09
def test_e2e_f4_03_arme_local_remoto_auto_sem_salto(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F4-03 (aceite PRD §8-F4): LOCAL→REMOTO(MAN)→AUTO — ΔMV da 1ª execução em AUTO é
    ≤ du_max (spec §3.6: init bumpless faz `u_{k-1} := u_vigente`, então "sem salto" é
    consequência da construção — o teto Δu é RESTRIÇÃO DURA do otimizador, não uma meta
    aproximada). SP agressivo (95, perto do teto de `sp_limits`) força o otimizador a
    QUERER mover mais que `du_max` de uma vez, tornando o teto visivelmente ativo."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f4-03", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        estado_local = fluxo.esperar(
            lambda e: e["modes"]["local_remote"] == "local", timeout=30.0, descricao="boot em LOCAL"
        )
        vigente = estado_local["vars"]["mv_pid"]["v"]

        _armar_ate_remoto(admin, fluxo, flow_id, "mpc1")
        operar_modo(admin, flow_id, "mpc1", "man_auto", "auto")
        fluxo.esperar(
            lambda e: e["modes"]["man_auto"] == "auto", timeout=5.0, descricao="transição pra AUTO"
        )
        operar_sp(admin, flow_id, "mpc1", "cv_1", 95.0)

        pos_auto = fluxo.coletar(
            quantidade=15, timeout=TS_MPC * 15 + 10.0, descricao="série de mpc.state em AUTO"
        )

    valores = [e["vars"]["mv_pid"]["v"] for e in pos_auto]
    primeiro_diferente = next((v for v in valores if abs(v - vigente) > 1e-6), None)
    assert primeiro_diferente is not None, f"mv_pid nunca saiu de {vigente} em AUTO: {valores}"
    delta = abs(primeiro_diferente - vigente)
    assert delta <= DU_MAX_MV + 1e-2, (
        f"1ª execução em AUTO moveu ΔMV={delta:.3f} > du_max={DU_MAX_MV} "
        f"(vigente={vigente}, 1ª execução={primeiro_diferente})"
    )


# --------------------------------------------------------------------------------------
# E2E-F4-04 — AUTO converge CV→SP na malha TFS
# --------------------------------------------------------------------------------------


def test_e2e_f4_04_auto_converge_cv_para_sp_na_malha_tfs(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F4-04 (spec §9.2): em AUTO, `cv1` converge pro SP dentro de 2% do span de
    `sp_limits` (100 -> tolerância 2.0) em até 20×Ts_mpc — malha fechada de verdade pela TFS
    `planta` (ADR-022), sem mismatch deliberado de modelo (spec §3.3: o `bias` corrige o
    resto, mas aqui o modelo interno já bate com a física simulada — o E2E testa a malha
    fechada, não a robustez a erro de modelo, isso é TDD, spec §9.1)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f4-04", grafo=grafo_mpc_tfs(ambiente_mpc))
    sp = 25.0
    tolerancia = 0.02 * (LIMITES_SP_CV["max"] - LIMITES_SP_CV["min"])  # 2% de 100 = 2.0

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        fluxo.esperar(
            lambda e: e["modes"]["local_remote"] == "local", timeout=30.0, descricao="boot em LOCAL"
        )

        _armar_ate_auto(admin, fluxo, flow_id, "mpc1")
        operar_sp(admin, flow_id, "mpc1", "cv_1", sp)

        convergiu = fluxo.esperar(
            lambda e: (
                e["modes"]["man_auto"] == "auto" and abs(e["vars"]["cv_1"]["v"] - sp) < tolerancia
            ),
            timeout=20 * TS_MPC,
            descricao=f"cv1 convergir pra SP={sp} (±{tolerancia})",
        )

    assert abs(convergiu["vars"]["cv_1"]["v"] - sp) < tolerancia
    assert convergiu["vars"]["cv_1"]["sp"] == sp


# --------------------------------------------------------------------------------------
# E2E-F4-05 — ACEITE: restrição vence CV (PRD §8-F4)
# --------------------------------------------------------------------------------------


@pytest.mark.rnf09
def test_e2e_f4_05_restricao_vence_cv(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F4-05 (aceite PRD §8-F4): SP fora do que `co1` tolera (spec §3.4 — `w_slack` =
    10⁴×max(w_cv)×priority, dominante por construção) ⇒ a faixa de `co1` é respeitada e o
    SP de `cv1` é sacrificado. Só `mv_pid` move `co1` de verdade (`GANHO_INTEGRADOR_CO`);
    `mv_direta` entra na matriz com Ki desprezível (1e-4) só pra satisfazer o teto "cada MV
    com ≥1 par habilitado" (spec §2.2-3) — documentado em `conftest.py`."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f4-05", grafo=grafo_mpc_tfs(ambiente_mpc))
    sp_agressivo = 95.0
    tolerancia_co = 0.05 * (FAIXA_CO["high"] - FAIXA_CO["low"])  # 5% da faixa de 10 = 0.5
    gap_minimo = 15.0  # sacrifício claro, bem acima da folga de uma soft constraint

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        fluxo.esperar(
            lambda e: e["modes"]["local_remote"] == "local", timeout=30.0, descricao="boot em LOCAL"
        )

        _armar_ate_auto(admin, fluxo, flow_id, "mpc1")
        operar_sp(admin, flow_id, "mpc1", "cv_1", sp_agressivo)

        # Mesma ordem de grandeza da janela de acomodação do E2E-F4-04.
        acomodado = fluxo.coletar(
            quantidade=20,
            timeout=20 * TS_MPC + 10.0,
            descricao="acomodação sob conflito SP×Restrição",
        )

    finais = acomodado[-5:]
    for estado in finais:
        co1 = estado["vars"]["co_1"]["v"]
        assert FAIXA_CO["low"] - tolerancia_co <= co1 <= FAIXA_CO["high"] + tolerancia_co, (
            f"co1={co1} fora da faixa {FAIXA_CO} (±{tolerancia_co}) — a Restrição não venceu"
        )
    cv1_final = finais[-1]["vars"]["cv_1"]["v"]
    assert sp_agressivo - cv1_final >= gap_minimo, (
        f"cv1={cv1_final} perto demais do SP={sp_agressivo} "
        f"(gap={sp_agressivo - cv1_final:.2f} < {gap_minimo}) — o SP não foi sacrificado"
    )
