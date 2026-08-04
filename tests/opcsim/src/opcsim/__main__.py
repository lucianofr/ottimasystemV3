"""CLI do opcsim: sobe o servidor de simulação e roda até SIGINT/SIGTERM."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from .server import SECURITY_MODES, SECURITY_NONE, OpcSimServer

_logger = logging.getLogger("opcsim")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="opcsim", description="Servidor OPC-UA de simulação")
    parser.add_argument("--port", type=int, default=4840, help="porta TCP de escuta")
    parser.add_argument("--host", default="0.0.0.0", help="endereço de bind")
    parser.add_argument(
        "--security", choices=SECURITY_MODES, default=SECURITY_NONE, help="modo de segurança"
    )
    parser.add_argument(
        "--cert-dir",
        type=Path,
        default=None,
        help="diretório do certificado do servidor (default: temporário criado no boot)",
    )
    return parser.parse_args(argv)


async def _serve(args: argparse.Namespace) -> None:
    server = OpcSimServer(
        port=args.port, security=args.security, cert_dir=args.cert_dir, host=args.host
    )
    await server.start()
    _logger.info("opcsim ouvindo em %s (segurança: %s)", server.endpoint, args.security)
    if server.cert_der_path is not None:
        _logger.info("certificado do servidor (DER): %s", server.cert_der_path)

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)
    try:
        await shutdown.wait()
    finally:
        await server.stop()
    _logger.info("opcsim encerrado")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_serve(_parse_args(argv)))


if __name__ == "__main__":
    main()
