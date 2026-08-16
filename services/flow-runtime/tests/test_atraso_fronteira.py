"""Flow que perde a fronteira por culpa alheia diz isso no evento (ARCH-11, lado da VÍTIMA).

Par do `test_block_overrun.py`: lá se prova que o scheduler nomeia o bloco CULPADO; aqui se
prova o outro lado, o flow que não fez nada de errado e mesmo assim estourou o ciclo.

O defeito de observabilidade que isto fixa: quando outra task do mesmo event loop segura o
processo, o `sleep_until` deste flow volta tarde e a fronteira já nasce perdida. Antes, a
vítima publicava `flow_overrun` com a mensagem de quem se atrasou sozinho — "a varredura
estourou o ciclo de 0,1 s (0,3 ms)", número que se contradiz e manda o engenheiro procurar
lentidão no flow errado.

Relógio VIRTUAL de propósito, ao contrário de `test_block_overrun.py`: `atraso_ms` é
aritmética de relógio do próprio scheduler (`fired_at - (t0 + index·Ts)`), não custo real de
CPU, então dá para exercitá-lo de forma determinística. O TD-008 já registrou o preço de
decidir gate por relógio de parede quando havia alternativa por causa.
"""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis

from ottima_core.bus import CHANNEL_EVENTS, KIND_FLOW_OVERRUN, EventMessage
from ottima_flow_runtime.blocks.base import Block, PortSample
from ottima_flow_runtime.scheduler import FlowDefinition, FlowTask

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
FLOW_ID = 701
TS_S = 0.1
ATRASO_S = 0.25
"""2,5x o Ts: a fronteira já está perdida no instante em que a varredura PARTE, independente
do que ela custe depois. É o cenário do flow vítima, não o do flow lento."""

ESPERA_S = 5.0


class BlocoSemCusto(Block):
    """Custo zero: tudo que este flow perder é de outro. Espelha o `BlocoContador` de
    `test_isolamento_temporal.py`, sem a contagem que lá é o sujeito do teste."""

    def __init__(self, block_id: str) -> None:
        super().__init__(block_id)
        self.varreduras = 0

    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        self.varreduras += 1
        return {}


class RelogioQueAcordaTarde:
    """Relógio virtual que devolve o controle DEPOIS da fronteira pedida.

    É exatamente o que o event loop faz quando outra task o segura: o `sleep_until` já
    venceu, mas a corrotina só volta a rodar quando o loop é devolvido — então `monotonic()`
    já passou da fronteira no instante em que ela retoma. Nenhum `time.sleep` real é
    necessário para reproduzir isso, porque o número que o scheduler calcula é a diferença
    entre o relógio e a grade, não o custo de nada.
    """

    def __init__(self, atraso_s: float) -> None:
        self._t = 0.0
        self._atraso_s = atraso_s
        self._waiters: list[tuple[float, asyncio.Event]] = []
        self._dormindo = asyncio.Event()

    def monotonic(self) -> float:
        return self._t

    def now(self) -> datetime:
        return EPOCH + timedelta(seconds=self._t)

    def gastar(self, segundos: float) -> None:
        """Custo consumido DENTRO de uma varredura (quem chama é o bloco-duplo)."""
        self._t += segundos

    async def sleep_until(self, deadline_monotonic: float) -> None:
        if self._t >= deadline_monotonic:
            await asyncio.sleep(0)
            return
        waiter = asyncio.Event()
        self._waiters.append((deadline_monotonic, waiter))
        self._dormindo.set()
        await waiter.wait()

    async def disparar_atrasado(self) -> float:
        """Salta para `fronteira + atraso` e libera o laço: a fronteira já passou."""
        await asyncio.wait_for(self._dormindo.wait(), ESPERA_S)
        deadline = min(deadline for deadline, _ in self._waiters)
        self._dormindo.clear()
        self._t = deadline + self._atraso_s
        for entry in [entry for entry in self._waiters if entry[0] <= self._t]:
            self._waiters.remove(entry)
            entry[1].set()
        return deadline

    async def esperar_dormir(self) -> None:
        await asyncio.wait_for(self._dormindo.wait(), ESPERA_S)


async def _primeiro_overrun(pubsub) -> list[EventMessage]:
    eventos: list[EventMessage] = []
    for _ in range(40):
        msg = await pubsub.get_message(timeout=0.1)
        if msg and msg["type"] == "message":
            evento = EventMessage.model_validate_json(msg["data"])
            if evento.payload.get("kind") == KIND_FLOW_OVERRUN:
                eventos.append(evento)
                break
    return eventos


async def test_flow_vitima_publica_atraso_de_partida_e_nao_culpa_a_propria_varredura(
    redis_client: Redis,
):
    """A fronteira se perde antes da varredura começar; o evento tem de dizer isso."""
    bloco = BlocoSemCusto("barato")
    definition = FlowDefinition(flow_id=FLOW_ID, ts_seconds=TS_S, blocks=(bloco,), wiring={})
    relogio = RelogioQueAcordaTarde(ATRASO_S)
    task = FlowTask(definition, redis_client=redis_client, clock=relogio)

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_EVENTS)
    await pubsub.get_message(timeout=ESPERA_S)  # confirmação de inscrição

    await task.start(user="teste")
    try:
        await relogio.disparar_atrasado()
        await relogio.esperar_dormir()  # laço fechou a varredura e voltou a dormir
        eventos = await _primeiro_overrun(pubsub)
    finally:
        await task.stop(user="teste", reason="user")
        await pubsub.aclose()

    assert bloco.varreduras == 1, "o cenário não se montou: o flow não chegou a varrer"
    assert len(eventos) == 1, f"esperado 1 flow_overrun, saíram {len(eventos)}"
    evento = eventos[0]

    # O número que faltava: a fronteira se perdeu ANTES de a varredura começar. `approx`
    # porque `Ts` de uma casa decimal não é exato em binário — mesma ressalva que
    # `scheduler.py::_first_future_index` já carrega.
    assert evento.payload["atraso_ms"] == pytest.approx(ATRASO_S * 1000.0)
    # E a varredura própria não custou nada — é o que torna a mensagem antiga enganosa.
    assert evento.payload["scan_ms"] == pytest.approx(0.0, abs=1e-6)
    assert evento.payload["atraso_ms"] > evento.payload["scan_ms"]

    # A mensagem aponta para fora, não para a varredura desta task.
    assert "atraso de partida" in evento.message
    assert "segurou o event loop" in evento.message
    assert "estourou o tempo de ciclo" not in evento.message

    # A propriedade acompanha o payload, para o supervisor e os testes lerem sem o barramento.
    assert task.atraso_ms == pytest.approx(ATRASO_S * 1000.0)


async def test_flow_lento_de_verdade_continua_com_a_mensagem_de_sempre(redis_client: Redis):
    """Não-regressão: quem se atrasa pela PRÓPRIA varredura não pode virar vítima.

    Sem este par, bastaria trocar a mensagem em todo overrun para o teste acima passar.
    """

    class BlocoLento(Block):
        """Consome tempo do relógio virtual dentro do próprio `step`."""

        def __init__(self, block_id: str, relogio: RelogioQueAcordaTarde) -> None:
            super().__init__(block_id)
            self._relogio = relogio

        async def step(
            self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
        ) -> dict[str, PortSample]:
            self._relogio.gastar(TS_S * 3)  # a varredura em si estoura o ciclo
            return {}

    relogio = RelogioQueAcordaTarde(0.0)  # acorda na hora: nenhum atraso alheio
    bloco = BlocoLento("lento", relogio)
    definition = FlowDefinition(flow_id=FLOW_ID, ts_seconds=TS_S, blocks=(bloco,), wiring={})
    task = FlowTask(definition, redis_client=redis_client, clock=relogio)

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_EVENTS)
    await pubsub.get_message(timeout=ESPERA_S)

    await task.start(user="teste")
    try:
        await relogio.disparar_atrasado()
        await relogio.esperar_dormir()
        eventos = await _primeiro_overrun(pubsub)
    finally:
        await task.stop(user="teste", reason="user")
        await pubsub.aclose()

    assert len(eventos) == 1
    evento = eventos[0]
    assert evento.payload["atraso_ms"] == pytest.approx(0.0, abs=1e-6)
    assert evento.payload["scan_ms"] > evento.payload["atraso_ms"]
    assert "estourou o tempo de ciclo" in evento.message
    assert "atraso de partida" not in evento.message
