"""Camada L2 da F4b (spec F4 §9.2, tarefa 4.2): overrun, devolver e `/operate`.

Três cenários (E2E-F4-06..08). E2E-F4-06 reutiliza a malha `grafo_mpc_tfs`/`_config_mpc_malha`
só quando faz sentido (07/08, que precisam do `pid` físico via opcsim) — o overrun (06) usa um
config PRÓPRIO, propositalmente pesado (dimensão>150, Np=120, Ts_mpc=0,5s — brief da tarefa),
com MVs diretas (sem `pid`): não precisa de malha física pra provar que o orçamento estoura, e
evita disputar a tag física de escrita (`NODE_W_FLOAT`) com os outros cenários do arquivo.

Bench do config pesado (rodado à parte, direto contra `mpc/worker.py._build_runtime`/`_solve`
dentro do container `flow-runtime`, mesmo ambiente do E2E): um config com dimensão=170 (2 MVs
× 6 linhas) às vezes deixava um solve escapar por baixo do orçamento — o "SP == medição" no
instante de entrar em AUTO (PV-tracking congelado, spec §4.4) é um ótimo quase trivial (mover a
MV pioraria o custo), e IPOPT ocasionalmente convergia rápido demais nesse caso degenerado. No
teto de MVs+linhas (4×6=24 pares, dimensão=340) o solve fica CONSISTENTE em ~13-17s (testado
3x, com SP trivial e não-trivial) — ~40-50x o orçamento de 0,7×0,5=0,35s, contra um build de
~8s (bem dentro do boot de 30s do `MpcHost`). Ver o relatório da tarefa pros números completos.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from opcsim import NODE_W_FLOAT, NODE_W_INT
from ottima_core.bus import KIND_MPC_OVERRUN

from .conftest import (
    BASE,
    DU_MAX_MV,
    LIMITES_MV,
    LIMITES_SP_CV,
    TS_MPC,
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
    operar_modo,
    operar_mv,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e


# --------------------------------------------------------------------------------------
# Config pesado do E2E-F4-06 — Ts_flow=0,5, multiplier=1 (Ts_mpc=0,5s), Np=120, dimensão=340
# --------------------------------------------------------------------------------------

_TS_FLOW_PESADO = 0.5
_TSS_PESADO = 60.0
"""Np = ceil(60/0,5) = 120 — exatamente no teto §2.2-5 (Np>120 seria 422)."""
_THETA_PESADO = 6.0
"""round(6,0/0,5)=12 amostras de atraso por par habilitado."""
_N_MV_PESADO = 4
_N_ROWS_PESADO = 6
# dimensão = n_MV + n_rows×n_MV×(2 [SOPDT] + round(theta/Ts_mpc)) = 4 + 6×4×14 = 340 (>150,
# spec §2.2-7; teto de MVs/linhas §2.2-2) — bench (3 rodadas, SP trivial e não-trivial) mede
# solve consistente em ~13-17s, ~40-50x o orçamento de 0,35s; build ~8s, dentro do boot de 30s.
_MV_IDS_PESADO = tuple(f"mv_h{i}" for i in range(_N_MV_PESADO))
_CV_IDS_PESADO = tuple(f"cv_h{i}" for i in range(_N_ROWS_PESADO))


def _config_mpc_pesado() -> dict:
    mvs = [
        {
            "id": mv_id,
            "name": f"MV pesada {mv_id}",
            "eu": "%",
            "limits": dict(LIMITES_MV),
            "du_max": DU_MAX_MV,
            "initial_value": 0.0,
        }
        for mv_id in _MV_IDS_PESADO
    ]
    cvs = [
        {
            "id": cv_id,
            "name": f"CV pesada {cv_id}",
            "eu": "C",
            "kind": "selfreg",
            "tss": _TSS_PESADO,
            "weight": 1.0,
            "sp_limits": dict(LIMITES_SP_CV),
        }
        for cv_id in _CV_IDS_PESADO
    ]
    modelos = {
        cv_id: {
            mv_id: {
                "enabled": True,
                "params": {"K": 1.0, "tau1": 10.0, "tau2": 2.0, "theta": _THETA_PESADO},
            }
            for mv_id in _MV_IDS_PESADO
        }
        for cv_id in _CV_IDS_PESADO
    }
    return {
        "name": "MPC pesado E2E-F4-06",
        "multiplier": 1,
        "variables": {"mvs": mvs, "cvs": cvs, "constraints": [], "dvs": []},
        "models": modelos,
    }


def _grafo_overrun(admin: httpx.Client, ambiente: AmbienteMpc, *, mpc_id: str = "mpc1") -> dict:
    """Cada CV recebe um `opc_read` dummy (`NODE_SINE`, mesmo padrão de `_grafo_validacao` em
    `test_f4_mpc.py`) — só pra satisfazer "entrada obrigatória" (spec §2.1-5); o cenário não
    depende de dinâmica real, só de o solve nunca caber no orçamento."""
    dados = _config_mpc_pesado()
    nodes: list[dict] = []
    edges: list[dict] = []
    for indice, cv in enumerate(dados["variables"]["cvs"], start=1):
        tag_id = criar_tag_leitura_dummy(admin, ambiente.conn_id, f"ov-in-{indice}")
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
                "targetHandle": cv["id"],
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
# E2E-F4-06 — ACEITE: overrun mantém MV + alarme (PRD §8-F4)
# --------------------------------------------------------------------------------------


def test_e2e_f4_06_overrun_mantem_mv_e_alarme(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    eventos: EventStream,
) -> None:
    """E2E-F4-06 (aceite PRD §8-F4, spec §4.2/§4.9): o config pesado nunca cabe no orçamento
    de 0,7×Ts_mpc=0,35s (bench: solve consistente em ~13-17s, ~40-50x o orçamento, 15
    tentativas sem exceção) — todo disparo em AUTO estoura, mata o worker e repõe; a MV
    nunca sai do `initial_value` e o contador de overruns/respawns cresce.

    DEFEITO FIXADO (originalmente achado nesta tarefa, corrigido no nível do bloco antes do
    fechamento da fase): `MpcBlock.reset()` inicializava `_solver_status = "ok"`, e
    `_build_state()` expunha esse valor cru sempre que `host.ready` — mesmo sem NENHUM solve
    real ter terminado ainda, mostrando `status.solver=="ok"` por 1-2 amostras ANTES do 1º
    overrun ser detectado. Corrigido em `blocks/mpc.py`: `reset()` agora inicializa
    `_solver_status` como `"idle"` (não `"ok"`), e `_build_state()` ganhou um gate de defesa
    em profundidade — `status=="ok"` sem `self._plan` aplicado não é exposto como "ok" (mantém
    o rótulo honesto anterior). Coberto em
    `test_mpc_block.py::test_solver_status_nao_e_ok_antes_do_primeiro_resultado_real`.

    Este E2E continua a assertar sobre `last_solve_ms` (tempo real do filho,
    `MpcHost._last_solve_ms`), não sobre o enum `status.solver`: é a prova de verdade de que
    nenhum plano jamais foi aplicado — só vira >0 quando o filho responde de verdade, e a MV,
    que só sai do hold quando `self._plan is not None` (`_compute_outputs`), só é setada
    dentro de um `status=="ok"` DE VERDADE (`_apply_result`), nunca alcançado neste cenário.
    `last_solve_ms` prova o comportamento físico independente do rótulo do enum — mesmo com o
    defeito acima já corrigido, este é o sinal mais direto do orçamento estourado."""
    flow_id = criar_flow_mpc(
        "f4-06", ts_seconds=_TS_FLOW_PESADO, grafo=_grafo_overrun(admin, ambiente_mpc)
    )

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        fluxo.esperar(
            lambda e: e["modes"]["local_remote"] == "local", timeout=30.0, descricao="boot em LOCAL"
        )

        armar_remoto_direto(admin, fluxo, flow_id, "mpc1")
        armar_auto_com_retentativa(admin, fluxo, flow_id, "mpc1", timeout=60.0)

        evento = eventos.esperar(
            evento_mpc(KIND_MPC_OVERRUN, flow_id, "mpc1"),
            timeout=15.0,
            descricao="mpc_overrun após o 1º disparo em AUTO",
        )

        antes = mpc_block_health(flow_id, "mpc1")
        assert antes is not None, "flow-runtime não reportou saúde do bloco mpc1"

        janela = fluxo.coletar(
            quantidade=20, timeout=40.0, descricao="janela de ciclos overrun/respawn"
        )

        def _cresceu() -> dict[str, Any] | None:
            saude = mpc_block_health(flow_id, "mpc1")
            if saude is None:
                return None
            cresceu_overruns = saude["overruns"] > antes["overruns"]
            cresceu_respawns = saude["worker"]["respawns"] > antes["worker"]["respawns"]
            return saude if (cresceu_overruns and cresceu_respawns) else None

        depois = esperar_ate(
            _cresceu, timeout=40.0, intervalo=2.0, descricao="overruns e respawns crescerem"
        )

    assert evento["severity"] == "warning"
    assert set(evento["payload"]) == {"kind", "overruns"}
    assert evento["payload"]["kind"] == KIND_MPC_OVERRUN
    assert isinstance(evento["payload"]["overruns"], int)
    assert evento["payload"]["overruns"] >= 1

    # MV congelada: `initial_value=0.0` o tempo todo — mesmo nas amostras rotuladas "ok"
    # pelo defeito acima, a MV nunca se move (a prova física independe do rótulo).
    for var_id in _MV_IDS_PESADO:
        valores = [e["vars"][var_id]["v"] for e in janela]
        assert all(v == 0.0 for v in valores), f"{var_id} não ficou congelada em 0.0: {valores}"

    # Nenhum solve DE VERDADE jamais completa a tempo — a prova é `last_solve_ms` (tempo
    # real do filho), não `status.solver` (contaminado pelo defeito documentado acima).
    tempos_de_solve = [e["status"]["last_solve_ms"] for e in janela]
    assert all(t == 0.0 for t in tempos_de_solve), (
        f"algum last_solve_ms > 0 — um solve completou dentro do orçamento: {tempos_de_solve}"
    )

    assert depois["overruns"] > antes["overruns"]
    assert depois["worker"]["respawns"] > antes["worker"]["respawns"]


# --------------------------------------------------------------------------------------
# E2E-F4-07 — devolver: AUTO→LOCAL congela MV e escreve mode_cmd=auto no opcsim
# --------------------------------------------------------------------------------------


def test_e2e_f4_07_devolver_congela_mv_e_escreve_mode_cmd_auto(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F4-07 (spec §9.2/§4.4): REMOTO(AUTO)→LOCAL escreve `mode_cmd=mode_values.auto`
    no PID físico (`NODE_W_INT` do opcsim) e a MV congela — a saída do bloco passa a ser o
    readback (§4.3), e ninguém mais está escrevendo nele (`_write_pid` só escreve em
    REMOTO), então os `mpc.state` seguintes trazem o MESMO valor de `mv_pid`."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f4-07", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        fluxo.esperar(
            lambda e: e["modes"]["local_remote"] == "local", timeout=30.0, descricao="boot em LOCAL"
        )

        armar_ate_remoto(admin, fluxo, flow_id, "mpc1")
        armar_auto_com_retentativa(admin, fluxo, flow_id, "mpc1")

        # Deixa o AUTO rodar algumas execuções pra ter um "vigente" de verdade (não o valor
        # recém-armado do bumpless).
        pre_local = fluxo.coletar(
            quantidade=3, timeout=TS_MPC * 3 + 10.0, descricao="AUTO antes de devolver"
        )
        vigente = pre_local[-1]["vars"]["mv_pid"]["v"]

        operar_modo(admin, flow_id, "mpc1", "local_remote", "local")
        pos_local = fluxo.coletar(
            quantidade=5, timeout=TS_MPC * 5 + 10.0, descricao="janela pós-devolução"
        )

    # Modo materializou LOCAL a partir da 1ª amostra pós-comando.
    assert pos_local[0]["modes"]["local_remote"] == "local"

    # MV congelada: nenhum salto no instante da transição, e constante daí em diante.
    primeiro_local = pos_local[0]["vars"]["mv_pid"]["v"]
    assert abs(primeiro_local - vigente) <= DU_MAX_MV + 1e-2, (
        f"salto no instante da devolução: vigente={vigente} -> {primeiro_local}"
    )
    valores_local = [e["vars"]["mv_pid"]["v"] for e in pos_local]
    assert max(valores_local) - min(valores_local) < 1e-6, (
        f"MV não congelou em LOCAL: {valores_local}"
    )

    # `mode_cmd = mode_values.auto` (1, spec §2.1-4 do config da malha) chegou ao opcsim.
    esperar_ate(
        lambda: opcsim_client.read(NODE_W_INT) == 1.0 or None,
        timeout=5.0,
        intervalo=0.5,
        descricao="mode_cmd=auto(1) no opcsim",
    )
    assert opcsim_client.read(NODE_W_INT) == 1.0


# --------------------------------------------------------------------------------------
# E2E-F4-08 — /operate: RBAC, 422 de faixa, mv fora de MAN não materializa
# --------------------------------------------------------------------------------------


def test_e2e_f4_08_operate_rbac_faixa_e_mv_fora_de_man(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F4-08 (spec §9.2/§6.1): sem token ⇒ 401 (o sistema só tem admin/operator, e os
    dois passam em `require_operator` — ADR-015 — então não há um 3º papel pra um 403 de
    verdade aqui; mesmo padrão de RBAC negativo usado pela L2 da F1/F3); valor fora de
    `limits` ⇒ 422; e `mpc_mv` comandado FORA de MAN (aqui, em AUTO) nunca materializa — a
    tag de escrita física do opcsim segue o plano do MPC, nunca o valor comandado."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f4-08", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        fluxo.esperar(
            lambda e: e["modes"]["local_remote"] == "local", timeout=30.0, descricao="boot em LOCAL"
        )

        # (a) RBAC — sem token, `require_operator` reprova antes de qualquer leitura do
        # flow (spec §6.1); o alvo nem precisa existir, mas usamos o flow real por consistência.
        r = httpx.post(
            f"{BASE}/api/operate/{flow_id}/mpc1/mode",
            json={"axis": "local_remote", "value": "remote"},
            timeout=10,
        )
        assert r.status_code == 401, f"sem token deveria ser 401: HTTP {r.status_code} {r.text}"

        # (b) 422 de faixa — mv fora de `limits` (spec §6.1).
        r = admin.post(
            f"/api/operate/{flow_id}/mpc1/mv",
            json={"var_id": "mv_pid", "value": LIMITES_MV["max"] + 500.0},
        )
        assert r.status_code == 422, f"faixa deveria reprovar 422: HTTP {r.status_code} {r.text}"
        assert "fora da faixa" in r.json()["detail"]

        # (c) controle positivo — mv materializa em REMOTO+MAN de verdade (prova que o
        # observador enxerga materialização quando ela deve mesmo acontecer, antes do
        # negativo abaixo — sem isso, um "não materializou" poderia ser um path de
        # observação quebrado, não a regra de modo funcionando).
        armar_ate_remoto(admin, fluxo, flow_id, "mpc1")
        alvo_man = 40.0
        operar_mv(admin, flow_id, "mpc1", "mv_pid", alvo_man)
        materializado = fluxo.esperar(
            lambda e: abs(e["vars"]["mv_pid"]["v"] - alvo_man) < 1e-6,
            timeout=TS_MPC * 3 + 5.0,
            descricao="mv_pid materializar o comando em MAN",
        )
        assert abs(materializado["vars"]["mv_pid"]["v"] - alvo_man) < 1e-6

        # (d) negativo — mv fora de MAN (aqui, em AUTO) NÃO materializa.
        armar_auto_com_retentativa(admin, fluxo, flow_id, "mpc1")
        alvo_fora_de_man = LIMITES_MV["max"]  # 100.0 — bem longe do que o plano em AUTO faria
        operar_mv(admin, flow_id, "mpc1", "mv_pid", alvo_fora_de_man)
        janela = fluxo.coletar(
            quantidade=5, timeout=TS_MPC * 5 + 10.0, descricao="janela pós-comando em AUTO"
        )

    for estado in janela:
        v = estado["vars"]["mv_pid"]["v"]
        assert abs(v - alvo_fora_de_man) > 20.0, (
            f"mv_pid={v} materializou o comando mv fora de MAN (alvo={alvo_fora_de_man})"
        )
    escrita_fisica = opcsim_client.read(NODE_W_FLOAT)
    assert abs(escrita_fisica - alvo_fora_de_man) > 20.0, (
        f"escrita física={escrita_fisica} seguiu o comando mv fora de MAN"
    )
