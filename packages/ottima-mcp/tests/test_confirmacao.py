"""`esperar_confirmacao`/`_tentativa`: mecânica genérica do protocolo `/ws` — sucesso por
predicado, falha por predicado, tempo esgotado com o último `MpcState` anexado, e
reautenticação única em 1008 (nunca loop). Servidor `/ws` REAL local (`cliente_com_ws`,
conftest.py) — não um mock que devolve o que o predicado já espera (motivo da correção do
bug de paginação de eventos na Fase 2: um hub falso construído para o teste passar não prova
nada sobre o protocolo real)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from ottima_mcp.confirmacao import ErroConfirmacao, esperar_confirmacao


async def _publicado_apos(hub_ws, canal: str, dado: dict, atraso: float = 0.01):
    async def _publicar() -> None:
        await asyncio.sleep(atraso)
        await hub_ws.publicar(canal, dado)

    return _publicar


@pytest.mark.asyncio
async def test_sucesso_por_predicado_no_canal_relevante(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))
    canal = "mpc.state.1.mpc1"
    publicar = await _publicado_apos(hub_ws, canal, {"modes": {"local_remote": "remote"}})

    estado, falha = await esperar_confirmacao(
        cliente,
        interesses={"mpc_state": ["1/mpc1"]},
        publicar_comando=publicar,
        predicado_sucesso=lambda c, d: c == canal and d["modes"]["local_remote"] == "remote",
        canais_relevantes=(canal,),
        limite_segundos=5.0,
    )
    assert falha is None
    assert estado == {"modes": {"local_remote": "remote"}}


@pytest.mark.asyncio
async def test_mensagem_em_canal_nao_relevante_e_ignorada(cliente_com_ws) -> None:
    """Mensagem que não bate `canais_relevantes` não conta como sucesso nem atualiza o
    último `mpc_state` — só o canal certo importa."""
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))
    canal_certo = "mpc.state.1.mpc1"
    canal_errado = "mpc.state.9.outro"

    async def _publicar() -> None:
        await asyncio.sleep(0.01)
        await hub_ws.publicar(canal_errado, {"modes": {"local_remote": "local"}})
        await asyncio.sleep(0.01)
        await hub_ws.publicar(canal_certo, {"modes": {"local_remote": "remote"}})

    estado, _falha = await esperar_confirmacao(
        cliente,
        interesses={"mpc_state": ["1/mpc1"]},
        publicar_comando=_publicar,
        predicado_sucesso=lambda c, d: d["modes"]["local_remote"] == "remote",
        canais_relevantes=(canal_certo,),
        limite_segundos=5.0,
    )
    assert estado == {"modes": {"local_remote": "remote"}}


@pytest.mark.asyncio
async def test_falha_por_predicado_devolve_o_evento(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))
    evento_falha = {
        "severity": "warning",
        "origin": "flow:1/block:mpc1",
        "message": "falhou",
        "payload": {"kind": "mpc_arm_failed", "axis": "man_auto", "reason": "cold_input"},
    }
    publicar = await _publicado_apos(hub_ws, "events", evento_falha)

    estado, falha = await esperar_confirmacao(
        cliente,
        interesses={"mpc_state": ["1/mpc1"], "events": True},
        publicar_comando=publicar,
        predicado_sucesso=lambda c, d: False,
        predicado_falha=lambda c, d: c == "events" and d["payload"]["kind"] == "mpc_arm_failed",
        canais_relevantes=("mpc.state.1.mpc1", "events"),
        limite_segundos=5.0,
    )
    assert falha == evento_falha
    assert estado is None  # nenhum mpc_state chegou nesta espera


@pytest.mark.asyncio
async def test_tempo_esgotado_anexa_ultimo_mpc_state_observado(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))
    canal = "mpc.state.1.mpc1"

    async def _publicar() -> None:
        await asyncio.sleep(0.01)
        # publica um estado que NUNCA bate o predicado — só para provar que fica anexado.
        await hub_ws.publicar(canal, {"modes": {"local_remote": "local"}})

    with pytest.raises(ErroConfirmacao) as exc_info:
        await esperar_confirmacao(
            cliente,
            interesses={"mpc_state": ["1/mpc1"]},
            publicar_comando=_publicar,
            predicado_sucesso=lambda c, d: d["modes"]["local_remote"] == "remote",
            canais_relevantes=(canal,),
            limite_segundos=0.2,
        )
    assert exc_info.value.ultimo_estado == {"modes": {"local_remote": "local"}}


@pytest.mark.asyncio
async def test_tempo_esgotado_sem_nenhuma_mensagem_ultimo_estado_none(cliente_com_ws) -> None:
    cliente, _hub_rest, _hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))

    async def _publicar() -> None:
        return None

    with pytest.raises(ErroConfirmacao) as exc_info:
        await esperar_confirmacao(
            cliente,
            interesses={"mpc_state": ["1/mpc1"]},
            publicar_comando=_publicar,
            predicado_sucesso=lambda c, d: False,
            canais_relevantes=("mpc.state.1.mpc1",),
            limite_segundos=0.2,
        )
    assert exc_info.value.ultimo_estado is None


@pytest.mark.asyncio
async def test_1008_reautentica_e_repete_a_sequencia_uma_vez(cliente_com_ws) -> None:
    """Primeira conexão recusada com 1008 (token 'vencido'); a reautenticação troca o
    token e a SEGUNDA tentativa (reconexão inteira, inclusive `publicar_comando` de novo)
    tem sucesso — comandos de operação são idempotentes no runtime, repetir é seguro."""
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))
    hub_ws.fechar_com_1008(quantas=1)
    canal = "mpc.state.1.mpc1"
    chamadas_publicar = 0

    async def _publicar() -> None:
        nonlocal chamadas_publicar
        chamadas_publicar += 1
        await asyncio.sleep(0.01)
        await hub_ws.publicar(canal, {"modes": {"local_remote": "remote"}})

    estado, falha = await esperar_confirmacao(
        cliente,
        interesses={"mpc_state": ["1/mpc1"]},
        publicar_comando=_publicar,
        predicado_sucesso=lambda c, d: d["modes"]["local_remote"] == "remote",
        canais_relevantes=(canal,),
        limite_segundos=5.0,
    )
    assert falha is None
    assert estado == {"modes": {"local_remote": "remote"}}
    # publicar_comando roda de novo na tentativa pós-reautenticação — 1a tentativa nem
    # chega a chamar (a recusa 1008 acontece no connect, antes do subscribe/publish).
    assert chamadas_publicar == 1


@pytest.mark.asyncio
async def test_1008_persistente_levanta_erro_sem_loop(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))
    hub_ws.fechar_com_1008(quantas=99)  # recusa qualquer número de tentativas

    async def _publicar() -> None:
        return None

    with pytest.raises(ErroConfirmacao) as exc_info:
        await esperar_confirmacao(
            cliente,
            interesses={"mpc_state": ["1/mpc1"]},
            publicar_comando=_publicar,
            predicado_sucesso=lambda c, d: False,
            canais_relevantes=("mpc.state.1.mpc1",),
            limite_segundos=5.0,
        )
    assert "reautenticar" in exc_info.value.mensagem
    assert exc_info.value.ultimo_estado is None
