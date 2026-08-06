"""Protocolo comum dos blocos executáveis e as duas regras de base (spec F3 §3.0).

`step` é `async` porque o laço de varredura é asyncio: o OPC-Write publica no Redis e o
Script (tarefa 1.3) espera o ProcessPool. Read e TFS não dão `await` em nada e não devem —
nenhum bloco pode bloquear o event loop (ADR-004).

`inputs` traz **somente** as portas de entrada conectadas: quem monta o dicionário é o
scheduler, a partir das arestas do grafo. Porta declarada e sem aresta simplesmente não
aparece, e por isso `has_cold_input` não pergunta pelas portas que faltam.

As duas regras de base moram aqui como helpers, não como template method: o OPC-Write não
tem saídas e precisa **ver** a entrada nula para emitir `write_suppressed` (§3.2), então
cada bloco compõe as peças conforme a própria semântica.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PortSample:
    """Valor de uma porta numa varredura.

    `v is None` é cold start (nunca houve valor desde o deploy). `ok=False` é invalidez com
    valor conhecido: o bloco executa com o valor e propaga a flag (decisão A-6).
    """

    v: float | bool | None
    ok: bool


class Block(ABC):
    """Bloco de um flow. `block_id` é o id do nó React Flow (chave do hot-swap, ADR-011)."""

    def __init__(self, block_id: str) -> None:
        self.block_id = block_id

    @property
    def input_ports(self) -> tuple[str, ...]:
        """Handles de entrada declarados (não necessariamente conectados)."""
        return ()

    @property
    def output_ports(self) -> tuple[str, ...]:
        return ()

    @abstractmethod
    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        """Executa uma varredura e devolve os valores das portas de saída.

        `ts` é o instante da fronteira desta varredura — o MESMO relógio publicado em
        `flow.status.ts` (`FlowTask._run`, spec F5 §2.1): o scheduler passa `fired_ts`
        para TODO bloco em toda varredura. A maioria dos blocos não carimba nada por si e
        ignora o parâmetro; hoje só o MPC usa (spec §2.1/§3.5, `ts`/`prediction.ts` de
        `mpc.state`)."""

    # B027: o corpo vazio é o contrato, não um stub — o OPC-Read não tem estado para zerar e
    # o scheduler chama `reset()` em todo bloco no deploy/stop sem perguntar o tipo.
    def reset(self) -> None:  # noqa: B027
        """Zera o estado interno (deploy/stop). Blocos sem estado não precisam sobrescrever."""


def has_cold_input(inputs: Mapping[str, PortSample]) -> bool:
    """Portão de cold start (§3.0): alguma entrada conectada ainda não tem valor."""
    return any(sample.v is None for sample in inputs.values())


def null_outputs(ports: Iterable[str]) -> dict[str, PortSample]:
    """Saídas de uma varredura que não executou: nulas e inválidas, nunca 0.0 sintético."""
    return {port: PortSample(None, False) for port in ports}
