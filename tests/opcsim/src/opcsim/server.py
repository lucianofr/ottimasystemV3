"""Servidor OPC-UA de simulação usado pelos testes do opc-worker.

Reproduz o mínimo do comportamento de um PLC: variáveis que mudam sozinhas, tags de
escrita com espelhos de leitura, o rung do watchdog (ADR-009) e nodes de controle que
permitem ao teste congelar o rung ou os valores em runtime.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import socket
import tempfile
from pathlib import Path
from typing import Any

from asyncua import Node, Server, ua
from asyncua.crypto.cert_gen import (
    dump_private_key_as_pem,
    generate_private_key,
    generate_self_signed_app_certificate,
)
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import ExtendedKeyUsageOID

_logger = logging.getLogger(__name__)

NAMESPACE_URI = "urn:ottima:opcsim"
"""URI do namespace dos nodes de simulação; o indice resultante tem de ser 2."""

NAMESPACE_INDEX = 2
"""ns 0 = OPC UA, ns 1 = ApplicationUri do servidor, ns 2 = NAMESPACE_URI."""

APPLICATION_URI = "urn:ottima:opcsim:server"
"""ApplicationUri do servidor. Precisa diferir de NAMESPACE_URI para não ocupar o ns 2."""

SECURITY_NONE = "none"
SECURITY_BASIC256SHA256 = "basic256sha256"
SECURITY_MODES = (SECURITY_NONE, SECURITY_BASIC256SHA256)

NODE_SINE = "ns=2;s=sim.float.sine"
NODE_COUNTER = "ns=2;s=sim.int.counter"
NODE_SQUARE = "ns=2;s=sim.bool.square"
NODE_STATIC = "ns=2;s=sim.float.static"
NODE_W_FLOAT = "ns=2;s=sim.w.float"
NODE_W_INT = "ns=2;s=sim.w.int"
NODE_W_BOOL = "ns=2;s=sim.w.bool"
NODE_MIRROR_FLOAT = "ns=2;s=sim.mirror.float"
NODE_MIRROR_INT = "ns=2;s=sim.mirror.int"
NODE_MIRROR_BOOL = "ns=2;s=sim.mirror.bool"
NODE_WD_FROM_SYSTEM = "ns=2;s=sim.watchdog.from_system"
NODE_WD_TO_SYSTEM = "ns=2;s=sim.watchdog.to_system"
NODE_CTRL_FREEZE_WATCHDOG = "ns=2;s=sim.control.freeze_watchdog"
NODE_CTRL_FREEZE_VALUES = "ns=2;s=sim.control.freeze_values"

VALUES_PERIOD = 0.2
"""Cadência do loop de simulação (senoide, contador, onda quadrada e espelhos)."""

RUNG_PERIOD = 0.05
"""Cadência do rung do watchdog."""

SINE_PERIOD = 60.0
SQUARE_PERIOD = 5.0
COUNTER_WRAP = 1_000_000

# (node id, browse name, valor inicial, tipo, gravável pelo cliente)
_NODES: tuple[tuple[str, str, Any, ua.VariantType, bool], ...] = (
    (NODE_SINE, "sine", 0.0, ua.VariantType.Double, False),
    (NODE_COUNTER, "counter", 0, ua.VariantType.Int32, False),
    (NODE_SQUARE, "square", False, ua.VariantType.Boolean, False),
    (NODE_STATIC, "static", 42.0, ua.VariantType.Double, False),
    (NODE_W_FLOAT, "w_float", 0.0, ua.VariantType.Double, True),
    (NODE_W_INT, "w_int", 0, ua.VariantType.Int32, True),
    (NODE_W_BOOL, "w_bool", False, ua.VariantType.Boolean, True),
    (NODE_MIRROR_FLOAT, "mirror_float", 0.0, ua.VariantType.Double, False),
    (NODE_MIRROR_INT, "mirror_int", 0, ua.VariantType.Int32, False),
    (NODE_MIRROR_BOOL, "mirror_bool", False, ua.VariantType.Boolean, False),
    (NODE_WD_FROM_SYSTEM, "wd_from_system", False, ua.VariantType.Boolean, True),
    (NODE_WD_TO_SYSTEM, "wd_to_system", False, ua.VariantType.Boolean, False),
    (NODE_CTRL_FREEZE_WATCHDOG, "freeze_watchdog", False, ua.VariantType.Boolean, True),
    (NODE_CTRL_FREEZE_VALUES, "freeze_values", False, ua.VariantType.Boolean, True),
)

_VARIANT_TYPES: dict[str, ua.VariantType] = {node[0]: node[3] for node in _NODES}

# Tags de escrita e seus espelhos de leitura, na ordem (origem, espelho).
_MIRRORS: tuple[tuple[str, str], ...] = (
    (NODE_W_FLOAT, NODE_MIRROR_FLOAT),
    (NODE_W_INT, NODE_MIRROR_INT),
    (NODE_W_BOOL, NODE_MIRROR_BOOL),
)


def free_port() -> int:
    """Reserva e devolve uma porta TCP livre no loopback, para servidores in-process."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def _generate_certificate(cert_dir: Path) -> tuple[Path, Path]:
    """Gera o par chave/certificado autoassinado do servidor. Bloqueante (RSA 2048)."""
    cert_dir.mkdir(parents=True, exist_ok=True)
    der_path = cert_dir / "opcsim.der"
    key_path = cert_dir / "opcsim.key.pem"

    key = generate_private_key()
    certificate = generate_self_signed_app_certificate(
        key,
        common_name="opcsim",
        names={"organizationName": "OttimaSystem"},
        subject_alt_names=[
            x509.UniformResourceIdentifier(APPLICATION_URI),
            x509.DNSName(socket.gethostname()),
        ],
        extended=[ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH],
    )
    key_path.write_bytes(dump_private_key_as_pem(key))
    der_path.write_bytes(certificate.public_bytes(encoding=Encoding.DER))
    return der_path, key_path


class OpcSimServer:
    """Servidor OPC-UA de simulação, utilizável in-process (testes) ou via CLI (container)."""

    def __init__(
        self,
        port: int,
        security: str = SECURITY_NONE,
        cert_dir: Path | None = None,
        host: str = "127.0.0.1",
    ) -> None:
        if security not in SECURITY_MODES:
            raise ValueError(f"modo de segurança desconhecido: {security!r}")
        self._port = port
        self._host = host
        self._security = security
        self._cert_dir = cert_dir
        self._server: Server | None = None
        self._nodes: dict[str, Node] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._tmp_cert_dir: tempfile.TemporaryDirectory[str] | None = None
        self._cert_der_path: Path | None = None
        # Tempo de simulação: só avança quando os valores não estão congelados.
        self._sim_time = 0.0
        # Último valor de from_system já consumido pelo rung.
        self._last_from_system = False

    @property
    def endpoint(self) -> str:
        return f"opc.tcp://{self._host}:{self._port}/ottima/opcsim/"

    @property
    def cert_der_path(self) -> Path | None:
        return self._cert_der_path

    async def start(self) -> None:
        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        server.set_server_name("OttimaSystem opcsim")
        await server.set_application_uri(APPLICATION_URI)

        index = await server.register_namespace(NAMESPACE_URI)
        if index != NAMESPACE_INDEX:
            raise RuntimeError(
                f"namespace {NAMESPACE_URI} registrado no indice {index}, "
                f"esperado {NAMESPACE_INDEX}: os NodeIds do contrato seriam inválidos"
            )

        if self._security == SECURITY_BASIC256SHA256:
            await self._setup_security(server)
        else:
            server.set_security_policy([ua.SecurityPolicyType.NoSecurity])

        await self._create_nodes(server)
        await server.start()
        self._server = server
        self._tasks = [
            asyncio.create_task(self._run_values_loop(), name="opcsim-values"),
            asyncio.create_task(self._run_watchdog_rung(), name="opcsim-watchdog"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        if self._server is not None:
            await self._server.stop()
            self._server = None
        self._nodes = {}
        if self._tmp_cert_dir is not None:
            self._tmp_cert_dir.cleanup()
            self._tmp_cert_dir = None
            self._cert_der_path = None

    async def set_freeze_watchdog(self, value: bool) -> None:
        await self.write(NODE_CTRL_FREEZE_WATCHDOG, value)

    async def set_freeze_values(self, value: bool) -> None:
        await self.write(NODE_CTRL_FREEZE_VALUES, value)

    async def read(self, node_id: str) -> Any:
        """Lê um node no address space do próprio servidor, sem abrir conexão OPC."""
        return await self._node(node_id).read_value()

    async def write(self, node_id: str, value: Any) -> None:
        """Escreve um node no address space do próprio servidor, sem abrir conexão OPC."""
        await self._node(node_id).write_value(value, _VARIANT_TYPES[node_id])

    def _node(self, node_id: str) -> Node:
        try:
            return self._nodes[node_id]
        except KeyError:
            if not self._nodes:
                raise RuntimeError("servidor não iniciado: chame start() antes") from None
            raise KeyError(f"node desconhecido: {node_id}") from None

    async def _setup_security(self, server: Server) -> None:
        cert_dir = self._cert_dir
        if cert_dir is None:
            self._tmp_cert_dir = tempfile.TemporaryDirectory(prefix="opcsim-cert-")
            cert_dir = Path(self._tmp_cert_dir.name)
        der_path, key_path = await asyncio.to_thread(_generate_certificate, cert_dir)
        await server.load_certificate(der_path)
        await server.load_private_key(key_path)
        self._cert_der_path = der_path
        # O endpoint sem segurança continua ativo de propósito: o mesmo container atende
        # aos dois casos do E2E-F2-07 (conexão insegura e conexão Basic256Sha256).
        server.set_security_policy(
            [
                ua.SecurityPolicyType.NoSecurity,
                ua.SecurityPolicyType.Basic256Sha256_Sign,
                ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
            ]
        )
        # Simulador de teste: nenhum validador de certificado de cliente é instalado, de
        # modo que qualquer certificado de cliente é aceito (sem trust list). Deliberado.
        _logger.info("opcsim: certificado do servidor em %s", der_path)

    async def _create_nodes(self, server: Server) -> None:
        objects = server.get_objects_node()
        for node_id, name, initial, variant, writable in _NODES:
            node = await objects.add_variable(
                node_id, f"{NAMESPACE_INDEX}:{name}", initial, variant
            )
            if writable:
                await node.set_writable()
            self._nodes[node_id] = node

    async def _run_values_loop(self) -> None:
        while True:
            await asyncio.sleep(VALUES_PERIOD)
            try:
                if await self.read(NODE_CTRL_FREEZE_VALUES):
                    continue
                self._sim_time += VALUES_PERIOD
                elapsed = self._sim_time
                await self.write(
                    NODE_SINE, 50.0 + 50.0 * math.sin(2.0 * math.pi * elapsed / SINE_PERIOD)
                )
                await self.write(NODE_COUNTER, int(elapsed) % COUNTER_WRAP)
                await self.write(NODE_SQUARE, int(elapsed / SQUARE_PERIOD) % 2 == 1)
                for source, mirror in _MIRRORS:
                    await self.write(mirror, await self.read(source))
            except Exception:
                _logger.exception("opcsim: falha no loop de simulação de valores")

    async def _run_watchdog_rung(self) -> None:
        """Rung do watchdog: cada mudança em from_system inverte to_system (ADR-009)."""
        while True:
            await asyncio.sleep(RUNG_PERIOD)
            try:
                if await self.read(NODE_CTRL_FREEZE_WATCHDOG):
                    # Congelado: a mudança pendente não é consumida, e provoca inversão
                    # imediata assim que o freeze for desligado.
                    continue
                current = await self.read(NODE_WD_FROM_SYSTEM)
                if current == self._last_from_system:
                    continue
                self._last_from_system = current
                await self.write(NODE_WD_TO_SYSTEM, not await self.read(NODE_WD_TO_SYSTEM))
            except Exception:
                _logger.exception("opcsim: falha no rung do watchdog")
