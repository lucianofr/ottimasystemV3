"""Contratos dos blocos de compensação dinâmica Lead-Lag e Tempo morto.

- **Lead-Lag**: `gain*(tau_lead*s+1)/(tau_lag*s+1)` realizado por decomposição sobre o
  estágio ZOH compartilhado (`lag.py`) — a resposta ao degrau bate com a analítica, ponto a
  ponto. Parte sem salto (prima na primeira amostra válida); não-finito não entra na
  recorrência (retém com `min(UNCERTAIN, q_in)`, BAD sem valor bom anterior).
- **Tempo morto**: fila de `round(theta/Ts)` amostras carregando `Signal`, primada na
  primeira amostra válida (nunca zero-fill), emitindo a qualidade histórica.
"""

import math

import pytest

from ottima_core.signal import Quality
from ottima_flow_runtime.blocks.base import Signal
from ottima_flow_runtime.blocks.dead_time import DeadTimeBlock
from ottima_flow_runtime.blocks.lead_lag import LeadLagBlock

TS = 1.0


def lead_lag(**config: float) -> LeadLagBlock:
    base = {"gain": 1.0, "tau_lead": 20.0, "tau_lag": 10.0}
    return LeadLagBlock("c1", **(base | config), ts_seconds=TS)


async def alimenta(bloco, valor: float, *, quality: Quality = Quality.GOOD) -> Signal:
    return (await bloco.step({"in": Signal(valor, quality=quality)}))["out"]


def resposta_analitica(
    n: int, *, u0: float, u1: float, gain: float, tau_lead: float, tau_lag: float, ts: float
) -> float:
    """`y(t) = K[u1 + (u0-u1)(1-r)e^(-t/tau_lag)]`, com `t = n*Ts` e o bloco partindo de `u0`."""
    r = tau_lead / tau_lag
    return gain * (u1 + (u0 - u1) * (1.0 - r) * math.exp(-n * ts / tau_lag))


# --------------------------------------------------------------------------------------
# Lead-Lag — dinâmica
# --------------------------------------------------------------------------------------


async def test_lead_lag_reproduz_a_resposta_ao_degrau_analitica():
    """Atualiza-e-emite, como o TFS: na varredura n a saída é y(n*Ts), não y((n-1)*Ts)."""
    bloco = lead_lag()
    await alimenta(bloco, 10.0)  # prima em u0 = 10

    for n in range(1, 20):
        saida = await alimenta(bloco, 15.0)
        assert saida.v == pytest.approx(
            resposta_analitica(n, u0=10.0, u1=15.0, gain=1.0, tau_lead=20.0, tau_lag=10.0, ts=TS)
        )


async def test_lead_lag_parte_sem_salto():
    """Primeira amostra válida sai `gain*u`: o sinal está na EU absoluta da planta e partir
    de zero inventaria um transiente — ligado a `bias_in`, um degrau na válvula."""
    assert (await alimenta(lead_lag(gain=2.0), 150.0)).v == pytest.approx(300.0)


async def test_lead_lag_com_tau_lead_igual_ao_lag_e_ganho_puro():
    bloco = lead_lag(tau_lead=10.0, tau_lag=10.0, gain=3.0)
    await alimenta(bloco, 1.0)

    for valor in (2.0, 7.0, -4.0):
        assert (await alimenta(bloco, valor)).v == pytest.approx(3.0 * valor)


async def test_lead_lag_com_tau_lead_zero_e_filtro_de_primeira_ordem():
    """`tau_lead = 0` reduz a G(s) = K/(tau_lag*s+1) — mesma recorrência do `first_order`,
    porque os dois usam o MESMO estágio de `lag.py`."""
    from ottima_flow_runtime.blocks.first_order import FirstOrderBlock

    compensador = lead_lag(tau_lead=0.0, tau_lag=10.0, gain=1.0)
    filtro = FirstOrderBlock("f1", tau=10.0, ts_seconds=TS)

    await alimenta(compensador, 10.0)
    await alimenta(filtro, 10.0)
    for _ in range(10):
        do_compensador = await alimenta(compensador, 15.0)
        do_filtro = await alimenta(filtro, 15.0)
        assert do_compensador.v == pytest.approx(do_filtro.v)


async def test_lead_lag_com_ganho_zero_emite_zero_bom():
    """`gain = 0` desliga o feedforward sem apagar o bloco: saída 0.0 GOOD, não nula."""
    saida = await alimenta(lead_lag(gain=0.0), 42.0)

    assert saida.v == 0.0
    assert saida.quality is Quality.GOOD


async def test_lead_lag_degrada_para_ganho_puro_abaixo_do_limiar_do_ts():
    """`tau_lag < Ts/10`: nenhuma das duas dinâmicas é resolvível na amostragem (a razão está
    limitada a 10 no parse, então `tau_lead` também é sub-Ts). A saída honesta é `gain*u` —
    NUNCA ganho de alta frequência ilimitado."""
    bloco = lead_lag(gain=2.0, tau_lead=0.5, tau_lag=0.05)

    assert (await alimenta(bloco, 10.0)).v == pytest.approx(20.0)
    assert (await alimenta(bloco, 30.0)).v == pytest.approx(60.0)


# --------------------------------------------------------------------------------------
# Lead-Lag — qualidade
# --------------------------------------------------------------------------------------


async def test_lead_lag_com_cold_start_nao_executa():
    saida = (await lead_lag().step({"in": Signal(None)}))["out"]

    assert saida.v is None
    assert saida.ok is False


async def test_lead_lag_propaga_invalidez_com_valor_finito():
    """Decisão A-6, como o `first_order`: executa e propaga — o estado do lag se lava
    sozinho na amostra seguinte."""
    bloco = lead_lag()
    await alimenta(bloco, 10.0)

    saida = await alimenta(bloco, 12.0, quality=Quality.BAD)

    assert saida.v is not None
    assert saida.quality is Quality.BAD


async def test_lead_lag_propaga_uncertain_sem_elevar():
    bloco = lead_lag()
    await alimenta(bloco, 10.0)

    assert (await alimenta(bloco, 12.0, quality=Quality.UNCERTAIN)).quality is Quality.UNCERTAIN


@pytest.mark.parametrize("ruim", [float("nan"), float("inf"), float("-inf")])
async def test_lead_lag_nao_finito_nao_envenena_a_recorrencia(ruim: float):
    """Um nan no lag deixaria a saída nan para sempre, mesmo depois do sinal se recuperar —
    o argumento que `pid.py::_integral` e `integrator.py` já registram."""
    bloco = lead_lag()
    await alimenta(bloco, 10.0)
    boa = await alimenta(bloco, 10.0)

    suja = await alimenta(bloco, ruim)
    assert suja.v == pytest.approx(boa.v)
    assert suja.quality is Quality.UNCERTAIN

    # O estado se cura na amostra seguinte: nunca precisa de redeploy.
    assert (await alimenta(bloco, 10.0)).quality is Quality.GOOD


async def test_lead_lag_nao_finito_sem_valor_bom_anterior_sai_bad():
    """ADR-043 D7: ausência de dado não é retenção — sem valor bom anterior, BAD, não
    UNCERTAIN."""
    saida = await alimenta(lead_lag(), float("nan"))

    assert saida.v is None
    assert saida.quality is Quality.BAD


async def test_lead_lag_nao_finito_com_entrada_bad_permanece_bad():
    """Monotonicidade (D7): retenção nunca eleva qualidade."""
    bloco = lead_lag()
    await alimenta(bloco, 10.0)

    assert (await alimenta(bloco, float("nan"), quality=Quality.BAD)).quality is Quality.BAD


async def test_lead_lag_reset_volta_ao_nao_primado():
    bloco = lead_lag()
    await alimenta(bloco, 10.0)
    await alimenta(bloco, 50.0)

    bloco.reset()

    assert (await alimenta(bloco, 80.0)).v == pytest.approx(80.0)


def test_lead_lag_declara_uma_entrada_e_uma_saida():
    bloco = lead_lag()

    assert bloco.input_ports == ("in",)
    assert bloco.output_ports == ("out",)


# --------------------------------------------------------------------------------------
# Instanciação pelo grafo
# --------------------------------------------------------------------------------------


def _no(tipo: str, **data: object):
    """Nó tipado a partir do JSON real, para não espelhar a forma do config à mão."""
    from ottima_core.flowgraph import parse_graph

    graph = {
        "nodes": [
            {
                "id": "r1",
                "type": "opc_read",
                "position": {"x": 0, "y": 0},
                "data": {"exec_order": 1, "label": "", "tag_id": 10},
            },
            {
                "id": "b1",
                "type": tipo,
                "position": {"x": 0, "y": 0},
                "data": {"exec_order": 2, "label": "", **data},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "r1",
                "target": "b1",
                "sourceHandle": "out",
                "targetHandle": "in",
            }
        ],
    }
    return parse_graph(graph).node("b1")


def _instancia(no, *, ts: float = TS):
    from ottima_flow_runtime.definition import _instantiate

    return _instantiate(
        no,
        flow_id=1,
        ts_seconds=ts,
        tags={},
        redis_client=None,
        pool=None,
        snapshot=None,
        exchange=None,
        write_opc=None,
        mpc_worker_target=None,
        watchdog_enabled=False,
    )


def test_lead_lag_instancia_com_o_ts_do_flow():
    """O bloco recebe o Ts pelo parâmetro de `build_definition`, nunca de `node.config` — o
    scheduler é a única autoridade de tempo do laço."""
    bloco = _instancia(_no("lead_lag", gain=2.0, tau_lead=20.0, tau_lag=10.0))

    assert isinstance(bloco, LeadLagBlock)
    assert bloco.input_ports == ("in",)


# --------------------------------------------------------------------------------------
# Tempo morto
# --------------------------------------------------------------------------------------


def dead_time(theta: float = 3.0, *, ts: float = TS) -> DeadTimeBlock:
    return DeadTimeBlock("d1", theta=theta, ts_seconds=ts)


async def test_dead_time_atrasa_exatamente_d_varreduras():
    bloco = dead_time(3.0)

    saidas = [(await alimenta(bloco, valor)).v for valor in (10.0, 11.0, 12.0, 13.0, 14.0, 15.0)]

    # A fila nasce cheia de 10.0 (as `d=3` cópias da partida) e SÓ ENTÃO recebe o append da
    # própria amostra 1 — quatro instâncias de 10.0 entram antes do primeiro pop, não três.
    # As 4 primeiras saídas repetem a partida (índices 0-3) e, a partir da quinta, cada saída
    # é a entrada de exatamente 3 varreduras atrás: saida[4]=entrada[1]=11, saida[5]=entrada[2]=12.
    assert saidas == [10.0, 10.0, 10.0, 10.0, 11.0, 12.0]


async def test_dead_time_zero_e_passagem_direta():
    bloco = dead_time(0.0)

    assert (await alimenta(bloco, 7.0)).v == 7.0
    assert (await alimenta(bloco, 9.0)).v == 9.0


async def test_dead_time_abaixo_de_meio_ts_vira_passagem_direta_em_silencio():
    """`round(0.4/1.0) == 0`: o bloco não atrasa e não reclama. Comportamento aceito — mas
    quem configurar 0,4 s achando que atrasou vê o sinal passar direto."""
    bloco = dead_time(0.4)

    assert (await alimenta(bloco, 7.0)).v == 7.0
    assert (await alimenta(bloco, 9.0)).v == 9.0


async def test_dead_time_arredonda_half_even_como_o_tfs():
    """`round(2.5) == 2` (banker's): a mesma convenção do TFS, do validate e do MPC."""
    bloco = dead_time(2.5)

    saidas = [(await alimenta(bloco, valor)).v for valor in (1.0, 2.0, 3.0, 4.0)]

    assert saidas == [1.0, 1.0, 1.0, 2.0]


async def test_dead_time_nao_injeta_zero_na_partida():
    """Zero-fill é correto no TFS (variável-desvio) e seria um degrau aqui, onde o sinal está
    na EU absoluta — ligado a `bias_in`, um degrau na válvula por `d` varreduras."""
    assert (await alimenta(dead_time(5.0), 150.0)).v == 150.0


async def test_dead_time_emite_a_qualidade_historica_da_amostra():
    """A saída é a amostra de `d` varreduras atrás: carrega a qualidade DAQUELA amostra, não
    a da entrada corrente."""
    bloco = dead_time(2.0)
    await alimenta(bloco, 1.0)
    await alimenta(bloco, 2.0, quality=Quality.BAD)
    await alimenta(bloco, 3.0)

    saida = await alimenta(bloco, 4.0)

    assert saida.v == 2.0
    assert saida.quality is Quality.BAD


async def test_dead_time_com_cold_start_nao_executa_nem_enche_a_fila():
    bloco = dead_time(2.0)

    nula = (await bloco.step({"in": Signal(None)}))["out"]
    assert nula.v is None
    assert nula.ok is False

    # A fila nasce da PRIMEIRA amostra válida, não da varredura fria.
    assert (await alimenta(bloco, 50.0)).v == 50.0


@pytest.mark.parametrize("ruim", [float("nan"), float("inf")])
async def test_dead_time_nao_finito_sai_nulo_e_invalido(ruim: float):
    """Convenção do `scaler`: nunca nan/inf com ok=True a jusante."""
    bloco = dead_time(1.0)
    await alimenta(bloco, 5.0)
    await alimenta(bloco, ruim)

    saida = await alimenta(bloco, 6.0)

    assert saida.v is None
    assert saida.ok is False


async def test_dead_time_reset_esvazia_a_fila():
    bloco = dead_time(2.0)
    for valor in (1.0, 2.0, 3.0):
        await alimenta(bloco, valor)

    bloco.reset()

    assert (await alimenta(bloco, 99.0)).v == 99.0


def test_dead_time_declara_uma_entrada_e_uma_saida():
    bloco = dead_time()

    assert bloco.input_ports == ("in",)
    assert bloco.output_ports == ("out",)


def test_dead_time_instancia_com_o_ts_do_flow():
    bloco = _instancia(_no("dead_time", theta=30.0))

    assert isinstance(bloco, DeadTimeBlock)
    assert bloco.input_ports == ("in",)
