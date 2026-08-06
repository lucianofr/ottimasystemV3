"""Bloco Python-Script (RF-511..514, ADR-018, spec F3 §3.3, decisões A-4/A-5/A-6).

O bloco é o dono do `state`: o pool é sem estado, recebe uma cópia picklada e devolve outra.
A cópia-mestre daqui só é substituída em retorno `ok`, então timeout e exceção nunca deixam
a malha com estado meio atualizado.

Falha mantém as saídas **verbatim** — valor e flag `ok` da última varredura boa. Antes do
primeiro sucesso isso é `(None, False)`, que é justamente o que o E2E-F3-10 espera a jusante
(o OPC-Write suprime a escrita e avisa). Uma regra só, dois requisitos atendidos.

Cold start e "manter saídas" não colidem: `ValueSnapshot` nunca remove um valor, então
`v is None` é monotônico — uma entrada que já chegou não volta a ser nula. O portão de cold
start (§3.0) só pode disparar antes do primeiro sucesso, quando as últimas saídas ainda são
nulas de qualquer forma.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from redis.asyncio import Redis

from ottima_core.bus import KIND_SCRIPT_ERROR, KIND_SCRIPT_TIMEOUT, publish_event

from ..script_pool import ScriptPool, ScriptResult
from .base import Block, PortSample, has_cold_input, null_outputs


class ScriptBlock(Block):
    """IN1..INn bivalentes, OUT1..OUTn numéricas.

    Eventos de falha são deduplicados por bloco por período de falha, guardando o último
    `kind` emitido: um script que alterna timeout e exceção avisa nas transições, não a cada
    varredura, e um sucesso re-arma os dois.
    """

    def __init__(
        self,
        block_id: str,
        *,
        code: str,
        n_inputs: int,
        n_outputs: int,
        flow_id: int,
        ts_seconds: float,
        pool: ScriptPool,
        redis_client: Redis,
    ) -> None:
        super().__init__(block_id)
        self._code = code
        self._input_ports = tuple(f"IN{i}" for i in range(1, n_inputs + 1))
        self._output_ports = tuple(f"OUT{i}" for i in range(1, n_outputs + 1))
        self._n_outputs = n_outputs
        self._pool = pool
        self._redis = redis_client
        self._source = f"flow:{flow_id}/block:{block_id}"
        # `float()` explícito: `ts_seconds` vem de um Numeric(4,1) do banco como Decimal, e
        # `Decimal * float` levanta TypeError (armadilha herdada da F1).
        self._timeout_s = 0.7 * float(ts_seconds)
        self._state: Any = {}
        self._last_outputs = null_outputs(self._output_ports)
        self._reported_kind: str | None = None

    @property
    def input_ports(self) -> tuple[str, ...]:
        return self._input_ports

    @property
    def output_ports(self) -> tuple[str, ...]:
        return self._output_ports

    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        if has_cold_input(inputs):
            return null_outputs(self._output_ports)

        # Decisão A-5: bivalência resolvida aqui, o script só vê números. `True` vira 1.0.
        values = {port: float(sample.v) for port, sample in inputs.items()}
        result = await self._pool.run(
            code=self._code,
            inputs=values,
            state=self._state,
            n_outputs=self._n_outputs,
            timeout_s=self._timeout_s,
        )

        if result.status != "ok":
            await self._report_failure(result)
            return dict(self._last_outputs)

        ok = all(sample.ok for sample in inputs.values())  # decisão A-6
        self._state = result.state
        self._last_outputs = {
            port: PortSample(result.outputs[port], ok) for port in self._output_ports
        }
        self._reported_kind = None
        return dict(self._last_outputs)

    def reset(self) -> None:
        self._state = {}
        self._last_outputs = null_outputs(self._output_ports)
        self._reported_kind = None

    async def _report_failure(self, result: ScriptResult) -> None:
        if result.status == "timeout":
            kind = KIND_SCRIPT_TIMEOUT
            message = (
                f"Script do bloco {self.block_id} excedeu o tempo limite de {self._timeout_s:.2f} s"
            )
            payload: dict[str, Any] = {"block_id": self.block_id, "timeout_s": self._timeout_s}
        else:
            kind = KIND_SCRIPT_ERROR
            message = f"Script do bloco {self.block_id} falhou"
            payload = {"block_id": self.block_id, "detail": result.detail}

        if kind == self._reported_kind:
            return
        self._reported_kind = kind
        await publish_event(
            self._redis,
            severity="alarm",
            origin=self._source,
            message=message,
            kind=kind,
            payload=payload,
        )
