"""Bloco OPC-Write: publica `OpcWrite` no barramento (RF-502, spec F3 §3.2, decisão A-6).

O flow-runtime nunca abre sessão OPC-UA (ADR-006): escrever é publicar em `opc.writes` e
deixar o `opc-worker` coagir o Variant da tag (spec F2 §4.3, `bool` ⇒ `value != 0`). Por isso
`value` sai sempre como `float`, inclusive quando a porta traz um `bool` — é o que faz a
saída booleana de Script (decisão A-5) funcionar sem lógica de tipo aqui.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from redis.asyncio import Redis

from ottima_core.bus import CHANNEL_OPC_WRITES, KIND_WRITE_SUPPRESSED, OpcWrite, publish_event

from .base import Block, PortSample

_REASON_COLD = "entrada sem valor"
_REASON_INVALID = "entrada inválida"


class OpcWriteBlock(Block):
    """Entrada `in`, nenhuma saída.

    Supressão (§3.2): entrada nula ou inválida não é publicada — não se escreve 0.0 nem um
    valor de qualidade ruim numa tag de processo. O aviso `write_suppressed` sai **uma vez
    por período** de supressão: a bandeira local re-arma quando a escrita volta a sair, o
    que evita uma rajada de eventos a cada varredura de um flow parado a montante.
    """

    def __init__(
        self,
        block_id: str,
        *,
        tag_id: int,
        conn_id: int,
        flow_id: int,
        redis_client: Redis,
    ) -> None:
        super().__init__(block_id)
        self._tag_id = tag_id
        self._conn_id = conn_id
        self._flow_id = flow_id
        self._redis = redis_client
        # Convenção de origem da fase: evento de bloco carrega o bloco; evento de flow
        # (tarefas 1.4/1.5) usa `flow:<id>` exato, porque a lista do frontend filtra por
        # igualdade nesse `origin`.
        self._source = f"flow:{flow_id}/block:{block_id}"
        self._suppression_reported = False

    @property
    def input_ports(self) -> tuple[str, ...]:
        return ("in",)

    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        reason = _suppression_reason(inputs.get("in"))
        if reason is not None:
            await self._report_suppression(reason)
            return {}

        sample = inputs["in"]
        write = OpcWrite(
            conn_id=self._conn_id,
            tag_id=self._tag_id,
            flow_id=self._flow_id,
            value=float(sample.v),
            source=self._source,
            ts=datetime.now(UTC),
        )
        await self._redis.publish(CHANNEL_OPC_WRITES, write.model_dump_json())
        self._suppression_reported = False
        return {}

    def reset(self) -> None:
        self._suppression_reported = False

    async def _report_suppression(self, reason: str) -> None:
        if self._suppression_reported:
            return
        self._suppression_reported = True
        await publish_event(
            self._redis,
            severity="warning",
            origin=self._source,
            message=f"Escrita na tag {self._tag_id} suprimida: {reason}",
            kind=KIND_WRITE_SUPPRESSED,
            payload={"tag_id": self._tag_id, "reason": reason},
        )


def _suppression_reason(sample: PortSample | None) -> str | None:
    """Motivo da supressão, ou `None` quando a escrita pode sair.

    Entrada ausente do dicionário é grafo sem a aresta obrigatória (a validação já reprova):
    tratada como sem valor, para o bloco nunca inventar um número.
    """
    if sample is None or sample.v is None:
        return _REASON_COLD
    return None if sample.ok else _REASON_INVALID
