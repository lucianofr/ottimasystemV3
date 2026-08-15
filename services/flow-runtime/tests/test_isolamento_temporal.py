"""Varredura lenta de um flow não pode atrasar a fronteira de outro (RF-402, ADR-004).

`test_scheduler.py` já cobre o isolamento de **falha**: bloco que levanta derruba só o próprio
flow. O que falta é o isolamento **temporal**, e ele é de outra natureza — todos os flows são
tasks asyncio do MESMO event loop, num processo só (`uvicorn` sem `--workers` no compose), então
a independência entre eles vale exatamente na medida em que nenhum bloco bloqueia o loop. É o
que `blocks/base.py` enuncia como contrato de base: "nenhum bloco pode bloquear o event loop
(ADR-004)". Nada exercita esse contrato hoje.

O relógio aqui é o `SystemClock` real, não o `FakeClock` de `test_scheduler.py`: naquele o tempo
só anda quando o teste manda e o custo de uma varredura é virtual (`SpyBlock.cost` chama
`clock.advance`), então um bloco que segura a thread de verdade não produziria efeito nenhum —
seria um teste que passa sem testar. Por isso as `FlowTask` são montadas à mão, com relógio real,
e a asserção é uma contagem grosseira em janela de tempo de parede.

O gatilho é `time.sleep` num `step`, que é a forma honesta do custo inline que existe em
produção: `blocks/fuzzy.py` roda `engine.process()` dentro do loop (com um comentário admitindo
"mover a executor se overrun aparecer"), e PID/TFS/Kalman/First-Order fazem o mesmo em escala
menor. Nenhum deles é assíncrono; todos somam no mesmo núcleo. Basta um engine grande, um laço
numpy mal dimensionado ou um `Ts` pequeno para o cenário deste teste sair de "sub-ms, ninguém
percebe" para "o flow do lado perdeu 10 fronteiras".

XFAIL: reprodução de defeito aberto. Fecha quando o custo inline dos blocos deixar de rodar no
event loop compartilhado (executor por bloco caro, ou a partição de flows por processo que o
ADR-004 já prevê: "um event loop por núcleo").
"""

import asyncio
import time
from collections.abc import Mapping
from datetime import datetime

import pytest
from redis.asyncio import Redis

from ottima_flow_runtime.blocks.base import Block, PortSample
from ottima_flow_runtime.scheduler import FlowDefinition, FlowTask

FLOW_LENTO = 101
FLOW_RAPIDO = 102
TS_S = 0.1
"""`Ts` dos dois flows. Do lado do flow rápido é o que torna a perda de fronteira contável."""

CUSTO_S = 1.0
"""Uma varredura lenta do flow A: 10x o `Ts` do flow B, ou seja 10 fronteiras de B em risco."""

JANELA_S = 1.5
"""Tempo de parede observado. Cabe o bloqueio inteiro e sobra para o flow B se recuperar."""

FRONTEIRAS_IDEAIS = int(JANELA_S / TS_S)
MINIMO_ACEITO = 12
"""80% das fronteiras ideais (15). Grosseiro de propósito: máquina carregada tira algumas, e o
que o teste precisa distinguir é 15 de ~5 — a diferença que 1,0 s de bloqueio produz."""


class BlocoBloqueante(Block):
    """Segura o event loop de verdade, como qualquer custo inline não trivial em produção.

    Bloqueia uma vez só: mantém a janela do teste curta e a aritmética das fronteiras óbvia.
    Bloquear em toda varredura seria mais próximo de um Fuzzy pesado, mas não muda o veredito e
    espalharia o custo por uma janela maior.
    """

    def __init__(self, block_id: str, *, custo_s: float) -> None:
        super().__init__(block_id)
        self._custo_s: float = custo_s
        self.execucoes: int = 0

    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        self.execucoes += 1
        if self.execucoes == 1:
            # `time.sleep` num `async def` é exatamente o que o ADR-004 proíbe e o que o
            # ruff acusa (ASYNC251). Aqui é o sujeito do teste, não um descuido: é o
            # substituto honesto de um `engine.process()` caro, que o linter não tem como ver.
            time.sleep(self._custo_s)  # noqa: ASYNC251
        return {}


class BlocoContador(Block):
    """Conta varreduras. O flow rápido não tem custo nenhum: tudo que ele perder é do outro."""

    def __init__(self, block_id: str) -> None:
        super().__init__(block_id)
        self.varreduras: int = 0

    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        self.varreduras += 1
        return {}


def _flow(flow_id: int, bloco: Block, redis_client: Redis) -> FlowTask:
    """`FlowTask` com o relógio real (default): o `FakeClock` da suíte não serve aqui."""
    definition = FlowDefinition(flow_id=flow_id, ts_seconds=TS_S, blocks=(bloco,), wiring={})
    return FlowTask(definition, redis_client=redis_client)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "defeito aberto: todos os flows compartilham um event loop, então custo inline de um"
        " bloco (fuzzy/PID/TFS) rouba a fronteira dos outros flows (RF-402, ADR-004)"
    ),
)
async def test_varredura_lenta_de_um_flow_nao_atrasa_a_fronteira_do_outro(redis_client: Redis):
    """O flow rápido tem de manter sua grade enquanto o flow lento gasta 1,0 s numa varredura.

    É o RF-402 lido no eixo do tempo, não no da falha: "falha de um flow não afeta os demais"
    não vale nada se a LENTIDÃO de um afeta a taxa de amostragem dos demais — numa malha de
    controle, fronteira perdida é ação de controle não tomada.
    """
    lento = BlocoBloqueante("bloqueante", custo_s=CUSTO_S)
    contador = BlocoContador("contador")
    flow_lento = _flow(FLOW_LENTO, lento, redis_client)
    flow_rapido = _flow(FLOW_RAPIDO, contador, redis_client)

    await flow_lento.start(user="teste")
    await flow_rapido.start(user="teste")
    try:
        await asyncio.sleep(JANELA_S)
    finally:
        await flow_lento.stop(user="teste", reason="user")
        await flow_rapido.stop(user="teste", reason="user")

    assert lento.execucoes >= 1, "o flow lento não chegou a varrer: o cenário não se montou"
    assert contador.varreduras >= MINIMO_ACEITO, (
        f"o flow rápido varreu {contador.varreduras}x em {JANELA_S}s com Ts={TS_S}s"
        f" ({FRONTEIRAS_IDEAIS} fronteiras na grade): perdeu as que o outro flow gastou"
        f" bloqueando o event loop por {CUSTO_S}s"
    )


async def test_dois_flows_sem_custo_mantem_cada_um_a_sua_grade(redis_client: Redis):
    """Controle do teste acima: mesma janela, mesmo `Ts`, dois flows — nenhum bloqueando.

    Verde aqui e vermelho lá é o que prova que a causa é o bloqueio do event loop, e não uma
    grade de 0,1 s inalcançável nesta máquina (publicação no Redis a cada varredura, jitter do
    agendador). Se ESTE teste ficar vermelho, `MINIMO_ACEITO` é que está mal calibrado.
    """
    primeiro, segundo = BlocoContador("a"), BlocoContador("b")
    flow_a = _flow(FLOW_LENTO, primeiro, redis_client)
    flow_b = _flow(FLOW_RAPIDO, segundo, redis_client)

    await flow_a.start(user="teste")
    await flow_b.start(user="teste")
    try:
        await asyncio.sleep(JANELA_S)
    finally:
        await flow_a.stop(user="teste", reason="user")
        await flow_b.stop(user="teste", reason="user")

    assert primeiro.varreduras >= MINIMO_ACEITO, f"flow A varreu {primeiro.varreduras}x"
    assert segundo.varreduras >= MINIMO_ACEITO, f"flow B varreu {segundo.varreduras}x"
