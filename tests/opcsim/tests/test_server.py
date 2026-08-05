"""Testes do opcsim, todos in-process contra o servidor asyncua em porta livre."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from asyncua import Client, ua
from asyncua.crypto.cert_gen import setup_self_signed_certificate
from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from opcsim import (
    NODE_COUNTER,
    NODE_MIRROR_BOOL,
    NODE_MIRROR_FLOAT,
    NODE_MIRROR_INT,
    NODE_SINE,
    NODE_STATIC,
    NODE_W_BOOL,
    NODE_W_FLOAT,
    NODE_W_INT,
    NODE_WD_FROM_SYSTEM,
    NODE_WD_TO_SYSTEM,
    OpcSimServer,
    free_port,
)
from testkit.await_until import await_until

# Cobre vários ciclos do rung (50 ms) e do loop de valores (200 ms): é o tempo mínimo
# para provar que algo NÃO acontece (freeze). Onde há condição a esperar, use await_until.
QUIET_WINDOW = 0.6


@pytest.fixture
async def sim() -> AsyncIterator[OpcSimServer]:
    server = OpcSimServer(port=free_port())
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


async def test_sobe_e_conecta(sim: OpcSimServer) -> None:
    async with Client(sim.endpoint) as client:
        assert await client.get_node(NODE_STATIC).read_value() == 42.0


async def test_vars_variam(sim: OpcSimServer) -> None:
    async with Client(sim.endpoint) as client:
        sine = client.get_node(NODE_SINE)
        counter = client.get_node(NODE_COUNTER)
        first_sine = await sine.read_value()
        first_counter = await counter.read_value()

        await asyncio.sleep(0.5)
        assert await sine.read_value() != first_sine

        await await_until(lambda: _greater_than(counter, first_counter))


async def test_espelhos_refletem_escrita_do_cliente(sim: OpcSimServer) -> None:
    async with Client(sim.endpoint) as client:
        await client.get_node(NODE_W_FLOAT).write_value(12.5, ua.VariantType.Double)
        await client.get_node(NODE_W_INT).write_value(7, ua.VariantType.Int32)
        await client.get_node(NODE_W_BOOL).write_value(True, ua.VariantType.Boolean)

        await await_until(lambda: _equals(client, NODE_MIRROR_FLOAT, 12.5))
        await await_until(lambda: _equals(client, NODE_MIRROR_INT, 7))
        await await_until(lambda: _equals(client, NODE_MIRROR_BOOL, True))


async def test_rung_alterna_a_cada_mudanca_do_sistema(sim: OpcSimServer) -> None:
    async with Client(sim.endpoint) as client:
        from_system = client.get_node(NODE_WD_FROM_SYSTEM)
        expected = await client.get_node(NODE_WD_TO_SYSTEM).read_value()
        assert expected is False

        # Três mudanças em from_system devem produzir três inversões de to_system.
        for written in (True, False, True):
            await from_system.write_value(written, ua.VariantType.Boolean)
            expected = not expected
            await await_until(
                lambda expected=expected: _equals(client, NODE_WD_TO_SYSTEM, expected)
            )

        assert expected is True


async def test_freeze_watchdog_congela_o_rung(sim: OpcSimServer) -> None:
    async with Client(sim.endpoint) as client:
        await sim.set_freeze_watchdog(True)
        before = await client.get_node(NODE_WD_TO_SYSTEM).read_value()

        await client.get_node(NODE_WD_FROM_SYSTEM).write_value(True, ua.VariantType.Boolean)
        await asyncio.sleep(QUIET_WINDOW)
        assert await client.get_node(NODE_WD_TO_SYSTEM).read_value() == before

        # A mudança pendente foi preservada: ao descongelar, o rung inverte de imediato.
        await sim.set_freeze_watchdog(False)
        await await_until(lambda: _equals(client, NODE_WD_TO_SYSTEM, not before))


async def test_freeze_values_congela_a_senoide(sim: OpcSimServer) -> None:
    async with Client(sim.endpoint) as client:
        await sim.set_freeze_values(True)
        # Um ciclo do loop pode estar em curso; espera passar antes de fixar a referência.
        await asyncio.sleep(QUIET_WINDOW)
        frozen = await client.get_node(NODE_SINE).read_value()

        await asyncio.sleep(QUIET_WINDOW)
        assert await client.get_node(NODE_SINE).read_value() == frozen

        await sim.set_freeze_values(False)
        await await_until(lambda: _differs(client, NODE_SINE, frozen))


async def test_erro_de_programacao_no_loop_nao_e_engolido() -> None:
    """O loop tolera só erro de comunicação; bug derruba a task e aparece no stop()."""
    server = OpcSimServer(port=free_port())
    await server.start()
    # Um objeto sem a API de Node faz o loop de valores levantar AttributeError, que não é
    # ua.UaError nem OSError e portanto não pode ser tolerado ciclo após ciclo.
    server._nodes[NODE_SINE] = object()  # type: ignore[assignment]

    await await_until(lambda: _any_task_done(server))
    with pytest.raises(AttributeError):
        await server.stop()
    # Mesmo relançando, o encerramento completou: uma segunda parada é inócua.
    await server.stop()


@pytest.mark.parametrize(
    "mode", [ua.MessageSecurityMode.Sign, ua.MessageSecurityMode.SignAndEncrypt]
)
async def test_modo_seguro_basic256sha256(tmp_path: Path, mode: ua.MessageSecurityMode) -> None:
    server = OpcSimServer(port=free_port(), security="basic256sha256", cert_dir=tmp_path / "srv")
    await server.start()
    try:
        assert server.cert_der_path is not None
        certificate = x509.load_der_x509_certificate(server.cert_der_path.read_bytes())
        assert certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "opcsim"

        client = Client(server.endpoint)
        client_cert, client_key = await _client_credentials(tmp_path, client.application_uri)
        await client.set_security(
            SecurityPolicyBasic256Sha256,
            certificate=str(client_cert),
            private_key=str(client_key),
            server_certificate=str(server.cert_der_path),
            mode=mode,
        )
        async with client:
            assert await client.get_node(NODE_STATIC).read_value() == 42.0
    finally:
        await server.stop()


async def _client_credentials(tmp_path: Path, application_uri: str) -> tuple[Path, Path]:
    cert_path = tmp_path / "client.der"
    key_path = tmp_path / "client.key.pem"
    await setup_self_signed_certificate(
        key_path,
        cert_path,
        application_uri,
        socket.gethostname(),
        [ExtendedKeyUsageOID.CLIENT_AUTH],
        {"organizationName": "OttimaSystem"},
    )
    return cert_path, key_path


async def _any_task_done(server: OpcSimServer) -> bool:
    return any(task.done() for task in server._tasks)


async def _equals(client: Client, node_id: str, expected: Any) -> bool:
    return bool(await client.get_node(node_id).read_value() == expected)


async def _differs(client: Client, node_id: str, reference: Any) -> bool:
    return bool(await client.get_node(node_id).read_value() != reference)


async def _greater_than(node: Any, reference: Any) -> bool:
    return bool(await node.read_value() > reference)
