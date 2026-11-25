"""Carga do modelo no deploy e pré-aquecimento pelo histórico (SPEC_SENSOR_VIRTUAL §5.6-5, §5.7).

O deploy carrega `desired_model_id`, iguala `active_model_id` e enche o buffer a partir de
`samples`; modelo ruim nunca derruba o deploy (o bloco sobe sem modelo e avisa).
"""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from runtime_test_helpers import (
    USER,
    create_connection,
    create_flow,
    create_project,
    create_tag,
    edge,
    graph,
    node,
    save_graph,
)
from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import KIND_SOFT_SENSOR_MODEL_MISSING, KIND_SOFT_SENSOR_PREWARM_SKIPPED
from ottima_core.flowgraph import parse_graph
from ottima_core.models import SoftSensorBinding, SoftSensorModel, Tag
from ottima_core.models.timeseries import samples_table
from ottima_core.script_pool import ScriptPool
from ottima_core.signal import Quality
from ottima_core.softsensor import BUFFER_STEPS, load_model, synthetic
from ottima_flow_runtime import soft_sensor_seeds
from ottima_flow_runtime.blocks.base import Signal
from ottima_flow_runtime.blocks.soft_sensor import BindingUpdate, SoftSensorBlock
from ottima_flow_runtime.definition import build_definition, carregar_sp_seeds
from ottima_flow_runtime.soft_sensor_seeds import (
    SoftSensorSeed,
    load_seeds,
    make_persist,
    model_mismatch,
)

Sessions = async_sessionmaker[AsyncSession]
TS = 1.0


class _Events:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, **kwargs: object) -> None:
        self.calls.append(kwargs)

    def kinds(self, kind: str) -> list[dict]:
        return [c for c in self.calls if c["kind"] == kind]


class _RecordingRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def publish(self, channel: str, data: str) -> None:
        self.published.append((channel, json.loads(data)))


class _FakeSnapshot:
    def get(self, tag_id: int) -> None:
        return None


def _node(block_id: str, *, n_inputs: int = 2, tipo: str = "soft_sensor_pls", order: int = 1):
    return {
        "id": block_id,
        "type": tipo,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": order, "n_inputs": n_inputs, "output_eu": "ppm"},
    }


def _graph(*nodes: dict):
    return parse_graph(graph(list(nodes)))


async def _scenario(
    factory: Sessions,
    block_ids: list[str],
    *,
    weights: bytes | None = None,
    n_tags: int = 2,
) -> dict:
    """Projeto, tags, um modelo PLS de 2 entradas por bloco e o vínculo desejando esse modelo."""
    project_id = await create_project(factory)
    connection_id = await create_connection(factory, project_id)
    tag_ids = [await create_tag(factory, connection_id, name=f"t{i}") for i in range(n_tags)]
    flow_id = await create_flow(factory, project_id, graph=graph([]))
    meta, blob = synthetic.pls([1.0, 2.0], 0.5, period_s=1.0)
    models: dict[str, int] = {}
    async with factory() as session:
        for block_id in block_ids:
            model = SoftSensorModel(
                project_id=project_id,
                name=f"modelo {block_id}",
                method="pls",
                period_s=1.0,
                n_inputs=2,
                input_tag_ids=tag_ids[:2],
                meta=meta.model_dump(mode="json"),
                weights=blob if weights is None else weights,
                created_by=USER,
            )
            session.add(model)
            await session.flush()
            models[block_id] = model.id
            session.add(
                SoftSensorBinding(
                    flow_id=flow_id,
                    block_id=block_id,
                    desired_model_id=model.id,
                    updated_by=USER,
                )
            )
        await session.commit()
    return {"flow_id": flow_id, "tag_ids": tag_ids, "models": models}


async def _binding(factory: Sessions, flow_id: int, block_id: str) -> SoftSensorBinding:
    async with factory() as session:
        return await session.get_one(SoftSensorBinding, (flow_id, block_id))


async def _seeds(factory: Sessions, scenario: dict, *nodes: dict, skip=(), events=None):
    return await load_seeds(
        factory,
        scenario["flow_id"],
        _graph(*nodes),
        ts_seconds=TS,
        skip=set(skip),
        emit_event=events if events is not None else _Events(),
    )


def _instantiate(seed: SoftSensorSeed, node: dict, redis: _RecordingRedis) -> SoftSensorBlock:
    staged = build_definition(
        _graph(node),
        {},
        flow_id=99,
        ts_seconds=TS,
        reuse={},
        redis_client=redis,
        pool=ScriptPool(),
        snapshot=_FakeSnapshot(),
        exchange=_FakeSnapshot(),
        soft_sensor_seeds={node["id"]: seed},
    )
    block = staged.blocks[node["id"]][1]
    assert isinstance(block, SoftSensorBlock)
    return block


def test_model_mismatch():
    assert (
        model_mismatch("pls", 2, 5.0, block_type="soft_sensor_esn", n_inputs=2, ts_seconds=1.0)
        == "method"
    )
    assert (
        model_mismatch("pls", 3, 5.0, block_type="soft_sensor_pls", n_inputs=2, ts_seconds=1.0)
        == "n_inputs"
    )
    assert (
        model_mismatch("pls", 2, 5.0, block_type="soft_sensor_pls", n_inputs=2, ts_seconds=2.0)
        == "period"
    )
    assert (
        model_mismatch("pls", 2, 0.5, block_type="soft_sensor_pls", n_inputs=2, ts_seconds=1.0)
        == "period"
    )
    assert (
        model_mismatch("pls", 2, 6.0, block_type="soft_sensor_pls", n_inputs=2, ts_seconds=2.0)
        is None
    )
    # 0,3 / 0,1 = 2,9999999999999996 em float: múltiplo, dentro da tolerância
    assert (
        model_mismatch("pls", 2, 0.3, block_type="soft_sensor_pls", n_inputs=2, ts_seconds=0.1)
        is None
    )


async def test_deploy_carrega_o_desejado_e_grava_o_ativo(session_factory):
    scenario = await _scenario(session_factory, ["ss"])
    async with session_factory() as session:  # candidato antigo pendurado: o deploy limpa
        binding = await session.get_one(SoftSensorBinding, (scenario["flow_id"], "ss"))
        binding.candidate_model_id = scenario["models"]["ss"]
        await session.commit()

    seeds = await _seeds(session_factory, scenario, _node("ss"), _node("livre", order=2))

    assert seeds["ss"].model is not None
    assert seeds["ss"].model.model_id == scenario["models"]["ss"]
    assert seeds["ss"].missing_reason is None
    assert seeds["livre"] == SoftSensorSeed(None, None, "no_model")  # sem vínculo
    binding = await _binding(session_factory, scenario["flow_id"], "ss")  # OUTRA sessão
    assert binding.active_model_id == binding.desired_model_id == scenario["models"]["ss"]
    assert binding.candidate_model_id is None


async def test_vinculo_sem_desejado_sobe_sem_modelo(session_factory):
    scenario = await _scenario(session_factory, ["ss"])
    async with session_factory() as session:
        binding = await session.get_one(SoftSensorBinding, (scenario["flow_id"], "ss"))
        binding.desired_model_id = None
        await session.commit()

    seeds = await _seeds(session_factory, scenario, _node("ss"))

    assert seeds["ss"] == SoftSensorSeed(None, None, "no_model")


async def test_prazo_de_preaquecimento_e_um_so_para_o_deploy(session_factory, monkeypatch):
    scenario = await _scenario(session_factory, ["a", "b", "c"])

    async def lenta(session, tag_ids, *, end, period_s, steps):
        await asyncio.sleep(0.4)
        return np.zeros((steps, len(tag_ids))), [Quality.GOOD] * steps

    monkeypatch.setattr(soft_sensor_seeds, "load_grid", lenta)
    monkeypatch.setattr(soft_sensor_seeds, "PREWARM_TIMEOUT_S", 1.0)
    events = _Events()

    inicio = time.monotonic()
    seeds = await _seeds(
        session_factory,
        scenario,
        _node("a", order=1),
        _node("b", order=2),
        _node("c", order=3),
        events=events,
    )
    decorrido = time.monotonic() - inicio

    assert decorrido < 1.5
    aquecidos = [bid for bid, seed in seeds.items() if seed.prewarm is not None]
    assert len(aquecidos) == 2
    assert all(seed.model is not None for seed in seeds.values())
    skipped = events.kinds(KIND_SOFT_SENSOR_PREWARM_SKIPPED)
    assert [c["payload"]["reason"] for c in skipped] == ["timeout"]
    assert skipped[0]["severity"] == "info"


async def test_sessao_do_chamador_segue_utilizavel_apos_timeout(session_factory, monkeypatch):
    scenario = await _scenario(session_factory, ["ss"])

    async def presa(session, tag_ids, *, end, period_s, steps):
        await session.execute(text("SELECT pg_sleep(10)"))  # cancelada no meio da consulta
        raise AssertionError("não devia terminar")

    monkeypatch.setattr(soft_sensor_seeds, "load_grid", presa)
    monkeypatch.setattr(soft_sensor_seeds, "PREWARM_TIMEOUT_S", 0.3)

    async with session_factory() as session:
        assert await carregar_sp_seeds(session, scenario["flow_id"]) == {}
        seeds = await _seeds(session_factory, scenario, _node("ss"))
        assert seeds["ss"].prewarm is None
        assert await carregar_sp_seeds(session, scenario["flow_id"]) == {}


async def test_deploy_com_historico_integro_preaquece(session_factory):
    scenario = await _scenario(session_factory, ["ss"])
    agora = datetime.now(UTC)
    async with session_factory() as session:
        await session.execute(
            insert(samples_table),
            [
                {"ts": agora - timedelta(seconds=k), "tag_id": tag, "value": float(k), "quality": 0}
                for tag in scenario["tag_ids"]
                for k in range(BUFFER_STEPS + 20)
            ],
        )
        await session.commit()
    events = _Events()

    seeds = await _seeds(session_factory, scenario, _node("ss"), events=events)

    buffer = seeds["ss"].prewarm
    assert buffer is not None and len(buffer) == BUFFER_STEPS
    _, qualities = buffer.last(BUFFER_STEPS)
    assert set(qualities) == {Quality.GOOD}
    assert events.calls == []


async def test_deploy_com_artefato_corrompido_sobe_sem_modelo(session_factory):
    scenario = await _scenario(session_factory, ["ss"], weights=b"lixo")

    seeds = await _seeds(session_factory, scenario, _node("ss"))

    assert seeds["ss"] == SoftSensorSeed(None, None, "corrupt")
    binding = await _binding(session_factory, scenario["flow_id"], "ss")
    assert binding.active_model_id is None
    # Bloco instanciado pelo caminho real: saída sem valor e evento com o motivo.
    redis = _RecordingRedis()
    block = _instantiate(seeds["ss"], _node("ss"), redis)
    out = await block.step({"IN1": Signal(1.0), "IN2": Signal(2.0)})
    assert out["out"].v is None and out["out"].quality is Quality.BAD
    payloads = [p["payload"] for _, p in redis.published]
    assert payloads == [
        {
            "kind": KIND_SOFT_SENSOR_MODEL_MISSING,
            "flow_id": 99,
            "block_id": "ss",
            "reason": "corrupt",
        }
    ]


async def test_reload_com_n_inputs_diferente_do_modelo(session_factory):
    scenario = await _scenario(session_factory, ["ss"])
    node = _node("ss", n_inputs=3)  # flow salvo com uma porta a mais; modelo é de 2

    seeds = await _seeds(session_factory, scenario, node)

    assert seeds["ss"] == SoftSensorSeed(None, None, "n_inputs")
    block = _instantiate(seeds["ss"], node, _RecordingRedis())
    out = await block.step({"IN1": Signal(1.0), "IN2": Signal(2.0), "IN3": Signal(3.0)})
    assert out["out"].v is None


async def test_tag_de_entrada_apagada_pula_o_preaquecimento(session_factory):
    scenario = await _scenario(session_factory, ["ss"])
    async with session_factory() as session:
        await session.execute(delete(Tag).where(Tag.id == scenario["tag_ids"][1]))
        await session.commit()
    events = _Events()

    seeds = await _seeds(session_factory, scenario, _node("ss"), events=events)

    assert seeds["ss"].model is not None and seeds["ss"].prewarm is None
    skipped = events.kinds(KIND_SOFT_SENSOR_PREWARM_SKIPPED)
    assert [c["payload"]["reason"] for c in skipped] == ["tags"]
    assert skipped[0]["payload"]["block_id"] == "ss"


async def test_consulta_lenta_pula_o_preaquecimento(session_factory, monkeypatch):
    scenario = await _scenario(session_factory, ["ss"])

    async def lenta(session, tag_ids, *, end, period_s, steps):
        await asyncio.sleep(10)

    monkeypatch.setattr(soft_sensor_seeds, "load_grid", lenta)
    monkeypatch.setattr(soft_sensor_seeds, "PREWARM_TIMEOUT_S", 0.2)
    events = _Events()

    seeds = await _seeds(session_factory, scenario, _node("ss"), events=events)

    assert seeds["ss"].model is not None and seeds["ss"].prewarm is None
    assert [c["payload"]["reason"] for c in events.kinds(KIND_SOFT_SENSOR_PREWARM_SKIPPED)] == [
        "timeout"
    ]


async def test_erro_de_banco_no_preaquecimento_pula_sem_derrubar(session_factory, monkeypatch):
    scenario = await _scenario(session_factory, ["ss"])

    async def quebrada(session, tag_ids, *, end, period_s, steps):
        await session.execute(text("SELECT * FROM tabela_inexistente"))

    monkeypatch.setattr(soft_sensor_seeds, "load_grid", quebrada)
    events = _Events()

    seeds = await _seeds(session_factory, scenario, _node("ss"), events=events)

    assert seeds["ss"].model is not None and seeds["ss"].prewarm is None
    assert [c["payload"]["reason"] for c in events.kinds(KIND_SOFT_SENSOR_PREWARM_SKIPPED)] == [
        "error"
    ]


async def test_bloco_reaproveitado_nao_e_recarregado(session_factory):
    scenario = await _scenario(session_factory, ["ss", "novo"])

    seeds = await _seeds(
        session_factory, scenario, _node("ss"), _node("novo", order=2), skip={"ss"}
    )

    assert set(seeds) == {"novo"}
    binding = await _binding(session_factory, scenario["flow_id"], "ss")
    assert binding.active_model_id is None  # nem tocado


async def test_persist_grava_o_vinculo_e_devolve_o_desejado(session_factory):
    scenario = await _scenario(session_factory, ["ss", "outro"])
    ativo, rejeitado = scenario["models"]["ss"], scenario["models"]["outro"]
    async with session_factory() as session:
        binding = await session.get_one(SoftSensorBinding, (scenario["flow_id"], "ss"))
        binding.desired_model_id = rejeitado
        await session.commit()
    persist = make_persist(session_factory, scenario["flow_id"], "ss")

    await persist(BindingUpdate(active_model_id=ativo, candidate_model_id=rejeitado))
    binding = await _binding(session_factory, scenario["flow_id"], "ss")
    assert (binding.active_model_id, binding.candidate_model_id) == (ativo, rejeitado)
    assert binding.desired_model_id == rejeitado

    await persist(BindingUpdate(ativo, None, reset_desired_to_active=True))
    binding = await _binding(session_factory, scenario["flow_id"], "ss")
    assert (binding.desired_model_id, binding.active_model_id) == (ativo, ativo)
    assert binding.candidate_model_id is None


async def test_build_definition_instancia_o_bloco_com_a_semente():
    meta, blob = synthetic.pls([1.0, 2.0], 0.5, period_s=1.0)
    model = load_model(7, meta.model_dump(mode="json"), blob)

    block = _instantiate(SoftSensorSeed(model, None, None), _node("ss"), _RecordingRedis())

    assert block.active_model_id == 7
    good = Quality.GOOD
    out = await block.step({"IN1": Signal(1.0, quality=good), "IN2": Signal(2.0, quality=good)})
    assert (out["out"].v, out["out"].quality) == (pytest.approx(5.5), Quality.GOOD)


def test_build_definition_recusa_tipo_desconhecido():
    flow_graph = _graph(_node("ss"))
    object.__setattr__(flow_graph.nodes[0], "type", "tipo_inexistente")

    with pytest.raises(ValueError, match="tipo_inexistente"):
        build_definition(
            flow_graph,
            {},
            flow_id=1,
            ts_seconds=TS,
            reuse={},
            redis_client=_RecordingRedis(),
            pool=ScriptPool(),
            snapshot=_FakeSnapshot(),
            exchange=_FakeSnapshot(),
        )


async def test_supervisor_deploy_carrega_o_modelo_vinculado(harness_factory, session_factory):
    scenario = await _scenario(session_factory, ["ss"])
    await save_graph(
        session_factory,
        scenario["flow_id"],
        graph(
            [
                node("c1", "constant", 1, {"value": 1.0}),
                node("c2", "constant", 2, {"value": 2.0}),
                _node("ss", order=3),
            ],
            [edge("c1", "out", "ss", "IN1"), edge("c2", "out", "ss", "IN2")],
        ),
    )
    harness = await harness_factory()

    await harness.command("deploy", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "running")

    block = harness.supervisor._runtimes[scenario["flow_id"]].blocks["ss"][1]
    assert isinstance(block, SoftSensorBlock)
    assert block.active_model_id == scenario["models"]["ss"]
    binding = await _binding(session_factory, scenario["flow_id"], "ss")
    assert binding.active_model_id == scenario["models"]["ss"]
