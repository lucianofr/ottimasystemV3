"""Laço de varredura de um flow (RF-401/402/404, ADR-004/007/011/024, spec F3 §2.2, §4.2).

Uma FlowTask por flow rodando, cada uma numa task asyncio própria: falha de um flow não
alcança os demais (RF-402). O laço recebe uma `FlowDefinition` pronta — blocos instanciados e
fiação resolvida — e por isso não conhece banco, `flowgraph` nem sessão OPC; quem monta a
definição é o supervisor.

Duas escolhas carregam o aceite da fase ("0,5 s sem jitter > 10%"):

1. **Fronteira absoluta.** A varredura `n` dispara em `t0 + n·Ts`, com `n` inteiro e `t0`
   ancorado no deploy. `sleep(Ts)` acumularia o custo de cada varredura na grade e a deriva
   apareceria como jitter crescente.
2. **Tabela de portas persistente.** Ela sobrevive à varredura, então a semântica do RF-401
   cai sozinha: aresta em ordem normal lê o valor escrito nesta varredura, aresta invertida lê
   o da anterior, e na primeira varredura a invertida lê `null` — que é o cold start (§3.0).
   Nenhum caso especial para nenhuma das três situações. A única exceção é a entrada de uma
   aresta de realimentação (ADR-040 D4): enquanto a origem dela nunca produziu valor, a
   leitura entrega a condição inicial declarada — senão o ciclo se auto-alimentaria de
   invalidez para sempre.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import traceback
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, NamedTuple, Protocol

from redis.asyncio import Redis

from ottima_core.bus import (
    CHANNEL_FLOW_VALUES,
    KIND_BLOCK_OVERRUN,
    KIND_FLOW_FAILED,
    KIND_FLOW_OVERRUN,
    FlowStatus,
    OpcValue,
    PortValue,
    channel_flow_status,
    publish_event,
)
from ottima_core.signal import Quality

from .blocks.base import Block, Signal

logger = logging.getLogger(__name__)

COLD = Signal(None)
"""Valor de porta que nunca foi escrito desde o deploy (§3.0). Imutável, logo compartilhável."""

BLOCK_BUDGET_FRACTION = 1.0
"""Orçamento de tempo síncrono de UM `block.step()`, como fração do `Ts` do próprio flow.

Candidato óbvio, sem constante mágica sem origem (ARCH-11): 100% do Ts é o único limiar que
não depende de nenhuma suposição sobre quantos blocos irmãos dividem o ciclo — um bloco que
sozinho já gasta o Ts inteiro garante, por conta própria, que esta varredura estoura a grade
(`_settle_grid`), não importa quão barato seja o resto do flow. Qualquer fração menor exigiria
decidir quantos blocos "cabem" no orçamento, decisão sem base hoje (spec F3 não reparte Ts
entre blocos). `block_overrun` é observabilidade — nomeia o bloco culpado; não reabre o
modelo de concorrência (ADR-004: mesma partição, mesmo event loop)."""


HISTORIZED_THROTTLE_S = 1.0
"""Teto de cadência por porta historiada (ADR-041 D3): `max(Ts_flow, 1 s)`.

A comparação leva tolerância de MEIA varredura (`- ts_seconds / 2`), não um épsilon de
microssegundo: o `ts` publicado é hora de PAREDE (`SystemClock.now()`, a grade é monotônica),
então o intervalo real entre varreduras oscila em torno de Ts por microssegundos. Com
tolerância de 1 µs e Ts = 1 s, cerca de um terço das varreduras caía um fio abaixo do limiar
e PERDIA a publicação — a série saía a ~1,5 s em vez de 1 s (medido no stack: 16 amostras em
25 s, alternando 1,000/2,003 s). Meia varredura decide sem ambiguidade em qualquer Ts da
lista {0,5; 1; 2; 5; 10; 30; 60}: Ts >= 1 s publica em toda varredura, Ts = 0,5 s publica em
uma de cada duas."""


class Clock(Protocol):
    """Relógio do laço, injetado para os testes poderem ser exatos em vez de tolerantes."""

    def monotonic(self) -> float: ...

    def now(self) -> datetime: ...

    async def sleep_until(self, deadline_monotonic: float) -> None: ...


class SystemClock:
    """Relógio real.

    A grade vive no **monotônico**: um ajuste de NTP para trás não pode deslocar fronteira
    (a F2 já pagou esse conserto no heartbeat do opc-worker). O `ts` publicado é hora de
    parede porque quem o lê é gente e o banco.
    """

    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep_until(self, deadline_monotonic: float) -> None:
        await asyncio.sleep(max(0.0, deadline_monotonic - time.monotonic()))


class HistorizedPort(NamedTuple):
    """Porta historiada resolvida contra o grafo (ADR-041 D1/D7): `definition.py` já
    filtrou pelo que o bloco realmente tem — aqui só o necessário para publicar em
    `flow.values` (`tag_id` é a linha em `tags` compartilhada com a variável)."""

    block_id: str
    port: str
    tag_id: int


def _historized_value(sample: Signal) -> tuple[float, int]:
    """`Signal` -> `(value, quality)` de `OpcValue` (ADR-041 D4).

    Porta inválida (`ok=False`) ou sem valor (`v=None`) vira `0.0`/`quality=2` — o recorder
    troca por NULL sozinho (ADR-037); alargar `OpcValue.value` para aceitar `None` mudaria
    o contrato compartilhado com `opc.values`/`calc.values`. Porta booleana vira `1.0`/`0.0`.

    Não-finito é FALHA, não valor (mesma regra de `calc_worker/runner.py`): `OpcReadBlock`
    propaga o float do PLC verbatim com `ok=True`, então um NaN/Inf de campo (overflow de
    escala, divisão por zero na lógica do PLC) chegaria aqui com qualidade boa. NULL é
    ignorado por `avg`/`max` do SQL; NaN CONTAMINA o bucket do CAgg de 1 min para sempre.
    """
    if not sample.ok or sample.v is None:
        return 0.0, 2
    if isinstance(sample.v, bool):
        return (1.0 if sample.v else 0.0), 0
    value = float(sample.v)
    if not math.isfinite(value):
        return 0.0, 2
    return value, 0


@dataclass(frozen=True, slots=True)
class FlowDefinition:
    """O que o laço precisa para varrer: blocos prontos, em ordem, e a fiação entre eles."""

    flow_id: int
    ts_seconds: float
    blocks: tuple[Block, ...]
    """Já em ordem crescente de `exec_order` (ADR-024): a tupla É a ordem de execução."""
    wiring: Mapping[str, Mapping[str, tuple[str, str]]]
    """`wiring[block_id][input_handle] = (source_block_id, source_handle)`."""
    seeds: Mapping[tuple[str, str], float] = field(default_factory=dict)
    """Condição inicial das arestas de realimentação (ADR-040 D4), por porta de DESTINO:
    `seeds[(target_block_id, target_handle)] = feedback_init`.

    Porta de destino, e não de origem: ela é única por construção (uma aresta por porta de
    entrada), e a semente é consumida na LEITURA — semear a tabela na origem não sobrevive
    ao próprio bloco de origem (ver `_seeded`). Sem isto o laço não é só frio:
    `has_cold_input` faz todo bloco devolver saída nula enquanto uma entrada conectada for
    `v=None`, e num ciclo essa invalidez se auto-alimenta — a malha ficaria inválida para
    sempre."""
    historized: tuple[HistorizedPort, ...] = field(default_factory=tuple)
    """Portas de bloco gravadas em `flow.values` (ADR-041): já filtradas contra as portas
    reais dos blocos instanciados por `definition.py` — porta que saiu do grafo (bloco
    removido, `n_inputs` reduzido, MV do mpc renomeada) nunca chega aqui. O throttle por
    porta (D3) mora no `FlowTask`, não nesta definição imutável e compartilhada entre
    varreduras."""


class FlowTask:
    """Um flow rodando: estado, grade de varredura e publicação de `flow.status`."""

    def __init__(
        self,
        definition: FlowDefinition,
        *,
        redis_client: Redis,
        clock: Clock | None = None,
    ) -> None:
        self._definition = definition
        self._redis = redis_client
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._state: Literal["running", "stopped", "failed"] = "stopped"
        self._ports: dict[str, dict[str, Signal]] = {}
        self._seeds_armed: dict[tuple[str, str], float] = {}
        self._historized_last: dict[tuple[str, str], datetime] = {}
        self._staged: FlowDefinition | None = None
        self._task: asyncio.Task[None] | None = None
        self._t0 = 0.0
        self._scan_ms = 0.0
        self._atraso_ms = 0.0
        self._overruns = 0
        self._last_scan_ts: datetime | None = None
        self._overrun_armed = True
        self._block_overrun_armed: dict[str, bool] = {}
        self._reset_ports()

    @property
    def state(self) -> Literal["running", "stopped", "failed"]:
        return self._state

    @property
    def scan_ms(self) -> float:
        return self._scan_ms

    @property
    def atraso_ms(self) -> float:
        """Quanto a ÚLTIMA varredura demorou a PARTIR depois da fronteira dela (ARCH-11).

        Distinto de `scan_ms`, que é o custo da varredura em si. `sleep_until` só devolve o
        controle quando o event loop volta a rodar, então este número é o tempo que OUTRA
        task do mesmo processo segurou o loop — a medida do lado da VÍTIMA, complementar ao
        `block_overrun`, que nomeia o culpado do lado de lá.
        """
        return self._atraso_ms

    @property
    def overruns(self) -> int:
        return self._overruns

    @property
    def last_scan_ts(self) -> datetime | None:
        return self._last_scan_ts

    async def start(self, *, user: str) -> None:
        """Ancora a grade e sobe a task. Idempotente: deploy em rodando é no-op (RNF-05)."""
        if self._state == "running":
            return
        self._reset_blocks()
        self._reset_ports()
        self._scan_ms = 0.0
        self._atraso_ms = 0.0
        self._overruns = 0
        self._overrun_armed = True
        self._block_overrun_armed = {}
        self._historized_last = {}
        self._last_scan_ts = None
        self._t0 = self._clock.monotonic()
        self._state = "running"
        logger.info(
            "Flow %s iniciado por %s (Ts=%s s)",
            self._definition.flow_id,
            user,
            self._definition.ts_seconds,
        )
        await self._publish_transition()
        self._task = asyncio.create_task(self._run(), name=f"flow-{self._definition.flow_id}")

    async def stop(self, *, user: str, reason: str) -> None:
        """Encerra a task. Idempotente e nunca levanta: é caminho de desmonte (RNF-05).

        Flow em `failed` não volta a `stopped`: falha é terminal e só deploy manual retoma
        (§2.2-6). Publicar `stopped` aqui apagaria o alarme da tela.
        """
        if self._state != "running":
            return
        self._state = "stopped"
        await self._cancel_task()
        self._reset_blocks()
        logger.info("Flow %s parado por %s (motivo=%s)", self._definition.flow_id, user, reason)
        await self._publish_transition()

    async def fail(self, *, reason: str) -> None:
        """Falha imposta de fora: `comm_failure` derruba os flows da conexão caída (RF-207)."""
        if self._state != "running":
            return
        self._state = "failed"
        await self._cancel_task()
        self._reset_blocks()
        logger.warning("Flow %s em falha (motivo=%s)", self._definition.flow_id, reason)
        await self._publish_transition()
        await self._emit_failed(
            reason=reason,
            message=f"Flow {self._definition.flow_id} parado em falha (motivo: {reason})",
        )

    def stage(self, definition: FlowDefinition) -> None:
        """Guarda a definição nova para o laço adotar na fronteira seguinte.

        Nunca no meio da varredura corrente (ADR-011). Quem monta a definição e preserva o
        estado interno dos blocos por `block_id` é o supervisor.
        """
        self._staged = definition

    async def _run(self) -> None:
        index = 1
        try:
            while True:
                await self._clock.sleep_until(self._t0 + index * self._definition.ts_seconds)
                if self._staged is not None:
                    index = self._adopt_staged(self._staged, index)
                fired_at = self._clock.monotonic()
                # Atraso de PARTIDA (ARCH-11): `sleep_until` só devolve o controle quando o
                # event loop volta a rodar. Se outra task do mesmo processo o segurou, este
                # número é grande mesmo com a varredura desta task custando quase nada — e é
                # a única evidência, do lado da vítima, de que a fronteira se perdeu por
                # motivo alheio. Calculado DEPOIS de `_adopt_staged`, que pode reancorar
                # `_t0` e devolver outro `index`.
                self._atraso_ms = (
                    fired_at - (self._t0 + index * self._definition.ts_seconds)
                ) * 1000.0
                fired_ts = self._clock.now()
                await self._scan(fired_ts)
                self._scan_ms = (self._clock.monotonic() - fired_at) * 1000.0
                self._last_scan_ts = fired_ts
                # A grade se acerta ANTES de publicar: a varredura que estourou tem de levar o
                # próprio `overruns`, e não o da anterior — é o campo que o aceite mede.
                index = await self._settle_grid(index)
                await self._publish_status(ts=fired_ts, ports=self._port_values())
                await self._publish_historized(fired_ts)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._handle_loop_failure()

    async def _scan(self, ts: datetime) -> None:
        """Uma varredura: blocos na ordem da tupla, lendo e escrevendo a tabela de portas.

        `ts` é a fronteira desta varredura (`fired_ts` de `_run`, o MESMO instante publicado
        em `flow.status.ts` logo abaixo) — repassado a todo bloco via `step(inputs, ts=ts)`
        (spec F5 §2.1): quem carimba algo próprio (hoje só o MPC, `ts`/`prediction.ts` de
        `mpc.state`) usa exatamente este relógio, nunca um `datetime.now(UTC)` desacoplado.

        Cada `block.step()` também é cronometrado individualmente (ARCH-11), reusando o
        `time.monotonic()` do próprio relógio do laço — o mesmo que alimenta `scan_ms` em
        `_run`, sem relógio novo. O custo agregado da varredura continua vindo de `_run`;
        aqui só se decompõe esse total por bloco, para nomear o culpado quando ele estoura o
        orçamento sozinho.
        """
        wiring = self._definition.wiring
        budget_ms = self._definition.ts_seconds * BLOCK_BUDGET_FRACTION * 1000.0
        for block in self._definition.blocks:
            ports = self._ports[block.block_id]
            inputs: dict[str, Signal] = {}
            for handle, (source_id, source_handle) in wiring.get(block.block_id, {}).items():
                sample = self._ports[source_id][source_handle]
                sample = self._seeded(block.block_id, handle, sample)
                inputs[handle] = sample
                # A entrada também vai para a tabela: o canvas desenha os dois lados da
                # aresta (§4.2). Só o dict `inputs` é restrito às portas conectadas.
                ports[handle] = sample
            started = self._clock.monotonic()
            outputs = await block.step(inputs, ts=ts)
            block_ms = (self._clock.monotonic() - started) * 1000.0
            for handle, sample in outputs.items():
                ports[handle] = sample
            await self._check_block_budget(block.block_id, block_ms, budget_ms)

    def _seeded(self, block_id: str, handle: str, sample: Signal) -> Signal:
        """Condição inicial da aresta de realimentação (ADR-040 D4), no ponto de LEITURA.

        A semente é **de partida, não fallback de invalidez**: vale enquanto a porta de
        origem nunca produziu valor, e é desarmada na primeira amostra com valor. Depois
        disso a invalidez propaga normalmente — senão um laço cujo sinal ficou ruim no meio
        da operação passaria a mostrar a condição inicial como se fosse dado bom.

        Aplicada na leitura, e chaveada pela porta de DESTINO, por dois motivos: semear a
        porta de origem na tabela não sobrevive (`_scan` grava toda saída do `step()`, e
        bloco com entrada fria devolve `null_outputs` — a origem apagaria a própria
        semente), e a porta de destino é única por construção (uma aresta por porta de
        entrada, `_check_fan_in`), então não há empate a resolver.
        """
        key = (block_id, handle)
        seed = self._seeds_armed.get(key)
        if seed is None:
            return sample
        if sample.v is None:
            return Signal(seed, quality=Quality.GOOD)
        del self._seeds_armed[key]
        return sample

    async def _check_block_budget(self, block_id: str, block_ms: float, budget_ms: float) -> None:
        """Compara o custo de UM `block.step()` contra o orçamento e nomeia o bloco culpado.

        Mesmo dedupe/rearme do `flow_overrun` (`_settle_grid` logo abaixo): sem isso, um
        bloco preso acima do orçamento em toda varredura emitiria um evento por varredura —
        rearma só quando o MESMO bloco fecha uma varredura dentro do orçamento de novo.
        """
        if block_ms <= budget_ms:
            self._block_overrun_armed[block_id] = True
            return
        if not self._block_overrun_armed.get(block_id, True):
            return
        self._block_overrun_armed[block_id] = False
        await publish_event(
            self._redis,
            severity="warning",
            origin=self._origin,
            message=(
                f"Bloco {block_id} do flow {self._definition.flow_id} estourou o orçamento"
                f" de {budget_ms:.1f} ms ({block_ms:.1f} ms)"
            ),
            kind=KIND_BLOCK_OVERRUN,
            payload={
                "flow_id": self._definition.flow_id,
                "block_id": block_id,
                "block_ms": block_ms,
                "budget_ms": budget_ms,
            },
        )

    async def _settle_grid(self, index: int) -> int:
        """Devolve o índice da próxima varredura, pulando as fronteiras perdidas (§2.2-2).

        `overruns` conta **varreduras** que fecharam depois da fronteira seguinte, não
        fronteiras puladas: é a leitura que o aceite "zero overruns" mede (E2E-F3-03). Uma
        varredura de 10×Ts conta 1, não 10.

        O evento distingue duas causas que antes saíam com a MESMA mensagem (ARCH-11). Um
        flow pode estourar a fronteira sem ter feito nada de errado: se outra task do mesmo
        event loop segurou o processo, o `sleep_until` desta aqui volta tarde e a fronteira
        já nasce perdida. Antes disso, a vítima publicava "a varredura estourou o ciclo de
        0,1 s (0,3 ms)" — número que se contradiz e manda o engenheiro procurar lentidão no
        flow errado. Agora `atraso_ms` e `scan_ms` saem os dois no payload, e quem dominar
        escolhe a mensagem. O culpado, do outro lado, é nomeado pelo `block_overrun`.
        """
        ts_seconds = self._definition.ts_seconds
        now = self._clock.monotonic()
        if now <= self._t0 + (index + 1) * ts_seconds:
            self._overrun_armed = True  # varredura no orçamento re-arma o dedupe do evento
            return index + 1

        self._overruns += 1
        if self._overrun_armed:
            self._overrun_armed = False
            await publish_event(
                self._redis,
                severity="warning",
                origin=self._origin,
                message=(
                    f"Flow {self._definition.flow_id} perdeu a fronteira por atraso de"
                    f" partida de {self._atraso_ms:.1f} ms (varredura própria:"
                    f" {self._scan_ms:.1f} ms) — outra task do mesmo processo segurou o"
                    f" event loop"
                    if self._atraso_ms > self._scan_ms
                    else (
                        f"Varredura do flow {self._definition.flow_id} estourou o tempo de"
                        f" ciclo de {ts_seconds} s ({self._scan_ms:.1f} ms)"
                    )
                ),
                kind=KIND_FLOW_OVERRUN,
                payload={
                    "flow_id": self._definition.flow_id,
                    "scan_ms": self._scan_ms,
                    # Aditivo ao payload (mesmo espírito do `status` do `MpcVarState`):
                    # consumidor existente que só lê `overruns` continua válido.
                    "atraso_ms": self._atraso_ms,
                    "ts_seconds": ts_seconds,
                    "overruns": self._overruns,
                },
            )
        return self._first_future_index(now, index, ts_seconds)

    def _first_future_index(self, now: float, index: int, ts_seconds: float) -> int:
        """Primeira fronteira da grade não anterior ao relógio — nunca uma fila de compensação.

        O índice é sempre inteiro e a fronteira sempre recalculada como `t0 + n·Ts`: a grade
        não guarda soma nenhuma, então não há onde a deriva se acumular. O `while` corrige o
        arredondamento da divisão (`Ts` de uma casa decimal raramente é exato em binário).
        """
        candidate = max(index + 1, int((now - self._t0) // ts_seconds))
        while self._t0 + candidate * ts_seconds < now:
            candidate += 1
        return candidate

    def _adopt_staged(self, staged: FlowDefinition, index: int) -> int:
        """Troca atômica na fronteira (ADR-011). Devolve o índice corrente da grade vigente."""
        self._staged = None
        previous_ts = self._definition.ts_seconds
        self._definition = staged
        self._carry_ports()
        self._forget_dead_historized()
        logger.info("Flow %s adotou a definição staged", staged.flow_id)
        if staged.ts_seconds != previous_ts:
            # Ts novo re-ancora a grade no instante da troca (spec §4.1-4): manter o `t0`
            # antigo faria as fronteiras novas caírem em posições arbitrárias da grade velha.
            self._t0 = self._clock.monotonic()
            return 0
        return index

    def _carry_ports(self) -> None:
        """Tabela da definição nova preservando o valor das portas que sobreviveram.

        Editar o grafo não pode zerar o histórico de quem não mudou: a aresta invertida
        perderia a varredura anterior por causa de uma edição em outro canto do flow. Porta
        nova nasce fria (§3.0); porta que saiu do grafo desaparece da publicação. As sementes
        de realimentação rearmam no `_reset_ports` — a de aresta nova parte da condição
        inicial dela, e a de aresta antiga se desarma sem efeito na primeira leitura.
        """
        previous = self._ports
        self._reset_ports()
        for block_id, ports in self._ports.items():
            carried = previous.get(block_id, {})
            for port in ports:
                if port in carried:
                    ports[port] = carried[port]

    def _forget_dead_historized(self) -> None:
        """Descarta o throttle das portas que saíram do cadastro (ADR-041 D3): variável
        removida ou porta que desapareceu do grafo não pode deixar chave morta acumulando
        para sempre num flow de Ts longo. Porta que sobrevive ao hot-swap mantém a própria
        cadência — a troca não reseta o relógio dela."""
        alive = {(port.block_id, port.port) for port in self._definition.historized}
        for key in list(self._historized_last):
            if key not in alive:
                del self._historized_last[key]

    def _reset_ports(self) -> None:
        """Toda porta declarada — entrada e saída — nasce nula e inválida, nunca 0.0.

        Rearma junto as sementes de realimentação (ADR-040 D4): vale para o deploy e para o
        hot-swap, porque aresta de realimentação NOVA precisa da condição inicial dela. Uma
        semente rearmada sobre porta que já tem valor não tem efeito — `_seeded` a desarma
        na primeira leitura, sem nunca usá-la.
        """
        self._ports = {
            block.block_id: dict.fromkeys((*block.input_ports, *block.output_ports), COLD)
            for block in self._definition.blocks
        }
        self._seeds_armed = dict(self._definition.seeds)

    def _reset_blocks(self) -> None:
        for block in self._definition.blocks:
            try:
                block.reset()
            except Exception:
                # `stop()` não levanta: bloco com `reset` defeituoso não trava o desmonte.
                logger.exception(
                    "Falha ao zerar o bloco %s do flow %s",
                    block.block_id,
                    self._definition.flow_id,
                )

    def _port_values(self) -> dict[str, dict[str, PortValue]]:
        """Tabela inteira: todas as portas de todos os blocos são o que o canvas desenha."""
        return {
            block_id: {
                port: PortValue(
                    v=sample.v,
                    quality=sample.quality,
                    substatus=sample.substatus,
                    hi_limited=sample.hi_limited,
                    lo_limited=sample.lo_limited,
                )
                for port, sample in ports.items()
            }
            for block_id, ports in self._ports.items()
        }

    async def _publish_status(
        self, *, ts: datetime, ports: dict[str, dict[str, PortValue]]
    ) -> None:
        status = FlowStatus(
            state=self._state,
            scan_ms=self._scan_ms,
            overruns=self._overruns,
            ts=ts,
            ports=ports,
        )
        try:
            await self._redis.publish(
                channel_flow_status(self._definition.flow_id), status.model_dump_json()
            )
        except Exception:
            # Telemetria não derruba laço de controle (ADR-004/009) — mesma regra que o
            # `publish_event` do bus já aplica aos eventos.
            logger.exception("Falha ao publicar flow.status do flow %s", self._definition.flow_id)

    async def _publish_historized(self, ts: datetime) -> None:
        """Publica em `flow.values` as portas historiadas cuja cadência (ADR-041 D3) já
        venceu, no MESMO `ts` da grade publicado em `flow.status` — nunca `time.time()`,
        para o throttle não herdar o jitter que a fronteira absoluta já elimina.

        Fire-and-forget, uma mensagem por porta: exceção de publicação é logada e nunca
        derruba a varredura (mesmo tratamento de `_publish_status`). Sai antes de montar
        qualquer coisa quando o flow não tem porta historiada — custo zero no caso comum.
        """
        historized = self._definition.historized
        if not historized:
            return
        # Tolerância de meia varredura (ver `HISTORIZED_THROTTLE_S`): o `ts` é hora de parede
        # e oscila em torno de Ts, então épsilon de microssegundo descartaria varredura boa.
        minimo = HISTORIZED_THROTTLE_S - self._definition.ts_seconds / 2
        for port in historized:
            key = (port.block_id, port.port)
            last = self._historized_last.get(key)
            if last is not None and (ts - last).total_seconds() < minimo:
                continue
            self._historized_last[key] = ts
            sample = self._ports.get(port.block_id, {}).get(port.port, COLD)
            value, quality = _historized_value(sample)
            payload = OpcValue(tag_id=port.tag_id, ts=ts, value=value, quality=quality)
            try:
                await self._redis.publish(CHANNEL_FLOW_VALUES, payload.model_dump_json())
            except Exception:
                logger.exception(
                    "Falha ao publicar variável historiada %s.%s (tag %s) do flow %s",
                    port.block_id,
                    port.port,
                    port.tag_id,
                    self._definition.flow_id,
                )

    async def _publish_transition(self) -> None:
        """Transição de estado não tem varredura atrás dela: `ports` vazio é o contrato."""
        await self._publish_status(ts=self._clock.now(), ports={})

    async def _handle_loop_failure(self) -> None:
        """Exceção não tratada: este flow vai a `failed` e a task encerra. Só este (RF-402)."""
        detail = traceback.format_exc()
        logger.error("Flow %s falhou no laço de varredura:\n%s", self._definition.flow_id, detail)
        self._state = "failed"
        await self._publish_transition()
        await self._emit_failed(
            reason="unhandled_exception",
            message=(
                f"Flow {self._definition.flow_id} em falha:"
                " exceção não tratada no laço de varredura"
            ),
            detail=detail,
        )

    async def _emit_failed(self, *, reason: str, message: str, detail: str | None = None) -> None:
        payload: dict[str, object] = {"flow_id": self._definition.flow_id, "reason": reason}
        if detail is not None:
            payload["traceback"] = detail
        await publish_event(
            self._redis,
            severity="alarm",
            origin=self._origin,
            message=message,
            kind=KIND_FLOW_FAILED,
            payload=payload,
        )

    async def _cancel_task(self) -> None:
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    @property
    def _origin(self) -> str:
        """`origin` de evento de flow (§6.1 filtra por ele); o `user` viaja no payload."""
        return f"flow:{self._definition.flow_id}"
