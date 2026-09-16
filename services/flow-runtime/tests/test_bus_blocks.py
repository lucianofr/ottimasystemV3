"""Contratos dos blocos de barramento `bus_publish`/`bus_subscribe` (ADR-042).

- **bus_publish**: publica `ExchangeValue` em `flow.exchange` a cada varredura, carimbando o
  Ts do próprio flow em `period_s`. Cold start NÃO publica; inválido publica com `ok=false`
  (decisão A-6 atravessa o barramento, D3).
- **bus_subscribe**: lê do espelho e decide validade por IDADE (D4) — `key` nunca publicada é
  cold (`None`, inválido); valor mais velho que `3 × period_s` sai com o último valor e
  `ok=False`, nunca com `ok=True`.

O par ponta a ponta é exercido com um espelho alimentado pelo payload REAL do publicador:
é o que prova que os dois lados falam o mesmo contrato de canal.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from ottima_core.bus import CHANNEL_FLOW_EXCHANGE, ExchangeValue
from ottima_core.flowgraph import parse_graph
from ottima_core.signal import Quality
from ottima_flow_runtime.blocks.base import Signal
from ottima_flow_runtime.blocks.bus_publish import BusPublishBlock
from ottima_flow_runtime.blocks.bus_subscribe import BusSubscribeBlock
from ottima_flow_runtime.definition import StagedDefinition, build_definition

TS = 1.0
T0 = datetime(2026, 1, 1, tzinfo=UTC)
KEY = "nivel_tanque"


class RedisEspiao:
    """Duplo do Redis: guarda `(canal, payload)` de cada `publish`."""

    def __init__(self) -> None:
        self.publicados: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.publicados.append((channel, payload))


class EspelhoFake:
    """Duplo do `ExchangeSnapshot`: só o `get` síncrono importa para o bloco."""

    def __init__(self) -> None:
        self.valores: dict[str, ExchangeValue] = {}

    def get(self, key: str) -> ExchangeValue | None:
        return self.valores.get(key)

    def ingest(self, payload: str) -> None:
        value = ExchangeValue.model_validate_json(payload)
        self.valores[value.key] = value


def publicador(*, key: str = KEY, ts_seconds: float = TS) -> tuple[BusPublishBlock, RedisEspiao]:
    redis = RedisEspiao()
    return BusPublishBlock("p1", key=key, ts_seconds=ts_seconds, redis_client=redis), redis  # type: ignore[arg-type]


def assinante(espelho: EspelhoFake, *, key: str = KEY) -> BusSubscribeBlock:
    return BusSubscribeBlock("s1", key=key, snapshot=espelho)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# bus_publish
# --------------------------------------------------------------------------------------


async def test_publica_valor_no_canal_com_o_ts_do_flow():
    bloco, redis = publicador(ts_seconds=2.0)

    saida = await bloco.step({"in": Signal(42.5, quality=Quality.GOOD)}, ts=T0)

    assert saida == {}
    assert bloco.output_ports == ()
    canal, payload = redis.publicados[0]
    assert canal == CHANNEL_FLOW_EXCHANGE
    quadro = ExchangeValue.model_validate_json(payload)
    assert (quadro.key, quadro.v, quadro.ok, quadro.period_s) == (KEY, 42.5, True, 2.0)
    assert quadro.ts == T0


async def test_publica_booleano_sem_virar_numero():
    """D7: o barramento é transporte — booleano chega booleano do outro lado."""
    bloco, redis = publicador()

    await bloco.step({"in": Signal(True, quality=Quality.GOOD)}, ts=T0)

    assert json.loads(redis.publicados[0][1])["v"] is True


async def test_cold_start_nao_publica():
    bloco, redis = publicador()

    assert await bloco.step({"in": Signal(None)}, ts=T0) == {}
    assert redis.publicados == []


async def test_entrada_ausente_nao_publica():
    """Aresta obrigatória faltando (a validação já reprova): nunca inventa um número."""
    bloco, redis = publicador()

    assert await bloco.step({}, ts=T0) == {}
    assert redis.publicados == []


async def test_invalido_publica_com_flag_de_invalidez():
    bloco, redis = publicador()

    await bloco.step({"in": Signal(7.0)}, ts=T0)

    quadro = ExchangeValue.model_validate_json(redis.publicados[0][1])
    assert (quadro.v, quadro.ok) == (7.0, False)


async def test_publica_uma_vez_por_varredura():
    bloco, redis = publicador()

    for i in range(3):
        await bloco.step(
            {"in": Signal(float(i), quality=Quality.GOOD)}, ts=T0 + timedelta(seconds=i)
        )

    assert [ExchangeValue.model_validate_json(p).v for _, p in redis.publicados] == [0.0, 1.0, 2.0]


# --------------------------------------------------------------------------------------
# bus_subscribe
# --------------------------------------------------------------------------------------


async def test_key_sem_publicador_sai_nula_e_invalida():
    """Cold start (D4/D6): congela o bloco a jusante por `has_cold_input`."""
    bloco = assinante(EspelhoFake())

    saida = (await bloco.step({}, ts=T0))["out"]

    assert (saida.v, saida.ok) == (None, False)
    assert bloco.input_ports == ()


async def test_valor_fresco_sai_valido():
    espelho = EspelhoFake()
    espelho.valores[KEY] = ExchangeValue(key=KEY, ts=T0, v=12.0, ok=True, period_s=TS)

    saida = (await assinante(espelho).step({}, ts=T0 + timedelta(seconds=2)))["out"]

    assert (saida.v, saida.ok) == (12.0, True)


async def test_valor_expirado_sai_com_ultimo_valor_e_invalido():
    """`3 × period_s` (D4): mantém o valor conhecido e baixa a flag, nunca `None`."""
    espelho = EspelhoFake()
    espelho.valores[KEY] = ExchangeValue(key=KEY, ts=T0, v=12.0, ok=True, period_s=TS)

    saida = (await assinante(espelho).step({}, ts=T0 + timedelta(seconds=3.5)))["out"]

    assert (saida.v, saida.ok) == (12.0, False)


async def test_tolerancia_acompanha_o_ts_do_publicador():
    """Publicador de Ts=60 s tolera 180 s — o que um limite fixo de segundos quebraria."""
    espelho = EspelhoFake()
    espelho.valores[KEY] = ExchangeValue(key=KEY, ts=T0, v=1.0, ok=True, period_s=60.0)

    bloco = assinante(espelho)

    assert (await bloco.step({}, ts=T0 + timedelta(seconds=179)))["out"].ok is True
    assert (await bloco.step({}, ts=T0 + timedelta(seconds=181)))["out"].ok is False


async def test_invalidez_do_publicador_propaga_mesmo_fresco():
    espelho = EspelhoFake()
    espelho.valores[KEY] = ExchangeValue(key=KEY, ts=T0, v=3.0, ok=False, period_s=TS)

    saida = (await assinante(espelho).step({}, ts=T0))["out"]

    assert (saida.v, saida.ok) == (3.0, False)


async def test_period_s_patologico_expira_em_vez_de_tolerar_para_sempre():
    """`period_s <= 0`/não-finito não pode virar tolerância infinita: cai para inválido."""
    espelho = EspelhoFake()
    espelho.valores[KEY] = ExchangeValue(key=KEY, ts=T0, v=5.0, ok=True, period_s=0.0)

    saida = (await assinante(espelho).step({}, ts=T0))["out"]

    assert (saida.v, saida.ok) == (5.0, False)


async def test_assinante_de_outra_key_nao_ve_o_valor():
    espelho = EspelhoFake()
    espelho.valores[KEY] = ExchangeValue(key=KEY, ts=T0, v=9.0, ok=True, period_s=TS)

    saida = (await assinante(espelho, key="outra").step({}, ts=T0))["out"]

    assert (saida.v, saida.ok) == (None, False)


# --------------------------------------------------------------------------------------
# par ponta a ponta (payload real do publicador alimentando o espelho)
# --------------------------------------------------------------------------------------


async def test_par_publica_e_assina_o_mesmo_contrato():
    publica, redis = publicador(ts_seconds=0.5)
    espelho = EspelhoFake()
    assina = assinante(espelho)

    await publica.step({"in": Signal(True, quality=Quality.GOOD)}, ts=T0)
    espelho.ingest(redis.publicados[-1][1])
    saida = (await assina.step({}, ts=T0 + timedelta(seconds=0.5)))["out"]

    assert (saida.v, saida.ok) == (True, True)

    # Publicador parou: o mesmo valor vence em 3 × 0,5 s e o consumidor invalida sozinho.
    expirado = (await assina.step({}, ts=T0 + timedelta(seconds=2)))["out"]
    assert (expirado.v, expirado.ok) == (True, False)


# --------------------------------------------------------------------------------------
# fiação (build_definition): os dois tipos chegam instanciados com os serviços certos
# --------------------------------------------------------------------------------------


def _grafo_bus() -> dict:
    """Assinante -> publicador: a única fiação possível entre os dois (o resto é barramento)."""
    return {
        "nodes": [
            {
                "id": "s1",
                "type": "bus_subscribe",
                "position": {"x": 0, "y": 0},
                "data": {"exec_order": 1, "label": "", "key": KEY},
            },
            {
                "id": "p1",
                "type": "bus_publish",
                "position": {"x": 0, "y": 0},
                "data": {"exec_order": 2, "label": "", "key": "outra"},
            },
        ],
        "edges": [
            {
                "id": "s1-p1",
                "source": "s1",
                "sourceHandle": "out",
                "target": "p1",
                "targetHandle": "in",
            }
        ],
    }


def _build(graph: dict, reuse: dict | None = None, *, exchange: object = None) -> StagedDefinition:
    none: Any = None
    return build_definition(
        parse_graph(graph),
        {},
        flow_id=1,
        ts_seconds=2.0,
        reuse={} if reuse is None else reuse,
        redis_client=none,
        pool=none,
        snapshot=none,
        exchange=cast("Any", exchange),
    )


async def test_build_definition_instancia_os_dois_blocos():
    espelho = EspelhoFake()
    espelho.valores[KEY] = ExchangeValue(key=KEY, ts=T0, v=1.0, ok=True, period_s=2.0)

    staged = _build(_grafo_bus(), exchange=espelho)

    assina = staged.blocks["s1"][1]
    publica = staged.blocks["p1"][1]
    assert isinstance(assina, BusSubscribeBlock)
    assert isinstance(publica, BusPublishBlock)
    # O assinante lê do espelho do processo que o `build_definition` injetou.
    assert (await assina.step({}, ts=T0))["out"].v == 1.0


def test_mudar_a_key_instancia_bloco_novo():
    """Identidade funcional (ADR-011): a `key` é config, então trocá-la re-instancia."""
    grafo = _grafo_bus()
    antes = _build(grafo)
    igual = _build(grafo, reuse=cast("dict", antes.blocks))
    grafo["nodes"][0]["data"]["key"] = "terceira"
    mudado = _build(grafo, reuse=cast("dict", antes.blocks))

    assert igual.blocks["s1"][1] is antes.blocks["s1"][1]
    assert mudado.blocks["s1"][1] is not antes.blocks["s1"][1]
