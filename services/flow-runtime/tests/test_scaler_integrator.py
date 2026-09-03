"""Contratos dos blocos utilitários Scaler e Integrator.

- **Scaler**: reescala linear sem estado — `out = out_min + (in - in_min) * ganho`, com
  `ganho = (out_max - out_min) / (in_max - in_min)`. Fora da faixa de entrada extrapola
  (nunca trava: quem limita é a config de escala, não o bloco).
- **Integrator**: totalizador com estado — `out += in * Ts / fator` por varredura, fator
  1/60/3600 para base s/min/h. O Ts vem do scheduler (única autoridade de tempo, ADR-031)
  — nada de relógio de parede. `reset` ≠ 0 zera o total e a varredura sai 0, sem acumular.
"""

import pytest

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.integrator import IntegratorBlock
from ottima_flow_runtime.blocks.scaler import ScalerBlock

TS = 1.0


def scaler(**escala: float) -> ScalerBlock:
    config = {"in_min": 0.0, "in_max": 100.0, "out_min": 4.0, "out_max": 20.0} | escala
    return ScalerBlock("s1", **config)


def integrator(time_base: str = "min", *, ts: float = TS) -> IntegratorBlock:
    return IntegratorBlock("i1", time_base=time_base, ts_seconds=ts)


async def alimenta(
    block: ScalerBlock | IntegratorBlock,
    valor: float,
    *,
    ok: bool = True,
    reset: object = ...,
) -> PortSample:
    entradas: dict[str, PortSample] = {"in": PortSample(valor, ok)}
    if reset is not ...:
        entradas["reset"] = PortSample(reset, True)  # type: ignore[arg-type]
    return (await block.step(entradas))["out"]


# --------------------------------------------------------------------------------------
# Scaler — mapeamento linear
# --------------------------------------------------------------------------------------


async def test_scaler_mapeia_os_extremos_da_escala():
    bloco = scaler()

    assert (await alimenta(bloco, 0.0)).v == 4.0
    assert (await alimenta(bloco, 100.0)).v == 20.0


async def test_scaler_mapeia_valor_intermediario_proporcionalmente():
    assert (await alimenta(scaler(), 50.0)).v == pytest.approx(12.0)


async def test_scaler_aceita_faixa_de_saida_invertida():
    bloco = scaler(out_min=100.0, out_max=0.0)

    assert (await alimenta(bloco, 25.0)).v == pytest.approx(75.0)


async def test_scaler_extrapola_fora_da_faixa_sem_travar():
    assert (await alimenta(scaler(), 150.0)).v == pytest.approx(28.0)


async def test_scaler_propaga_invalidez_da_entrada():
    saida = await alimenta(scaler(), 50.0, ok=False)

    assert saida.v == pytest.approx(12.0)
    assert saida.ok is False


async def test_scaler_com_cold_start_nao_executa():
    saida = (await scaler().step({"in": PortSample(None, False)}))["out"]

    assert saida.v is None
    assert saida.ok is False


def test_scaler_declara_uma_entrada_e_uma_saida():
    bloco = scaler()

    assert bloco.input_ports == ("in",)
    assert bloco.output_ports == ("out",)


# --------------------------------------------------------------------------------------
# Integrator — acumulação no tempo do flow
# --------------------------------------------------------------------------------------


async def test_integrator_acumula_na_base_minuto():
    """6 unidades/min com Ts=1 s ⇒ 0,1 por varredura; 60 varreduras totalizam 6."""
    bloco = integrator("min")
    for _ in range(59):
        await alimenta(bloco, 6.0)

    assert (await alimenta(bloco, 6.0)).v == pytest.approx(6.0)


async def test_integrator_acumula_na_base_segundo():
    bloco = integrator("s")

    assert (await alimenta(bloco, 2.5)).v == pytest.approx(2.5)
    assert (await alimenta(bloco, 2.5)).v == pytest.approx(5.0)


async def test_integrator_acumula_na_base_hora():
    bloco = integrator("h", ts=0.5)

    assert (await alimenta(bloco, 3600.0)).v == pytest.approx(0.5)


async def test_integrator_reset_ativo_zera_o_total_e_a_varredura():
    bloco = integrator("s")
    await alimenta(bloco, 5.0)
    await alimenta(bloco, 5.0)

    assert (await alimenta(bloco, 5.0, reset=1.0)).v == 0.0
    assert (await alimenta(bloco, 5.0, reset=0.0)).v == pytest.approx(5.0)


async def test_integrator_integra_a_variavel_e_nao_o_valor_instantaneo():
    """Entrada variável acumula amostra a amostra (soma de Riemann no Ts do flow)."""
    bloco = integrator("s", ts=2.0)
    saida = await alimenta(bloco, 1.0)
    for valor in (2.0, 3.0):
        saida = await alimenta(bloco, valor)

    assert saida.v == pytest.approx(12.0)


async def test_integrator_reset_cold_nao_zera():
    """`reset` conectado sem valor ainda (None) não é comando de zerar."""
    bloco = integrator("s")
    await alimenta(bloco, 5.0)

    assert (await alimenta(bloco, 5.0, reset=None)).v == pytest.approx(10.0)


async def test_integrator_propaga_invalidez_da_entrada():
    saida = await alimenta(integrator("s"), 5.0, ok=False)

    assert saida.v == pytest.approx(5.0)
    assert saida.ok is False


async def test_integrator_amostra_nao_finita_nao_envenena_o_total():
    """inf/nan não entram no acumulador: retém o total e marca a varredura inválida."""
    bloco = integrator("s")
    await alimenta(bloco, 5.0)

    suja = await alimenta(bloco, float("nan"))
    assert suja.v == pytest.approx(5.0)
    assert suja.ok is False
    # O estado se cura na amostra seguinte — nunca precisa de redeploy para voltar.
    assert (await alimenta(bloco, 5.0)).v == pytest.approx(10.0)


async def test_integrator_ignora_reset_sem_qualidade():
    """Comando de zerar vindo de amostra inválida não apaga o total."""
    bloco = integrator("s")
    await alimenta(bloco, 5.0)

    saida = (await bloco.step({"in": PortSample(5.0, True), "reset": PortSample(1.0, False)}))[
        "out"
    ]

    assert saida.v == pytest.approx(10.0)


async def test_integrator_com_cold_start_nao_executa_nem_avanca_o_estado():
    bloco = integrator("s")

    nula = (await bloco.step({"in": PortSample(None, False)}))["out"]
    assert nula.v is None
    assert nula.ok is False
    assert (await alimenta(bloco, 5.0)).v == pytest.approx(5.0)


async def test_integrator_reset_de_deploy_zera_o_total():
    bloco = integrator("s")
    await alimenta(bloco, 5.0)

    bloco.reset()

    assert (await alimenta(bloco, 5.0)).v == pytest.approx(5.0)


def test_integrator_declara_duas_entradas_e_uma_saida():
    bloco = integrator()

    assert bloco.input_ports == ("in", "reset")
    assert bloco.output_ports == ("out",)
