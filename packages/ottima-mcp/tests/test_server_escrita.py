"""Ferramentas de escrita de operação (Fase 3): `mpc_set_mode`/`mpc_write_sp`/
`mpc_write_mv`/`mpc_state`. Servidor `/ws` REAL local (`cliente_com_ws`) — fixtures de
`MpcState`/evento copiadas dos campos confirmados em `bus.py`/`mpc.py` (comentado no
próprio server.py), nunca inventadas."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from ottima_mcp import server


def _ctx(cliente: Any) -> Any:
    return SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context=SimpleNamespace(cliente=cliente))
    )


def _rota_mpcs_para_timeout(flow_ts_seconds: float, multiplier: int):
    """`_timeout_padrao` chama `GET /api/operate/mpcs` — rota mínima para ela resolver
    sem precisar simular o restante do endpoint de leitura."""

    def _rota(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/operate/mpcs":
            return httpx.Response(
                200,
                json=[
                    {
                        "flow_id": 1,
                        "block_id": "mpc1",
                        "flow_ts_seconds": flow_ts_seconds,
                        "multiplier": multiplier,
                    }
                ],
            )
        return httpx.Response(202)

    return _rota



# ----------------------------------------------------------------------------------
# mpc_set_mode
# ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mpc_set_mode_confirma_por_estado_publicado(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(1.0, 1))

    async def _fluxo():
        return await server.mpc_set_mode(1, "mpc1", "man_auto", "auto", _ctx(cliente))

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.05)
    await hub_ws.publicar(
        "mpc.state.1.mpc1", {"modes": {"local_remote": "remote", "man_auto": "auto"}}
    )
    resultado = await tarefa
    assert resultado["modes"]["man_auto"] == "auto"


@pytest.mark.asyncio
async def test_mpc_set_mode_confirma_por_evento_mesmo_sem_estado_batendo(cliente_com_ws) -> None:
    """Evento `mpc_mode_changed` sozinho já confirma — não depende do próximo `mpc_state`
    chegar antes (fila 8 pode atrasar a próxima fronteira)."""
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(1.0, 1))
    evento = {
        "severity": "info",
        "origin": "flow:1/block:mpc1",
        "message": "modo trocado",
        "payload": {"kind": "mpc_mode_changed", "axis": "man_auto", "to": "auto"},
    }

    async def _fluxo():
        return await server.mpc_set_mode(1, "mpc1", "man_auto", "auto", _ctx(cliente))

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.05)
    await hub_ws.publicar("events", evento)
    resultado = await tarefa
    assert resultado == {}  # nenhum mpc_state chegou; evento já bastou


@pytest.mark.asyncio
async def test_mpc_set_mode_mpc_arm_failed_e_falha_rapida(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(1.0, 1))
    evento = {
        "severity": "warning",
        "origin": "flow:1/block:mpc1",
        "message": "armar falhou",
        "payload": {"kind": "mpc_arm_failed", "axis": "man_auto", "reason": "cold_input"},
    }

    async def _fluxo():
        return await server.mpc_set_mode(1, "mpc1", "man_auto", "auto", _ctx(cliente))

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.05)
    await hub_ws.publicar("events", evento)
    with pytest.raises(RuntimeError, match="cold_input"):
        await tarefa


@pytest.mark.asyncio
async def test_mpc_set_mode_man_auto_em_local_diagnostico_adr010(cliente_com_ws) -> None:
    """Sem nenhum evento nem mudança de estado (comando silenciosamente ignorado pelo
    runtime, mpc.py:1001-1002) — o tempo esgota, mas o erro cita ADR-010, não 'timeout'."""
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(0.05, 1))

    async def _fluxo():
        return await server.mpc_set_mode(1, "mpc1", "man_auto", "auto", _ctx(cliente), timeout=0.2)

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    # única publicação: o estado real (LOCAL) — nunca confirma o pedido de man_auto=auto.
    await hub_ws.publicar(
        "mpc.state.1.mpc1", {"modes": {"local_remote": "local", "man_auto": "man"}}
    )
    with pytest.raises(RuntimeError, match="ADR-010"):
        await tarefa


# ----------------------------------------------------------------------------------
# mpc_write_sp
# ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mpc_write_sp_confirma_por_evento(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(1.0, 1))
    evento = {
        "severity": "info",
        "origin": "flow:1/block:mpc1",
        "message": "SP escrito",
        "payload": {"kind": "mpc_sp_written", "var_id": "cv_a", "value": 55.0, "user": "user:7"},
    }

    async def _fluxo():
        return await server.mpc_write_sp(1, "mpc1", "cv_a", 55.0, _ctx(cliente))

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.05)
    await hub_ws.publicar("events", evento)
    resultado = await tarefa
    assert resultado == {}


@pytest.mark.asyncio
async def test_mpc_write_sp_confirma_sem_evento_novo_por_retry_idempotente(cliente_com_ws) -> None:
    """Simula o caso `mpc.py:1043-1044`: o comando já foi aplicado antes (nenhum evento
    NOVO sai), mas `vars.sp` já publicado no valor pedido confirma mesmo assim."""
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(1.0, 1))

    async def _fluxo():
        return await server.mpc_write_sp(1, "mpc1", "cv_a", 55.0, _ctx(cliente))

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.05)
    # só mpc_state, nenhum evento — sp já está no valor pedido (retry pós-idempotência).
    await hub_ws.publicar(
        "mpc.state.1.mpc1",
        {
            "modes": {"local_remote": "remote", "man_auto": "auto"},
            "vars": {"cv_a": {"v": 54.9, "sp": 55.0}},
        },
    )
    resultado = await tarefa
    assert resultado["vars"]["cv_a"]["sp"] == 55.0


@pytest.mark.asyncio
async def test_mpc_write_sp_fora_de_auto_diagnostico(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(0.05, 1))

    async def _fluxo():
        return await server.mpc_write_sp(1, "mpc1", "cv_a", 55.0, _ctx(cliente), timeout=0.2)

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    await hub_ws.publicar(
        "mpc.state.1.mpc1",
        {
            "modes": {"local_remote": "remote", "man_auto": "man"},
            "vars": {"cv_a": {"v": 50.0, "sp": 50.0}},
        },
    )
    with pytest.raises(RuntimeError, match="REMOTO\\+AUTO"):
        await tarefa


# ----------------------------------------------------------------------------------
# mpc_write_mv
# ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mpc_write_mv_confirma_so_por_evento_v_divergente_nao_impede(cliente_com_ws) -> None:
    """`v` (mv_last) ainda em rampa por max_rate — NÃO impede o sucesso, porque o
    predicado de MV nunca olha `v`, só o evento (ADR-028)."""
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(1.0, 1))
    evento = {
        "severity": "info",
        "origin": "flow:1/block:mpc1",
        "message": "MV escrita",
        "payload": {"kind": "mpc_mv_written", "var_id": "mv_a", "value": 80.0, "user": "user:7"},
    }

    async def _fluxo():
        return await server.mpc_write_mv(1, "mpc1", "mv_a", 80.0, _ctx(cliente))

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    # v ainda longe do alvo (rampa) — publicado ANTES do evento, não deve confirmar sozinho.
    await hub_ws.publicar(
        "mpc.state.1.mpc1",
        {"modes": {"local_remote": "remote", "man_auto": "man"}, "vars": {"mv_a": {"v": 22.0}}},
    )
    await asyncio.sleep(0.02)
    await hub_ws.publicar("events", evento)
    resultado = await tarefa
    # confirmou pelo evento; o estado anexo mostra v ainda em rampa (22.0 != 80.0) — honesto.
    assert resultado["vars"]["mv_a"]["v"] == 22.0


@pytest.mark.asyncio
async def test_mpc_write_mv_v_coincidente_sem_evento_nao_confirma(cliente_com_ws) -> None:
    """`v` bater o valor pedido por coincidência (ex.: processo já estava lá) NÃO deve
    confirmar sem o evento — provaria que o predicado ignora `v` mesmo a favor."""
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(0.05, 1))

    async def _fluxo():
        return await server.mpc_write_mv(1, "mpc1", "mv_a", 80.0, _ctx(cliente), timeout=0.2)

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    await hub_ws.publicar(
        "mpc.state.1.mpc1",
        {"modes": {"local_remote": "remote", "man_auto": "man"}, "vars": {"mv_a": {"v": 80.0}}},
    )
    with pytest.raises(RuntimeError):  # tempo esgota — nenhum evento chegou
        await tarefa


@pytest.mark.asyncio
async def test_mpc_write_mv_fora_de_remoto_man_diagnostico_adr010(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(0.05, 1))

    async def _fluxo():
        return await server.mpc_write_mv(1, "mpc1", "mv_a", 80.0, _ctx(cliente), timeout=0.2)

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    await hub_ws.publicar(
        "mpc.state.1.mpc1",
        {"modes": {"local_remote": "local", "man_auto": "man"}, "vars": {"mv_a": {"v": 10.0}}},
    )
    with pytest.raises(RuntimeError, match="ADR-010"):
        await tarefa


@pytest.mark.asyncio
async def test_mpc_write_mv_remoto_man_sem_evento_diagnostico_idempotencia(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(0.05, 1))

    async def _fluxo():
        return await server.mpc_write_mv(1, "mpc1", "mv_a", 80.0, _ctx(cliente), timeout=0.2)

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    await hub_ws.publicar(
        "mpc.state.1.mpc1",
        {"modes": {"local_remote": "remote", "man_auto": "man"}, "vars": {"mv_a": {"v": 10.0}}},
    )
    with pytest.raises(RuntimeError, match="idempotente"):
        await tarefa


# ----------------------------------------------------------------------------------
# mpc_state
# ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mpc_state_devolve_a_primeira_publicacao(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(1.0, 1))

    async def _fluxo():
        return await server.mpc_state(1, "mpc1", _ctx(cliente))

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.05)
    await hub_ws.publicar(
        "mpc.state.1.mpc1", {"modes": {"local_remote": "remote", "man_auto": "auto"}}
    )
    resultado = await tarefa
    assert resultado["modes"]["man_auto"] == "auto"


# ----------------------------------------------------------------------------------
# Isolamento por origem: `events` é canal GLOBAL — sem filtrar `origin`, o evento de
# OUTRO bloco com o mesmo kind/var_id confirmaria falsamente (achado de revisão).
# ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mpc_write_sp_ignora_evento_de_outro_bloco_mesmo_kind_e_var_id(
    cliente_com_ws,
) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(0.05, 1))
    evento_de_outro_bloco = {
        "severity": "info",
        "origin": "flow:1/block:mpc2",  # bloco DIFERENTE, mesmo flow
        "message": "SP escrito",
        "payload": {"kind": "mpc_sp_written", "var_id": "cv_a", "value": 55.0, "user": "user:7"},
    }

    async def _fluxo():
        return await server.mpc_write_sp(1, "mpc1", "cv_a", 55.0, _ctx(cliente), timeout=0.2)

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    await hub_ws.publicar("events", evento_de_outro_bloco)
    with pytest.raises(RuntimeError, match="REMOTO\\+AUTO"):  # tempo esgota, nao confirma
        await tarefa


@pytest.mark.asyncio
async def test_mpc_write_mv_ignora_evento_de_outro_bloco_mesmo_kind_e_var_id(
    cliente_com_ws,
) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(0.05, 1))
    evento_de_outro_flow = {
        "severity": "info",
        "origin": "flow:9/block:mpc1",  # mesmo block_id, flow DIFERENTE
        "message": "MV escrita",
        "payload": {"kind": "mpc_mv_written", "var_id": "mv_a", "value": 80.0, "user": "user:7"},
    }

    async def _fluxo():
        return await server.mpc_write_mv(1, "mpc1", "mv_a", 80.0, _ctx(cliente), timeout=0.2)

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    await hub_ws.publicar("events", evento_de_outro_flow)
    with pytest.raises(RuntimeError):  # tempo esgota, nao confirma
        await tarefa


@pytest.mark.asyncio
async def test_mpc_set_mode_ignora_mpc_arm_failed_de_outro_bloco(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(_rota_mpcs_para_timeout(0.05, 1))
    falha_de_outro_bloco = {
        "severity": "warning",
        "origin": "flow:1/block:mpc2",
        "message": "armar falhou",
        "payload": {"kind": "mpc_arm_failed", "axis": "man_auto", "reason": "cold_input"},
    }

    async def _fluxo():
        return await server.mpc_set_mode(1, "mpc1", "man_auto", "auto", _ctx(cliente), timeout=0.2)

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    await hub_ws.publicar("events", falha_de_outro_bloco)
    with pytest.raises(RuntimeError):  # tempo esgota (nao e falha rapida) — origem nao bate
        await tarefa
