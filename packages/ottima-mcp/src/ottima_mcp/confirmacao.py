"""Cliente WS efêmero para aguardar a confirmação publicada de um comando de operação
(RNF-05: comandado ≠ confirmado; ADR-036 item 5). Uma sessão por escrita: assina os
interesses ANTES de publicar o comando (o `/ws` não faz replay — sem histórico, quem assina
depois de publicar perde a confirmação), espera o predicado de sucesso/falha bater num canal
relevante ou o limite de tempo vencer, fecha.

Protocolo verificado em `services/api/src/ottima_api/ws.py` e
`packages/ottima-core/src/ottima_core/bus.py` (2026-08-17):
- URL: `ws(s)://<host>/ws?token=<jwt>`, path `/ws` sem barra final (o `location /ws` do nginx
  casa por prefixo; `/ws/` vira 403 — `ws.py:_authenticate`, `canalPrimitivos.ts:52-58`).
- Subscribe (cliente→servidor): `{"subscribe": {"mpc_state": ["<flow_id>/<block_id>"],
  "events": true}}` — formato exato `"<flow_id_dígitos>/<block_id>"` (`ws.py:_pair_ids`,
  `.partition("/")`).
- Envelope (servidor→cliente): `{"channel": "<canal>", "data": {...}}` (`ws.py:_fanout` linha
  259, `_dispatch_events` linha 242 — `json.dumps` idêntico nos dois). Canal de `mpc_state`:
  `mpc.state.<flow_id>.<block_id>` (`bus.py:channel_mpc_state`). Canal de eventos: literal
  `"events"` (`bus.py:CHANNEL_EVENTS`).
- Close 1008 = sessão recusada (token ausente/inválido/expirado); o servidor sempre aceita o
  handshake primeiro e só depois fecha (`ws.py:_authenticate`) — o close chega como
  `ConnectionClosed` no primeiro `recv()`, nunca como falha de handshake. Aqui: reautentica e
  tenta a sequência inteira de novo exatamente uma vez (comandos de operação são idempotentes
  no runtime — `mpc.py:1043-1044`/`:1063-1064` — repetir o POST no retry é seguro).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from ottima_core.bus import CHANNEL_EVENTS
from ottima_mcp.cliente import ClienteOttima

Predicado = Callable[[str, dict[str, Any]], bool]
"""Recebe `(canal, data)` de uma mensagem já filtrada para um canal relevante — o canal
explícito evita inferir `mpc_state` vs `events` pela forma das chaves do payload. Devolve
`True` quando a mensagem confirma (ou recusa) o comando."""


class ErroConfirmacao(RuntimeError):
    """Limite de tempo aguardando confirmação, ou sessão WS recusada mesmo após reautenticar.

    `ultimo_estado` é o `MpcState` mais recente observado na mesma assinatura (pode ser
    `None` se nenhuma publicação de `mpc_state` chegou) — nunca descartado: é o único sinal
    que o chamador tem para diagnosticar o estouro (ex.: `modes.local_remote` para detectar
    o comando silenciosamente ignorado por ADR-010)."""

    def __init__(self, mensagem: str, ultimo_estado: dict[str, Any] | None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.ultimo_estado = ultimo_estado


class _SessaoRecusada(Exception):
    """Sentinela interno: 1008 recebido — `esperar_confirmacao` reautentica e tenta de novo
    exatamente uma vez; nunca escapa desta função."""


def _url_ws(cliente: ClienteOttima) -> str:
    esquema = "wss" if cliente.url.startswith("https://") else "ws"
    resto = cliente.url.split("://", 1)[1]
    return f"{esquema}://{resto}/ws?token={cliente.token}"


async def _tentativa(
    cliente: ClienteOttima,
    *,
    interesses: dict[str, Any],
    publicar_comando: Callable[[], Awaitable[None]],
    predicado_sucesso: Predicado,
    predicado_falha: Predicado | None,
    canais_relevantes: tuple[str, ...],
    limite_segundos: float,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    ultimo_estado: dict[str, Any] | None = None
    try:
        async with websockets.connect(_url_ws(cliente)) as ws:
            await ws.send(json.dumps({"subscribe": interesses}))
            await publicar_comando()
            async with asyncio.timeout(limite_segundos):
                while True:
                    bruta = await ws.recv()
                    try:
                        mensagem = json.loads(bruta)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    canal = mensagem.get("channel")
                    dado = mensagem.get("data")
                    if canal not in canais_relevantes or not isinstance(dado, dict):
                        continue
                    if canal != CHANNEL_EVENTS:
                        ultimo_estado = dado
                    if predicado_sucesso(canal, dado):
                        return ultimo_estado, None
                    if predicado_falha is not None and predicado_falha(canal, dado):
                        return ultimo_estado, dado
    except ConnectionClosed as fechado:
        codigo = fechado.rcvd.code if fechado.rcvd else None
        if codigo == 1008:
            raise _SessaoRecusada from None
        raise ErroConfirmacao(
            f"Conexão WS perdida (código {codigo}) aguardando confirmação.", ultimo_estado
        ) from None
    except TimeoutError:
        raise ErroConfirmacao(
            "Tempo esgotado aguardando confirmação do comando.", ultimo_estado
        ) from None


async def esperar_confirmacao(
    cliente: ClienteOttima,
    *,
    interesses: dict[str, Any],
    publicar_comando: Callable[[], Awaitable[None]],
    predicado_sucesso: Predicado,
    predicado_falha: Predicado | None = None,
    canais_relevantes: tuple[str, ...],
    limite_segundos: float,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Assina `interesses` no `/ws`, publica o comando (`publicar_comando`), espera
    `predicado_sucesso`/`predicado_falha` — cada um recebendo `(canal, data)` — baterem num
    canal de `canais_relevantes` ou `limite_segundos` vencer.

    Devolve `(mpc_state_mais_recente_observado, evento_de_falha_ou_None)`:
    - `evento_de_falha is not None` → o chamador levanta erro com a razão publicada
      (ex.: `mpc_arm_failed{payload.reason}`).
    - Tempo esgotado sem sucesso nem falha → `ErroConfirmacao` com o último `MpcState`
      observado.
    """
    try:
        return await _tentativa(
            cliente,
            interesses=interesses,
            publicar_comando=publicar_comando,
            predicado_sucesso=predicado_sucesso,
            predicado_falha=predicado_falha,
            canais_relevantes=canais_relevantes,
            limite_segundos=limite_segundos,
        )
    except _SessaoRecusada:
        await cliente.reautenticar()
        try:
            return await _tentativa(
                cliente,
                interesses=interesses,
                publicar_comando=publicar_comando,
                predicado_sucesso=predicado_sucesso,
                predicado_falha=predicado_falha,
                canais_relevantes=canais_relevantes,
                limite_segundos=limite_segundos,
            )
        except _SessaoRecusada:
            raise ErroConfirmacao(
                "Sessão WS recusada (token inválido/expirado) mesmo após reautenticar.", None
            ) from None
