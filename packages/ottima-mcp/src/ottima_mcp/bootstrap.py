"""Bootstrap da conta `agente` do servidor MCP (ADR-036 Fase 5): `python -m ottima_mcp.bootstrap`.

Autentica como admin (`OTTIMA_ADMIN_USERNAME`/`OTTIMA_ADMIN_PASSWORD` — mesmas variáveis do
`.env` do deploy, `seed.py`) e cria o usuário `agente` via `POST /api/users`
(`routers/users.py:38-53`, papel admin — ADR-036 item 2: token alcança admin, a superfície de
ferramentas é que é curada). Idempotente: 409 "Nome de usuário já em uso" não é erro — a
conta já existe.

Não mexe no seed do backend (`services/api/src/ottima_api/seed.py`) — roda depois do boot,
separado, como qualquer outro cliente autenticado da API.
"""

from __future__ import annotations

import asyncio
import os

import httpx

from ottima_mcp.cliente import ClienteOttima, ErroOttima
from ottima_mcp.config import Config

_ENV_ADMIN_USERNAME = "OTTIMA_ADMIN_USERNAME"
_ENV_ADMIN_PASSWORD = "OTTIMA_ADMIN_PASSWORD"


async def bootstrap(*, transport: httpx.AsyncBaseTransport | None = None) -> None:
    """`transport` é o mesmo hook de teste de `ClienteOttima` (`httpx.MockTransport`,
    sem rede); produção nunca passa este argumento."""
    config = Config.do_ambiente()
    admin_username = os.environ.get(_ENV_ADMIN_USERNAME)
    admin_password = os.environ.get(_ENV_ADMIN_PASSWORD)
    if not admin_username or not admin_password:
        raise SystemExit(
            f"Bootstrap precisa das credenciais do admin: defina {_ENV_ADMIN_USERNAME} e "
            f"{_ENV_ADMIN_PASSWORD} (mesmas variáveis de deploy/.env)."
        )
    admin_config = Config(url=config.url, username=admin_username, password=admin_password)
    cliente = await ClienteOttima.conectar(admin_config, transport=transport)
    try:
        await cliente.post(
            "/api/users",
            json={
                "username": config.username,
                "name": "Agente MCP",
                "password": config.password,
                "role": "admin",
            },
        )
        print(f"Conta '{config.username}' criada.")
    except ErroOttima as erro:
        if erro.status_code == 409:
            print(f"Conta '{config.username}' já existe — nada a fazer.")
        else:
            raise
    finally:
        await cliente.fechar()


def main() -> None:
    asyncio.run(bootstrap())


if __name__ == "__main__":
    main()
