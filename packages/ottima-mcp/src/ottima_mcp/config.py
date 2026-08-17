"""Configuração do servidor MCP via variáveis de ambiente (ADR-036).

Sem defaults mágicos: as três variáveis são obrigatórias. Falta de qualquer uma é erro de
partida com mensagem clara — um servidor MCP que sobe sem saber falar com a API é pior que um
que recusa subir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_ENV_URL = "OTTIMA_URL"
_ENV_USERNAME = "OTTIMA_MCP_USERNAME"
_ENV_PASSWORD = "OTTIMA_MCP_PASSWORD"


class ConfiguracaoAusente(RuntimeError):
    """Variável de ambiente obrigatória não definida na partida do servidor."""


@dataclass(frozen=True)
class Config:
    """Configuração resolvida do ambiente. `url` nunca termina em `/` (normalizado)."""

    url: str
    username: str
    password: str

    @classmethod
    def do_ambiente(cls) -> Config:
        return cls(
            url=_obrigatoria(_ENV_URL).rstrip("/"),
            username=_obrigatoria(_ENV_USERNAME),
            password=_obrigatoria(_ENV_PASSWORD),
        )


def _obrigatoria(nome: str) -> str:
    valor = os.environ.get(nome)
    if not valor:
        raise ConfiguracaoAusente(
            f"Variável de ambiente obrigatória '{nome}' não definida. "
            + f"O servidor MCP precisa de {_ENV_URL}, {_ENV_USERNAME} e {_ENV_PASSWORD} "
            + "para falar com a API do OttimaSystem (ADR-036)."
        )
    return valor
