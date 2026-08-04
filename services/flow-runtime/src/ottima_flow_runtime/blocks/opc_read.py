"""Bloco OPC-Read: uma tag do espelho do barramento vira uma porta de saída (RF-501, §3.1).

Não abre sessão OPC-UA — o `opc-worker` é o único processo que fala OPC (ADR-006). Aqui só
se lê o espelho alimentado por `opc.values.*` (tarefa 1.1), que é síncrono e O(1).
"""

from collections.abc import Mapping
from typing import Literal

from ..snapshot import ValueSnapshot
from .base import Block, PortSample


class OpcReadBlock(Block):
    """Sem entradas; saída `out`.

    Invalidez (§3.1) é conservadora: `quality != 0` invalida a porta (uncertain inclusive),
    mas o valor lido continua propagado — quem decide o que fazer com ele é o bloco a
    jusante (decisão A-6). Tag ausente do espelho é cold start: `(None, False)`.
    """

    def __init__(
        self,
        block_id: str,
        *,
        tag_id: int,
        data_type: Literal["float", "int", "bool"],
        snapshot: ValueSnapshot,
    ) -> None:
        super().__init__(block_id)
        self._tag_id = tag_id
        self._is_bool = data_type == "bool"
        self._snapshot = snapshot

    @property
    def output_ports(self) -> tuple[str, ...]:
        return ("out",)

    async def step(self, inputs: Mapping[str, PortSample]) -> dict[str, PortSample]:
        tag_value = self._snapshot.get(self._tag_id)
        if tag_value is None:
            return {"out": PortSample(None, False)}
        # A tipagem da porta é a da tag (decisão A-5): tag booleana entrega `bool` do
        # Python, e não 1.0, para o Script e o canvas não terem de adivinhar.
        value = tag_value.value != 0 if self._is_bool else float(tag_value.value)
        return {"out": PortSample(value, tag_value.quality == 0)}
