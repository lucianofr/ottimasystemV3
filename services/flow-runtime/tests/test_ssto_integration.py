"""Integração SSTO ↔ worker do MPC (ADR-027 §1/§10).

O ponto de costura é UM: de onde vem o SP escrito no `tvp` antes do `make_step`. Nada da
matemática do move plan muda — estes testes existem justamente para provar isso, incluindo o
**fallback**: com `economics` ausente/desligado, o worker se comporta exatamente como na F4.

Testes em processo (sem `spawn`): o alvo é a decisão de SP, não o transporte pelo `Pipe`.
"""

from __future__ import annotations

import numpy as np
import pytest

from ottima_core.bus import SstoRun
from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.mpc import worker as worker_module
from ottima_flow_runtime.mpc.worker import SolveRequest, _build_runtime, _solve
from ottima_flow_runtime.target_calculation.solver import SolverResult

TS_FLOW = 1.0
MULTIPLIER = 2
TSS = 10.0


def _config(
    *,
    economics: dict | None = None,
    kind: str = "selfreg",
    sp_limits: tuple[float, float] = (0.0, 200.0),
    mv_limits: tuple[float, float] = (0.0, 100.0),
) -> MpcConfig:
    par = (
        {"enabled": True, "params": {"K": 2.0, "tau1": 5.0, "tau2": 2.0, "theta": 0.0}}
        if kind == "selfreg"
        else {"enabled": True, "params": {"Ki": 0.4, "theta": 0.0}}
    )
    raw = {
        "name": "ssto_1x1",
        "multiplier": MULTIPLIER,
        "variables": {
            "mvs": [
                {
                    "id": "mv_1",
                    "name": "mv",
                    "eu": "u",
                    "limits": {"min": mv_limits[0], "max": mv_limits[1]},
                    "du_max": 100.0,
                }
            ],
            "cvs": [
                {
                    "id": "cv_1",
                    "name": "cv",
                    "eu": "y",
                    "kind": kind,
                    "tss": TSS,
                    "weight": 1.0,
                    "sp_limits": {"min": sp_limits[0], "max": sp_limits[1]},
                }
            ],
            "constraints": [],
            "dvs": [],
        },
        "models": {"cv_1": par},
    }
    raw["models"] = {"cv_1": {"mv_1": par}}
    if economics is not None:
        raw["economics"] = economics
    return MpcConfig.model_validate(raw)


def _request(*, sp: float = 50.0, y: float = 20.0, u: float = 10.0) -> SolveRequest:
    return SolveRequest(y={"cv_1": y}, u_applied={"mv_1": u}, d={}, sp={"cv_1": sp}, reinit=False)


def _sp_escrito(runtime) -> float:
    """SP de fato escrito no `tvp` do controlador — o valor que o `make_step` enxergou."""
    return float(runtime.built.tvp_template["_tvp", 0, "sp_cv_1"])


# ---------------------------------------------------------------------------------------
# Fallback — o caminho da F4, intocado
# ---------------------------------------------------------------------------------------


def test_sem_economics_o_worker_nao_monta_ssto():
    runtime = _build_runtime(_config(), TS_FLOW)

    assert runtime.ssto is None


def test_sem_economics_o_sp_e_o_do_operador():
    runtime = _build_runtime(_config(), TS_FLOW)

    result = _solve(runtime, _request(sp=50.0))

    assert _sp_escrito(runtime) == pytest.approx(50.0)
    assert result.ssto is None
    assert result.status == "ok"


def test_economics_desabilitado_tambem_cai_no_fallback():
    runtime = _build_runtime(
        _config(economics={"enabled": False, "costs": {"mv_1": -1.0}}), TS_FLOW
    )

    result = _solve(runtime, _request(sp=50.0))

    assert runtime.ssto is None
    assert _sp_escrito(runtime) == pytest.approx(50.0)
    assert result.ssto is None


# ---------------------------------------------------------------------------------------
# SSTO ligado — o alvo substitui o SP do operador
# ---------------------------------------------------------------------------------------


def test_com_ssto_o_sp_vira_o_alvo_calculado():
    """Preço negativo na MV empurra até o limite duro (100) — com a faixa da CV folgada, é
    o limite de MV que segura, e o alvo de CV é o que resulta dele."""
    runtime = _build_runtime(
        _config(economics={"enabled": True, "costs": {"mv_1": -1.0}}, sp_limits=(0.0, 1e6)),
        TS_FLOW,
    )

    result = _solve(runtime, _request(sp=50.0, y=20.0, u=10.0))

    assert runtime.ssto is not None
    assert result.ssto is not None
    assert result.ssto.status == "optimal"
    assert result.ssto.mv_target["mv_1"] == pytest.approx(100.0)
    # O SP do operador (50) foi ignorado: quem manda agora é o alvo.
    assert _sp_escrito(runtime) != pytest.approx(50.0)
    assert _sp_escrito(runtime) == pytest.approx(result.ssto.cv_target["cv_1"])


def test_alvo_e_limitado_pelos_sp_limits_da_cv():
    """`sp_limits` é a faixa admissível do alvo (ADR-027 §5) — o LP não pode entregar SP
    fora dela, e o clamp final é a defesa em profundidade."""
    runtime = _build_runtime(
        _config(
            economics={"enabled": True, "costs": {"mv_1": -1.0}},
            sp_limits=(0.0, 90.0),
            mv_limits=(0.0, 1000.0),
        ),
        TS_FLOW,
    )

    _solve(runtime, _request(sp=10.0, y=0.0, u=0.0))

    assert _sp_escrito(runtime) == pytest.approx(90.0)


def test_registro_de_auditoria_vem_completo():
    runtime = _build_runtime(_config(economics={"enabled": True, "costs": {"mv_1": -1.0}}), TS_FLOW)

    result = _solve(runtime, _request())

    run = result.ssto
    assert isinstance(run, SstoRun)
    assert len(run.run_id) == 36  # uuid4 canônico
    assert len(run.config_hash) == 64
    assert len(run.model_hash) == 64
    assert run.solver == "highs"
    assert run.mv == {"mv_1": 10.0}
    assert run.bias  # bias DMC do ciclo, não vazio
    assert run.costs == {"mv_1": -1.0}


def test_cada_execucao_tem_run_id_proprio():
    runtime = _build_runtime(_config(economics={"enabled": True, "costs": {"mv_1": -1.0}}), TS_FLOW)

    primeiro = _solve(runtime, _request()).ssto
    segundo = _solve(runtime, _request()).ssto

    assert primeiro is not None and segundo is not None
    assert primeiro.run_id != segundo.run_id


def test_cv_integradora_mantem_o_sp_do_operador():
    """Linha integradora não tem alvo de NÍVEL (ADR-027 §4): o LP só decide a taxa, então o
    SP dela continua sendo o do operador. Trocar por uma taxa seria erro de unidade."""
    runtime = _build_runtime(
        _config(economics={"enabled": True, "costs": {"mv_1": -1.0}}, kind="integrating"),
        TS_FLOW,
    )

    result = _solve(runtime, _request(sp=50.0))

    assert result.ssto is not None
    assert _sp_escrito(runtime) == pytest.approx(50.0)


# ---------------------------------------------------------------------------------------
# Falha do SSTO — fallback para o SP do operador
# ---------------------------------------------------------------------------------------


class _BackendQuebrado:
    """Duplo de `SolverBackend` que sempre falha — a interface plugável serve também para
    forçar o caminho de erro sem inventar um problema numericamente patológico."""

    name = "quebrado"

    def solve(self, c, a_ub, b_ub, bounds, quadratic=None) -> SolverResult:
        return SolverResult(
            status="error",
            x=np.zeros(0),
            objective=0.0,
            active_constraints=(),
            active_bounds=(),
            duals=np.zeros(0),
            bound_duals=np.zeros(0),
            solver=self.name,
            solve_ms=0.1,
            detail="falha simulada",
        )


def test_ssto_que_falha_devolve_o_sp_do_operador_e_registra_o_status():
    runtime = _build_runtime(_config(economics={"enabled": True, "costs": {"mv_1": -1.0}}), TS_FLOW)
    runtime.ssto._backend = _BackendQuebrado()  # noqa: SLF001 - injeção de falha do teste

    result = _solve(runtime, _request(sp=50.0))

    assert _sp_escrito(runtime) == pytest.approx(50.0)
    assert result.ssto is not None
    assert result.ssto.status == "error"
    assert result.status == "ok"  # o MPC dinâmico segue rodando: fallback, não parada


def test_excecao_no_ssto_nao_derruba_o_solve(monkeypatch):
    """Fronteira dura: qualquer falha inesperada da camada econômica cai no SP do operador —
    o controlador dinâmico nunca para por causa do otimizador."""
    runtime = _build_runtime(_config(economics={"enabled": True, "costs": {"mv_1": -1.0}}), TS_FLOW)

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime.ssto, "solve", explode)

    result = _solve(runtime, _request(sp=50.0))

    assert result.status == "ok"
    assert _sp_escrito(runtime) == pytest.approx(50.0)
    assert result.ssto is None


def test_dv_anterior_e_lembrada_entre_execucoes():
    """O `ΔDV` do ciclo é medido contra a DV da execução ANTERIOR (ADR-027 §2) — quem
    guarda esse estado é o runtime do worker, não o otimizador."""
    raw = _config(economics={"enabled": True, "costs": {"mv_1": -1.0}}).model_dump()
    raw["variables"]["dvs"] = [{"id": "dv_1", "name": "dv", "eu": "u"}]
    raw["models"]["cv_1"]["dv_1"] = {
        "enabled": True,
        "params": {"K": 1.0, "tau1": 5.0, "tau2": 2.0, "theta": 0.0},
    }
    runtime = _build_runtime(MpcConfig.model_validate(raw), TS_FLOW)

    pedido = SolveRequest(
        y={"cv_1": 20.0}, u_applied={"mv_1": 10.0}, d={"dv_1": 5.0}, sp={"cv_1": 50.0}, reinit=False
    )
    _solve(runtime, pedido)

    assert runtime.ssto_dv_prev == {"dv_1": 5.0}


def test_worker_module_nao_importa_do_mpc_no_target_calculation():
    """Separação física das camadas (ADR-027 §1): o pacote do SSTO não conhece do-mpc."""
    import ottima_flow_runtime.target_calculation.ssto as ssto_module

    fonte = ssto_module.__file__
    with open(fonte, encoding="utf-8") as fh:
        conteudo = fh.read()
    assert "do_mpc" not in conteudo
    assert worker_module is not None
