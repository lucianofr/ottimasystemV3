"""Bloco Barramento-Publicar: a entrada vai para o canal `flow.exchange` (ADR-042 D1/D2).

Mesma forma do OPC-Write (entrada `in`, nenhuma saída, publica dentro do `step()`), mas sem
tag, sem conexão e sem escrita em planta: o destino é o barramento interno, e do outro lado
está o bloco `bus_subscribe` de outro flow.

Duas diferenças de semântica em relação ao Write, ambas do ADR-042 D3 (emendado por
ADR-043 §6):

- **Cold start não publica** — não há valor a anunciar, e o assinante fica COLD (D4/D6).
  Também não gera evento: enquanto o Write suprimido é uma escrita de controle que deixou de
  sair (fato de operação), aqui a ausência é a partida normal de um flow.
- **Valor inválido publica mesmo assim** — o bloco TRANSPORTA o `Signal` completo da entrada
  verbatim (D9): `quality`, `substatus` e os dois bits de limitação viajam tal como chegaram,
  nunca reinterpretados. Quem decide o que fazer com uma qualidade ruim é o bloco a jusante
  (MPC marca `input_valid=False`, o Write suprime, o filtro propaga).

`period_s` viaja em todo quadro: é o Ts do flow que contém este bloco e é o que permite ao
assinante derivar a validade sem nenhum campo de config (D4).
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from redis.asyncio import Redis

from ottima_core.bus import CHANNEL_FLOW_EXCHANGE, ExchangeValue

from .base import Block, Signal

INPUT_PORTS = ("in",)


class BusPublishBlock(Block):
    """Entrada `in` (bivalente), nenhuma saída."""

    def __init__(
        self,
        block_id: str,
        *,
        key: str,
        ts_seconds: float,
        redis_client: Redis,
    ) -> None:
        super().__init__(block_id)
        self._key = key
        self._period_s = float(ts_seconds)
        self._redis = redis_client

    @property
    def input_ports(self) -> tuple[str, ...]:
        return INPUT_PORTS

    async def step(
        self, inputs: Mapping[str, Signal], *, ts: datetime | None = None
    ) -> dict[str, Signal]:
        sample = inputs.get("in")
        # Entrada ausente do dicionário é grafo sem a aresta obrigatória (a validação já
        # reprova): tratada como cold, para o bloco nunca inventar um número.
        if sample is None or sample.v is None:
            return {}

        value = ExchangeValue(
            key=self._key,
            ts=ts if ts is not None else datetime.now(UTC),
            v=sample.v,
            quality=sample.quality,
            substatus=sample.substatus,
            hi_limited=sample.hi_limited,
            lo_limited=sample.lo_limited,
            period_s=self._period_s,
        )
        await self._redis.publish(CHANNEL_FLOW_EXCHANGE, value.model_dump_json())
        return {}
