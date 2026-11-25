"""Comando `soft_sensor_model`: troca do modelo de um bloco em execução (RF-584, spec §5.6).

O runtime carrega o modelo pedido, confere contra o bloco, monta o buffer do candidato (cópia
do buffer em uso no mesmo período; pré-aquecimento pelo histórico em outro), grava
`candidate_model_id` e entrega o candidato ao bloco vivo. Nada levanta para o laço de comandos.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from runtime_test_helpers import (
    QUIET_WINDOW_S,
    USER,
    await_until,
    create_connection,
    create_flow,
    create_project,
    create_tag,
    edge,
    graph,
    node,
)
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import (
    KIND_SOFT_SENSOR_MODEL_REJECTED,
    KIND_SOFT_SENSOR_PREWARM_SKIPPED,
    FlowCommand,
)
from ottima_core.models import SoftSensorBinding, SoftSensorModel, Tag
from ottima_core.signal import Quality
from ottima_core.softsensor import BUFFER_STEPS, load_model, synthetic
from ottima_flow_runtime import soft_sensor_seeds
from ottima_flow_runtime.blocks.base import Signal
from ottima_flow_runtime.blocks.soft_sensor import SoftSensorBlock
from ottima_flow_runtime.soft_sensor_seeds import make_persist, soft_sensor_command

Sessions = async_sessionmaker[AsyncSession]
TS = 1.0
GOOD = Quality.GOOD


class _Events:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, **kwargs: object) -> None:
        self.calls.append(kwargs)

    def kinds(self, kind: str) -> list[dict]:
        return [c for c in self.calls if c["kind"] == kind]


async def _scenario(
    factory: Sessions,
    *pairs: tuple,
    ts: float = TS,
    flow_graph: dict | None = None,
    weights: dict[int, bytes] | None = None,
) -> dict:
    """Projeto, 2 tags, um modelo por par `(meta, blob)` e o vínculo de `ss` sem modelo."""
    project_id = await create_project(factory)
    connection_id = await create_connection(factory, project_id)
    tag_ids = [await create_tag(factory, connection_id, name=f"t{i}") for i in range(2)]
    flow_id = await create_flow(factory, project_id, graph=flow_graph or graph([]), ts_seconds=ts)
    ids: list[int] = []
    async with factory() as session:
        for k, (meta, blob) in enumerate(pairs):
            model = SoftSensorModel(
                project_id=project_id,
                name=f"modelo {k}",
                method=meta.method,
                period_s=meta.period_s,
                n_inputs=len(meta.inputs),
                input_tag_ids=tag_ids,
                meta=meta.model_dump(mode="json"),
                weights=(weights or {}).get(k, blob),
                created_by=USER,
            )
            session.add(model)
            await session.flush()
            ids.append(model.id)
        session.add(SoftSensorBinding(flow_id=flow_id, block_id="ss", updated_by=USER))
        await session.commit()
    return {"flow_id": flow_id, "tag_ids": tag_ids, "models": ids}


async def _set_binding(factory: Sessions, flow_id: int, **values: int | None) -> None:
    async with factory() as session:
        row = await session.get_one(SoftSensorBinding, (flow_id, "ss"))
        for key, value in values.items():
            setattr(row, key, value)
        await session.commit()


async def _binding(factory: Sessions, flow_id: int) -> tuple[int | None, int | None, int | None]:
    async with factory() as session:
        row = await session.get_one(SoftSensorBinding, (flow_id, "ss"))
        return row.desired_model_id, row.active_model_id, row.candidate_model_id


def _loaded(pair: tuple, model_id: int):
    meta, blob = pair
    return load_model(model_id, meta.model_dump(mode="json"), blob)


def _block(factory: Sessions, flow_id: int, model=None) -> SoftSensorBlock:
    return SoftSensorBlock(
        "ss",
        n_inputs=2,
        ts_seconds=TS,
        model=model,
        prewarm=None,
        missing_reason=None,
        emit_event=_Events(),
        persist=make_persist(factory, flow_id, "ss"),
    )


def _spy(block: SoftSensorBlock) -> list[tuple]:
    calls: list[tuple] = []
    original = block.set_candidate

    def set_candidate(model, buffer):
        calls.append((model, buffer))
        original(model, buffer)

    block.set_candidate = set_candidate  # type: ignore[method-assign]
    return calls


def _runtime(block: object, tipo: str = "soft_sensor_pls") -> SimpleNamespace:
    return SimpleNamespace(blocks={"ss": ({"type": tipo, "n_inputs": 2}, block)}, ts_seconds=TS)


def _command(flow_id: int, model_id: object, block_id: object = "ss") -> FlowCommand:
    return FlowCommand(
        flow_id=flow_id,
        cmd="soft_sensor_model",
        args={"block_id": block_id, "model_id": model_id},
        user=USER,
        ts=datetime.now(UTC),
    )


async def _run(factory: Sessions, runtime, command: FlowCommand, events: _Events | None = None):
    await soft_sensor_command(factory, runtime, command, emit_event=events or _Events())


async def _steps(block: SoftSensorBlock, *values: float) -> None:
    for v in values:
        await block.step({"IN1": Signal(v, quality=GOOD), "IN2": Signal(v + 1, quality=GOOD)})


PLS_A = synthetic.pls([1.0, 1.0], 0.0, period_s=1.0)
PLS_B = synthetic.pls([2.0, 2.0], 0.0, period_s=1.0)
PLS_2S = synthetic.pls([3.0, 3.0], 0.0, period_s=2.0)
ESN = synthetic.esn(2, period_s=1.0)


@pytest.fixture
def no_history(monkeypatch):
    """Mesmo período: o pré-aquecimento não pode nem ser tentado."""

    async def proibido(*args, **kwargs):
        raise AssertionError("load_grid não devia ser chamado")

    monkeypatch.setattr(soft_sensor_seeds, "load_grid", proibido)


# --------------------------------------------------------------------------------------
# Chamada direta do handler (runtime mínimo)
# --------------------------------------------------------------------------------------


async def test_comando_para_bloco_que_nao_e_sensor_virtual_e_ignorado(session_factory):
    scenario = await _scenario(session_factory, PLS_A)
    flow_id, model_id = scenario["flow_id"], scenario["models"][0]
    events = _Events()

    await _run(session_factory, _runtime(object()), _command(flow_id, model_id), events)
    await _run(session_factory, _runtime(object()), _command(flow_id, model_id, "nao_existe"))
    await _run(session_factory, _runtime(object()), _command(flow_id, "lixo"))

    assert events.calls == []
    assert await _binding(session_factory, flow_id) == (None, None, None)


async def test_modelo_inexistente_e_ignorado_sem_tocar_o_vinculo(session_factory):
    scenario = await _scenario(session_factory, PLS_A)
    flow_id, active = scenario["flow_id"], scenario["models"][0]
    block = _block(session_factory, flow_id, _loaded(PLS_A, active))
    calls = _spy(block)
    events = _Events()

    await _run(session_factory, _runtime(block), _command(flow_id, 999_999), events)

    assert calls == [] and events.calls == []
    assert await _binding(session_factory, flow_id) == (None, None, None)


async def test_comando_com_flow_rodando_cria_candidato_e_grava_candidate_model_id(
    session_factory, no_history
):
    scenario = await _scenario(session_factory, PLS_A, PLS_B)
    flow_id, (active, novo) = scenario["flow_id"], scenario["models"]
    await _set_binding(session_factory, flow_id, desired_model_id=novo, active_model_id=active)
    block = _block(session_factory, flow_id, _loaded(PLS_A, active))
    calls = _spy(block)

    await _run(session_factory, _runtime(block), _command(flow_id, novo))

    assert [m.model_id for m, _ in calls] == [novo]
    assert await _binding(session_factory, flow_id) == (novo, active, novo)


async def test_modelo_de_metodo_errado_e_rejeitado_e_o_desejado_volta_ao_ativo(
    session_factory,
):
    scenario = await _scenario(session_factory, PLS_A, ESN)
    flow_id, (active, esn) = scenario["flow_id"], scenario["models"]
    await _set_binding(session_factory, flow_id, desired_model_id=esn, active_model_id=active)
    block = _block(session_factory, flow_id, _loaded(PLS_A, active))
    calls = _spy(block)
    events = _Events()

    await _run(session_factory, _runtime(block), _command(flow_id, esn), events)

    assert calls == []
    assert await _binding(session_factory, flow_id) == (active, active, None)
    rejected = events.kinds(KIND_SOFT_SENSOR_MODEL_REJECTED)
    assert [c["payload"] for c in rejected] == [
        {"block_id": "ss", "model_id": esn, "reason": "method"}
    ]
    assert rejected[0]["severity"] == "warning"


async def test_artefato_corrompido_sem_modelo_em_uso_devolve_o_desejado_a_nulo(session_factory):
    scenario = await _scenario(session_factory, PLS_A, weights={0: b"lixo"})
    flow_id, corrompido = scenario["flow_id"], scenario["models"][0]
    await _set_binding(session_factory, flow_id, desired_model_id=corrompido)
    block = _block(session_factory, flow_id)
    calls = _spy(block)
    events = _Events()

    await _run(session_factory, _runtime(block), _command(flow_id, corrompido), events)

    assert calls == []
    assert await _binding(session_factory, flow_id) == (None, None, None)
    reasons = [c["payload"]["reason"] for c in events.kinds(KIND_SOFT_SENSOR_MODEL_REJECTED)]
    assert reasons == ["corrupt"]


async def test_periodo_recusado_pelo_bloco_rejeita_e_limpa_o_candidato(session_factory):
    scenario = await _scenario(session_factory, PLS_A, PLS_B)
    flow_id, (active, novo) = scenario["flow_id"], scenario["models"]
    await _set_binding(session_factory, flow_id, desired_model_id=novo, active_model_id=active)
    block = _block(session_factory, flow_id, _loaded(PLS_A, active))

    def recusa(model, buffer):
        raise ValueError("período do modelo menor que o Ts")

    block.set_candidate = recusa  # type: ignore[method-assign]
    events = _Events()

    await _run(session_factory, _runtime(block), _command(flow_id, novo), events)

    assert await _binding(session_factory, flow_id) == (active, active, None)
    reasons = [c["payload"]["reason"] for c in events.kinds(KIND_SOFT_SENSOR_MODEL_REJECTED)]
    assert reasons == ["period"]


async def test_mesmo_periodo_herda_copia_do_buffer_do_ativo(session_factory, no_history):
    scenario = await _scenario(session_factory, PLS_A, PLS_B)
    flow_id, (active, novo) = scenario["flow_id"], scenario["models"]
    block = _block(session_factory, flow_id, _loaded(PLS_A, active))
    await _steps(block, 1.0, 2.0, 3.0)
    calls = _spy(block)

    await _run(session_factory, _runtime(block), _command(flow_id, novo))

    [(_, buffer)] = calls
    expected = block.active_buffer_copy()
    assert buffer is not None and len(buffer) == len(expected) == 3
    rows, qualities = buffer.last(3)
    expected_rows, expected_qualities = expected.last(3)
    np.testing.assert_array_equal(rows, expected_rows)
    assert qualities == expected_qualities
    await _steps(block, 4.0)  # ativo e candidato empurram uma vez cada: compartilhado daria 5
    assert len(buffer) == 4


async def test_periodo_diferente_preaquece_pelo_historico(session_factory, monkeypatch):
    scenario = await _scenario(session_factory, PLS_A, PLS_2S)
    flow_id, (active, lento) = scenario["flow_id"], scenario["models"]
    block = _block(session_factory, flow_id, _loaded(PLS_A, active))
    await _steps(block, 1.0, 2.0)
    pedidos: list[tuple[datetime, float]] = []

    async def grade(session, tag_ids, *, end, period_s, steps):
        pedidos.append((end, period_s))
        return np.full((steps, len(tag_ids)), 7.0), [GOOD] * steps

    monkeypatch.setattr(soft_sensor_seeds, "load_grid", grade)
    calls = _spy(block)

    antes = datetime.now(UTC)
    await _run(session_factory, _runtime(block), _command(flow_id, lento))
    depois = datetime.now(UTC)

    [(end, period_s)] = pedidos
    assert period_s == 2.0
    assert antes - timedelta(seconds=2.0) <= end <= depois - timedelta(seconds=2.0)
    [(model, buffer)] = calls
    assert model.model_id == lento
    assert buffer is not None and len(buffer) == BUFFER_STEPS  # nunca o buffer do ativo (2)
    assert set(buffer.last(BUFFER_STEPS)[1]) == {GOOD}


async def test_sem_modelo_em_uso_preaquece_pelo_historico(session_factory, monkeypatch):
    scenario = await _scenario(session_factory, PLS_A)
    flow_id, novo = scenario["flow_id"], scenario["models"][0]
    block = _block(session_factory, flow_id)

    async def grade(session, tag_ids, *, end, period_s, steps):
        return np.zeros((steps, len(tag_ids))), [GOOD] * steps

    monkeypatch.setattr(soft_sensor_seeds, "load_grid", grade)
    calls = _spy(block)

    await _run(session_factory, _runtime(block), _command(flow_id, novo))

    [(_, buffer)] = calls
    assert buffer is not None and len(buffer) == BUFFER_STEPS


async def test_periodo_diferente_sem_as_tags_entra_vazio_e_avisa(session_factory, no_history):
    scenario = await _scenario(session_factory, PLS_A, PLS_2S)
    flow_id, (active, lento) = scenario["flow_id"], scenario["models"]
    async with session_factory() as session:
        await session.execute(delete(Tag).where(Tag.id == scenario["tag_ids"][1]))
        await session.commit()
    block = _block(session_factory, flow_id, _loaded(PLS_A, active))
    await _steps(block, 1.0)
    calls = _spy(block)
    events = _Events()

    await _run(session_factory, _runtime(block), _command(flow_id, lento), events)

    [(_, buffer)] = calls
    assert buffer is None
    skipped = events.kinds(KIND_SOFT_SENSOR_PREWARM_SKIPPED)
    assert [c["payload"] for c in skipped] == [
        {"block_id": "ss", "model_id": lento, "reason": "tags"}
    ]
    assert await _binding(session_factory, flow_id) == (None, None, lento)


# --------------------------------------------------------------------------------------
# Pelo supervisor e pelo laço de varredura
# --------------------------------------------------------------------------------------

HARNESS_TS = 0.5


def _flow_graph(tipo: str = "soft_sensor_pls") -> dict:
    return graph(
        [
            node("c1", "constant", 1, {"value": 1.0}),
            node("c2", "constant", 2, {"value": 2.0}),
            {
                "id": "ss",
                "type": tipo,
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": 3, "n_inputs": 2, "output_eu": "ppm"},
            },
        ],
        [edge("c1", "out", "ss", "IN1"), edge("c2", "out", "ss", "IN2")],
    )


async def _deployed(harness_factory, session_factory, *pairs, tipo="soft_sensor_pls", desired=0):
    scenario = await _scenario(session_factory, *pairs, ts=HARNESS_TS, flow_graph=_flow_graph(tipo))
    flow_id = scenario["flow_id"]
    if desired is not None:
        await _set_binding(session_factory, flow_id, desired_model_id=scenario["models"][desired])
    harness = await harness_factory()
    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    block = harness.supervisor._runtimes[flow_id].blocks["ss"][1]
    assert isinstance(block, SoftSensorBlock)
    return harness, scenario, block


async def _activate(harness, session_factory, flow_id: int, model_id: int) -> None:
    await _set_binding(session_factory, flow_id, desired_model_id=model_id)  # como a API faz
    await harness.command(
        "soft_sensor_model", flow_id, args={"block_id": "ss", "model_id": model_id}
    )


async def test_comando_com_flow_parado_nao_faz_nada(harness_factory, session_factory):
    harness, scenario, block = await _deployed(harness_factory, session_factory, PLS_A, PLS_B)
    flow_id, (active, novo) = scenario["flow_id"], scenario["models"]
    await harness.command("stop", flow_id)
    await harness.await_state(flow_id, "stopped")

    await _activate(harness, session_factory, flow_id, novo)
    await asyncio.sleep(QUIET_WINDOW_S)

    assert block.active_model_id == active and block.candidate_model_id is None
    assert await _binding(session_factory, flow_id) == (novo, active, None)


async def test_apos_alguns_scans_o_ativo_no_banco_e_o_modelo_novo(harness_factory, session_factory):
    pls_a = synthetic.pls([1.0, 1.0], 0.0, period_s=HARNESS_TS)
    pls_b = synthetic.pls([2.0, 2.0], 0.0, period_s=HARNESS_TS)
    harness, scenario, block = await _deployed(harness_factory, session_factory, pls_a, pls_b)
    flow_id, (active, novo) = scenario["flow_id"], scenario["models"]
    assert block.active_model_id == active

    await _activate(harness, session_factory, flow_id, novo)

    await await_until(lambda: block.active_model_id == novo)

    async def gravado() -> bool:
        return await _binding(session_factory, flow_id) == (novo, novo, None)

    await await_until(gravado)


async def test_sem_modelo_em_uso_o_vinculo_final_e_ativo_sem_candidato(
    harness_factory, session_factory, monkeypatch
):
    """Decisão de ordem: `candidate_model_id` é gravado ANTES do `set_candidate`. Ao contrário,
    sem modelo em uso a varredura promove e grava `(X, None)` antes de a gravação do handler
    chegar, e o vínculo termina `(X, X)`: a página mostraria "aquecendo" para sempre."""
    pls = synthetic.pls([1.0, 1.0], 0.0, period_s=HARNESS_TS)
    harness, scenario, block = await _deployed(harness_factory, session_factory, pls, desired=None)
    flow_id, novo = scenario["flow_id"], scenario["models"][0]
    assert block.active_model_id is None
    original = soft_sensor_seeds.write_binding

    async def lenta(factory, flow_id, block_id, **values):
        if set(values) == {"candidate_model_id"}:  # só a gravação do handler
            await asyncio.sleep(3 * HARNESS_TS)
        await original(factory, flow_id, block_id, **values)

    monkeypatch.setattr(soft_sensor_seeds, "write_binding", lenta)
    monkeypatch.setattr(soft_sensor_seeds, "load_grid", _empty_grid)

    await _activate(harness, session_factory, flow_id, novo)

    await await_until(lambda: block.active_model_id == novo)
    async with harness.supervisor._lock:  # o handler terminou (gravação incluída)
        pass
    await asyncio.gather(*block._writes)  # e a gravação da promoção também
    assert await _binding(session_factory, flow_id) == (novo, novo, None)


async def _empty_grid(session, tag_ids, *, end, period_s, steps):
    return np.zeros((steps, len(tag_ids))), [GOOD] * steps
