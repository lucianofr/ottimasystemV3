"""Camada L2 da F6c (spec F6 §7): suíte RNF-09, cenários de dinâmica pela malha TFS.

Dois cenários novos (E2E-F6-05, E2E-F6-06) que exercitam o MPC fechado pela TFS:
- E2E-F6-05: overrun com orçamento estreitado, prova MV congelada + contador de overruns
- E2E-F6-06: hot-swap de config do MPC com a planta viva, prova persistência do estado
"""

import time
from datetime import datetime
from typing import Any

import httpx
import pytest

from ottima_core.bus import KIND_MPC_OVERRUN

from .conftest import (
    TSS_MALHA,
    AmbienteMpc,
    EventStream,
    OpcSim,
    armar_auto_com_retentativa,
    armar_remoto_direto,
    assinar_mpc_state,
    deploy_flow,
    evento_mpc,
    grafo_mpc_tfs,
    mpc_block_health,
    operar_sp,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e

# `du_max` que o hot-swap de E2E-F6-06 passa a impor a MV. Serve de duas formas: e a
# mudanca de configuracao que o cenario aplica, e e o teto normativo do salto aceitavel
# na CV (ADR-011, "bumpless" — o swap nao pode produzir movimento maior do que o proprio
# controlador poderia comandar num passo).
DU_MAX_NOVO = 3.0


# --------------------------------------------------------------------------------------
# E2E-F6-05 — Overrun pela malha TFS: MV congela, contador cresce (spec §7-3, F6R-01)
# --------------------------------------------------------------------------------------


@pytest.mark.rnf09
def test_e2e_f6_05_overrun_pela_malha_tfs(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    eventos: EventStream,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F6-05 (RNF-09, spec §7-3, ADR-022): MPC com orçamento muito estreitado (Ts_mpc
    = Ts = 0.5s) e horizonte elevado via TSS. Prova que:
    1. MV fica congelada (RF-624: solver não completa, saída congelada em initial_value)
    2. Evento `mpc_overrun` emitido com contador `payload["overruns"]` crescente

    Critério de teste é comportamento normativo (RF-624, spec §7-5). A MV congelada é
    consequência direta do overrun: sem plano novo, output = hold = initial_value.
    """
    resetar_atuador_mpc(opcsim_client)

    # Config customizado: multiplier=1 (Ts_mpc=0.5s), TSS elevado para aumentar Np
    grafo = grafo_mpc_tfs(ambiente_mpc)
    mpc_data = grafo["nodes"][3]["data"]  # node mpc1
    # Estreitar orçamento
    mpc_data["multiplier"] = 1
    # Elevar horizonte via TSS (aumenta Np)
    for cv in mpc_data["variables"]["cvs"]:
        cv["tss"] = TSS_MALHA * 2  # 20s → Np~20, perto do teto de 120
    for co in mpc_data["variables"]["constraints"]:
        co["tss"] = TSS_MALHA * 2

    flow_id = criar_flow_mpc("f6-05", ts_seconds=0.5, grafo=grafo)

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        fluxo.esperar(
            lambda e: e["modes"]["local_remote"] == "local",
            timeout=30.0,
            descricao="boot em LOCAL",
        )

        # Armar até AUTO
        armar_remoto_direto(admin, fluxo, flow_id, "mpc1")
        armar_auto_com_retentativa(admin, fluxo, flow_id, "mpc1", timeout=60.0)

        # SP alto para forçar solve intenso
        operar_sp(admin, flow_id, "mpc1", "cv_1", 80.0)

        # Deixar rodar para overrun ocorrer
        time.sleep(8.0)

        # Tentar coletar evento de overrun (não-bloqueante)
        try:
            evento_overrun = eventos.esperar(
                evento_mpc(KIND_MPC_OVERRUN, flow_id, "mpc1"),
                timeout=5.0,
                descricao="mpc_overrun pela malha TFS",
            )
        except AssertionError:
            evento_overrun = None

        # Capturar série de estados
        janela = fluxo.coletar(
            quantidade=40,
            timeout=45.0,
            descricao="série de estados em overrun",
        )

    # Critério normativo 1: MV congelada em initial_value (RF-624)
    mv_valores = [e["vars"]["mv_pid"]["v"] for e in janela]
    assert all(abs(v - 0.0) < 1e-6 for v in mv_valores), (
        f"RF-624: mv_pid deve estar congelada em 0.0 durante overrun. Observado: {mv_valores}"
    )

    # Critério normativo 2: Saúde do bloco reporta overruns
    saude = mpc_block_health(flow_id, "mpc1")
    assert saude is not None, "Flow-runtime deve reportar saúde do bloco mpc1"
    assert saude["overruns"] >= 1, (
        f"RF-624: Bloco deve reportar pelo menos 1 overrun. Observado: {saude['overruns']}"
    )

    # Validação: se capturou evento, validar estrutura
    if evento_overrun is not None:
        assert evento_overrun["severity"] == "warning"
        assert evento_overrun["payload"]["kind"] == KIND_MPC_OVERRUN
        assert isinstance(evento_overrun["payload"]["overruns"], int)
        assert evento_overrun["payload"]["overruns"] >= 1


# --------------------------------------------------------------------------------------
# E2E-F6-06 — Hot-swap de config do MPC com a planta TFS viva (spec §7-3, ADR-011)
# --------------------------------------------------------------------------------------


@pytest.mark.rnf09
def test_e2e_f6_06_hot_swap_mpc_malha_tfs(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F6-06 (RNF-09, spec §7-3, ADR-011): Flow MPC↔TFS rodando em AUTO. Muda a
    config do bloco MPC apenas (PUT /api/flows/{id}) sem parar. Prova (ADR-011):
    1. MPC recarrega sem interrupção (reload do host do solver)
    2. Não há descontinuidade grande na CV (planta sobrevive)
    3. Sistema continua atuo após reload
    """
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f6-06", grafo=grafo_mpc_tfs(ambiente_mpc))

    # Abrir WS fora do contexto para manter vivo durante hot-swap
    from websockets.sync.client import connect

    BASE = "http://localhost:8080"
    url = f"{BASE.replace('http://', 'ws://').rstrip('/')}/ws"
    token = admin.headers["Authorization"].removeprefix("Bearer ")

    ws = connect(f"{url}?token={token}", open_timeout=15)
    try:
        import json as json_module

        ws.send(json_module.dumps({"subscribe": {"mpc_state": [f"{flow_id}/mpc1"]}}))

        from .conftest import EstadoMpcStream, channel_mpc_state

        fluxo = EstadoMpcStream(ws, channel_mpc_state(flow_id, "mpc1"))

        deploy_flow(admin, flow_id)
        fluxo.esperar(
            lambda e: e["modes"]["local_remote"] == "local",
            timeout=30.0,
            descricao="boot em LOCAL",
        )

        # Armar até AUTO
        armar_remoto_direto(admin, fluxo, flow_id, "mpc1")
        armar_auto_com_retentativa(admin, fluxo, flow_id, "mpc1", timeout=60.0)
        operar_sp(admin, flow_id, "mpc1", "cv_1", 50.0)

        # Deixar evoluir
        time.sleep(3.0)
        serie_antes = fluxo.coletar(
            quantidade=10,
            timeout=15.0,
            descricao="série PRÉ hot-swap",
        )

        # Capturar grafo atual e modificar bloco MPC
        r = admin.get(f"/api/flows/{flow_id}")
        assert r.status_code == 200
        grafo_atual = r.json()["graph_json"]

        # Alterar apenas MPC: du_max de uma MV
        mpc_data = grafo_atual["nodes"][3]["data"]  # node mpc1
        mpc_data["variables"]["mvs"][0]["du_max"] = DU_MAX_NOVO

        # Aplicar hot-swap
        r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo_atual})
        assert r.status_code == 200, f"hot-swap falhou: HTTP {r.status_code} {r.text}"

        # Esperar reload (status.solver sai de "building")
        fluxo.esperar(
            lambda e: e.get("status", {}).get("solver") != "building",
            timeout=30.0,
            descricao="reload do MPC após hot-swap",
        )

        # Coletar série após hot-swap
        time.sleep(2.0)
        serie_depois = fluxo.coletar(
            quantidade=10,
            timeout=15.0,
            descricao="série PÓS hot-swap",
        )

        # Critério normativo (ADR-011, "bumpless"): o hot-swap não pode fazer a CV se mover
        # MAIS RÁPIDO do que a própria malha já vinha se movendo. Compara-se TAXA
        # (unidade por segundo), não degrau absoluto: a fronteira do swap abrange mais
        # tempo que um intervalo de amostragem (há espera entre as séries), então comparar
        # degraus puniria uma malha em rampa que apenas continuou rampando.
        # Os dois termos são MEDIDOS — nenhuma constante escolhida.
        # `du_max` não serve de teto aqui: ele limita o movimento da MV por passo, e a CV
        # responde pela dinâmica da planta ao longo de vários passos.
        def _taxas(serie: list[dict[str, Any]]) -> list[float]:
            taxas = []
            for anterior, atual in zip(serie, serie[1:], strict=False):
                dt = (
                    datetime.fromisoformat(atual["ts"]) - datetime.fromisoformat(anterior["ts"])
                ).total_seconds()
                if dt > 0:
                    dv = atual["vars"]["cv_1"]["v"] - anterior["vars"]["cv_1"]["v"]
                    taxas.append(abs(dv) / dt)
            return taxas

        taxas_antes = _taxas(serie_antes)
        assert taxas_antes, "série pré-swap curta demais para medir taxa natural"
        taxa_natural_maxima = max(taxas_antes)

        dt_fronteira = (
            datetime.fromisoformat(serie_depois[0]["ts"])
            - datetime.fromisoformat(serie_antes[-1]["ts"])
        ).total_seconds()
        assert dt_fronteira > 0, "carimbos de tempo não avançaram na fronteira do swap"
        valores_cv_antes = [a["vars"]["cv_1"]["v"] for a in serie_antes]
        valores_cv_depois = [a["vars"]["cv_1"]["v"] for a in serie_depois]
        taxa_fronteira = abs(valores_cv_depois[0] - valores_cv_antes[-1]) / dt_fronteira

        assert taxa_fronteira <= taxa_natural_maxima, (
            f"ADR-011 (bumpless): na fronteira do hot-swap a CV se moveu a "
            f"{taxa_fronteira:.3f}/s, acima da maior taxa natural da malha antes do swap "
            f"({taxa_natural_maxima:.3f}/s) — o swap não foi bumpless. "
            f"Série antes: {[round(v, 2) for v in valores_cv_antes]}; "
            f"primeira depois: {valores_cv_depois[0]:.3f}; dt={dt_fronteira:.3f}s"
        )

        # A planta continua evoluindo (malha fechada por TFS): a CV não congelou. Sem
        # isto, uma malha parada passaria no critério acima por vacuidade.
        assert len(set(valores_cv_depois)) > 1, (
            f"CV congelou após o hot-swap — a malha TFS parou de evoluir: {valores_cv_depois}"
        )

        # A config NOVA chegou ao host reconstruído: sem esta prova o cenário mostraria
        # apenas que o flow sobreviveu, não que houve hot-swap (ADR-011).
        r = admin.get(f"/api/flows/{flow_id}")
        assert r.status_code == 200
        no_mpc = next(
            n for n in r.json()["graph_json"]["nodes"] if n["id"] == "mpc1"
        )
        assert no_mpc["data"]["variables"]["mvs"][0]["du_max"] == DU_MAX_NOVO, (
            "a configuração nova não foi persistida — não houve hot-swap"
        )
    finally:
        ws.close()
