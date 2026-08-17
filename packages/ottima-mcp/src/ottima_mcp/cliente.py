"""Cliente HTTP autenticado para a API REST do OttimaSystem (ADR-036).

Um cliente como o frontend: nenhuma validação de domínio aqui — a API é a fronteira. Erros
4xx/5xx viram `ErroOttima` com a string `detail` do backend verbatim (shape
`{"detail": "<string>"}`, garantido pelo handler global de validação —
`services/api/src/ottima_api/app.py`, `packages/ottima-core/src/ottima_core/schemas/auth.py`
para o shape de login).
"""

from __future__ import annotations

from typing import Any

import httpx

from ottima_mcp.config import Config


class ErroOttima(RuntimeError):
    """Erro de domínio devolvido pela API (4xx/5xx). `mensagem` é o `detail` verbatim —
    string única em pt-BR, nunca lista (spec F5 §4.3-1)."""

    def __init__(self, mensagem: str, status_code: int) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status_code = status_code


class ClienteOttima:
    """Sessão HTTP autenticada contra a API do OttimaSystem.

    Exatamente um re-login seguido de exatamente um retry em 401 — nunca loop (o login tem
    rate-limit de 30 req/min por IP no nginx, `frontend/nginx.conf`)."""

    def __init__(
        self, config: Config, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        """`transport` é o hook padrão do httpx para injetar `httpx.MockTransport` em teste
        (sem rede); produção nunca passa este argumento (usa o transporte HTTP real)."""
        self._config = config
        self._http = httpx.AsyncClient(base_url=config.url, timeout=10.0, transport=transport)

    @classmethod
    async def conectar(
        cls, config: Config, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> ClienteOttima:
        """Cria o cliente e faz o login inicial.

        Uso: `cliente = await ClienteOttima.conectar(cfg)`.
        """
        cliente = cls(config, transport=transport)
        await cliente._login()
        return cliente

    async def fechar(self) -> None:
        await self._http.aclose()

    @property
    def url(self) -> str:
        return self._config.url

    @property
    def token(self) -> str | None:
        """JWT vigente sem o prefixo `Bearer ` — para quem monta a URL do `/ws`
        (`?token=<jwt>`, `confirmacao.py`), que não fala REST/headers."""
        cabecalho = self._http.headers.get("Authorization")
        return cabecalho.removeprefix("Bearer ") if cabecalho else None

    async def reautenticar(self) -> None:
        """Login de novo, forçando um JWT fresco. Uso: sessão WS fechada com 1008 (token
        expirado) — REST já reloga sozinho em 401 (`_chamar`); o `/ws` não tem esse retry
        embutido no protocolo, então quem espera confirmação (`confirmacao.py`) chama isto
        explicitamente antes de tentar reconectar, exatamente uma vez."""
        await self._login()

    async def get(self, path: str, **params: Any) -> Any:
        """Query params `None` são omitidos — chamadores passam filtros opcionais direto
        como kwargs (ex.: `start=None`) sem montar o dict à mão."""
        filtrados = {chave: valor for chave, valor in params.items() if valor is not None}
        return await self._chamar("GET", path, params=filtrados)

    async def post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        return await self._chamar("POST", path, json=json)

    async def put(self, path: str, json: dict[str, Any] | None = None) -> Any:
        return await self._chamar("PUT", path, json=json)

    async def delete(self, path: str) -> Any:
        return await self._chamar("DELETE", path)

    async def _login(self) -> None:
        resposta = await self._http.post(
            "/api/auth/login",
            json={"username": self._config.username, "password": self._config.password},
        )
        if resposta.status_code >= 400:
            raise ErroOttima(_extrair_detail(resposta), resposta.status_code)
        corpo = resposta.json()
        self._http.headers["Authorization"] = f"Bearer {corpo['access_token']}"

    async def _chamar(
        self,
        metodo: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        _apos_relogin: bool = False,
    ) -> Any:
        resposta = await self._http.request(metodo, path, params=params, json=json)
        if resposta.status_code == 401 and not _apos_relogin:
            await self._login()
            return await self._chamar(
                metodo, path, params=params, json=json, _apos_relogin=True
            )
        if resposta.status_code >= 400:
            raise ErroOttima(_extrair_detail(resposta), resposta.status_code)
        if resposta.status_code in (202, 204) or not resposta.content:
            return None
        return resposta.json()


def _extrair_detail(resposta: httpx.Response) -> str:
    """`detail` string única, garantida pelo handler global de 4xx/5xx (spec F5 §4.3-1).
    Corpo sem `detail`/JSON inválido não deveria acontecer nesta API — repassa algo útil
    como diagnóstico em vez de estourar aqui dentro."""
    try:
        corpo = resposta.json()
    except ValueError:
        return resposta.text or f"Erro HTTP {resposta.status_code} sem corpo"
    detail = corpo.get("detail") if isinstance(corpo, dict) else None
    return detail if isinstance(detail, str) else str(corpo)
