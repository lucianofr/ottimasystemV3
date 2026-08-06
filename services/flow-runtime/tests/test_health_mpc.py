"""`/health` expõe MPC por bloco e `script_pool` (spec F4 §4.10, plano F4b tarefa 2.3).

Unitário, no padrão de `test_health.py`: app cru (sem lifespan), `app.state.supervisor` e
`app.state.runtime_state` são dublês — sem subir Redis/banco/processos reais.
"""

from httpx import ASGITransport, AsyncClient

from ottima_flow_runtime.main import app
from ottima_flow_runtime.state import RuntimeState


class _StubFlowMetrics:
    """Satisfaz `FlowMetrics` com o mínimo para `FlowSnapshot.of()`."""

    state = "running"
    scan_ms = 12.5
    overruns = 0
    last_scan_ts = None


class _StubSupervisor:
    """Dublê do `Supervisor`: só a superfície que o `/health` consulta."""

    def __init__(self, mpc_by_flow: dict[int, dict], pool_stats: dict) -> None:
        self._mpc_by_flow = mpc_by_flow
        self._pool_stats = pool_stats

    def mpc_health(self, flow_id: int) -> dict:
        return self._mpc_by_flow.get(flow_id, {})

    def script_pool_stats(self) -> dict:
        return self._pool_stats


async def _get_health() -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    return r.json()


async def test_health_expoe_mpc_por_bloco_e_script_pool():
    runtime_state = RuntimeState()
    runtime_state.track(1, _StubFlowMetrics())
    mpc_health = {
        "mpc_a1b2": {
            "mode": {"local_remote": "remote", "man_auto": "auto"},
            "overruns": 2,
            "last_solve_ms": 87.3,
            "worker": {"alive": True, "respawns": 1, "last_solve_ms": 87.3},
        }
    }
    pool_stats = {"size": 4, "busy": 1, "respawns": 0}
    app.state.runtime_state = runtime_state
    app.state.supervisor = _StubSupervisor({1: mpc_health}, pool_stats)
    try:
        body = await _get_health()
    finally:
        del app.state.runtime_state, app.state.supervisor

    flow_health = body["flows"]["1"]
    assert flow_health["mpc"] == mpc_health
    assert flow_health["mpc"]["mpc_a1b2"]["worker"]["alive"] is True
    assert flow_health["mpc"]["mpc_a1b2"]["worker"]["respawns"] == 1
    assert body["script_pool"] == pool_stats


async def test_health_flow_sem_bloco_mpc_tem_dict_vazio():
    runtime_state = RuntimeState()
    runtime_state.track(2, _StubFlowMetrics())
    app.state.runtime_state = runtime_state
    app.state.supervisor = _StubSupervisor({}, {"size": 4, "busy": 0, "respawns": 0})
    try:
        body = await _get_health()
    finally:
        del app.state.runtime_state, app.state.supervisor

    assert body["flows"]["2"]["mpc"] == {}


async def test_health_sem_supervisor_script_pool_vazio():
    """Sem lifespan (app cru), `script_pool` cai no default vazio — mesmo padrão de `flows`."""
    body = await _get_health()
    assert body["script_pool"] == {}
