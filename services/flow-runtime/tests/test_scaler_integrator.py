"""Contratos dos blocos utilitários Scaler e Integrator.

- **Scaler**: reescala linear sem estado — `out = out_min + (in - in_min) * ganho`, com
  clamp na faixa de saída fora da faixa de entrada (spike de sensor nunca vira escrita
  além do OUT_SCALE) e saída nula/inválida para amostra não-finita.
- **Integrator**: totalizador com estado — `out += in * dt / fator`, fator 1/60/3600 para
  base s/min/h. O `dt` é medido entre os `ts` do scheduler (overrun pula fronteira sem
  compensar: Ts nominal subcontaria); `dt <= 0` ou `dt > 10×Ts` congela e invalida, e a
  primeira varredura com valor só inicia o relógio. Amostra `ok=False` ou não-finita
  congela o total (erro de totalizador é permanente — não vale a A-6 do filtro).
  `reset` ≠ 0 com qualidade boa zera o total e a varredura sai 0, sem acumular.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import pytest

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.integrator import IntegratorBlock
from ottima_flow_runtime.blocks.scaler import ScalerBlock

TS = 1.0
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def scaler(**escala: float) -> ScalerBlock:
    config = {"in_min": 0.0, "in_max": 100.0, "out_min": 4.0, "out_max": 20.0} | escala
    return ScalerBlock("s1", **config)


def integrator(time_base: Literal["s", "min", "h"] = "min", *, ts: float = TS) -> IntegratorBlock:
    return IntegratorBlock("i1", time_base=time_base, ts_seconds=ts)


async def alimenta_scaler(bloco: ScalerBlock, valor: float, *, ok: bool = True) -> PortSample:
    return (await bloco.step({"in": PortSample(valor, ok)}))["out"]


class Totaliza:
    """Dirige um IntegratorBlock com relógio explícito: cada chamada avança `passo`."""

    def __init__(self, bloco: IntegratorBlock, *, passo: float = TS) -> None:
        self.bloco = bloco
        self.passo = passo
        self.agora = T0

    async def alimenta(self, valor: float, *, ok: bool = True, reset: object = ...) -> PortSample:
        entradas: dict[str, PortSample] = {"in": PortSample(valor, ok)}
        if reset is not ...:
            entradas["reset"] = PortSample(cast("float | bool | None", reset), True)
        saida = (await self.bloco.step(entradas, ts=self.agora))["out"]
        self.agora += timedelta(seconds=self.passo)
        return saida


# --------------------------------------------------------------------------------------
# Scaler — mapeamento linear
# --------------------------------------------------------------------------------------


async def test_scaler_mapeia_os_extremos_da_escala():
    bloco = scaler()

    assert (await alimenta_scaler(bloco, 0.0)).v == 4.0
    assert (await alimenta_scaler(bloco, 100.0)).v == 20.0


async def test_scaler_mapeia_valor_intermediario_proporcionalmente():
    assert (await alimenta_scaler(scaler(), 50.0)).v == pytest.approx(12.0)


async def test_scaler_aceita_faixa_de_saida_invertida():
    bloco = scaler(out_min=100.0, out_max=0.0)

    assert (await alimenta_scaler(bloco, 25.0)).v == pytest.approx(75.0)


async def test_scaler_extrapola_fora_da_faixa_sem_travar():
    """Bloco de escala é conversão de unidade: over-range chega ao operador/alarme/MPC —
    limitar é função de outro bloco."""
    bloco = scaler()

    assert (await alimenta_scaler(bloco, 150.0)).v == pytest.approx(28.0)
    assert (await alimenta_scaler(bloco, -50.0)).v == pytest.approx(-4.0)

    invertido = scaler(out_min=100.0, out_max=0.0)
    assert (await alimenta_scaler(invertido, 150.0)).v == pytest.approx(-50.0)


async def test_scaler_amostra_nao_finita_sai_nula_e_invalida():
    """Convenção da casa (fuzzy/pid): nunca nan/inf com ok=True na saída."""
    for ruim in (float("nan"), float("inf"), float("-inf")):
        saida = await alimenta_scaler(scaler(), ruim)

        assert saida.v is None
        assert saida.ok is False


async def test_scaler_propaga_invalidez_da_entrada():
    saida = await alimenta_scaler(scaler(), 50.0, ok=False)

    assert saida.v == pytest.approx(12.0)
    assert saida.ok is False


async def test_scaler_com_cold_start_nao_executa():
    saida = (await scaler().step({"in": PortSample(None, False)}))["out"]

    assert saida.v is None
    assert saida.ok is False


# --------------------------------------------------------------------------------------
# Integrator — acumulação no tempo medido pelo scheduler
# --------------------------------------------------------------------------------------


async def test_integrator_primeira_varredura_so_inicia_o_relogio():
    """Sem dt conhecido não há o que acumular: o total nasce zero, não in*Ts."""
    totaliza = Totaliza(integrator("s"))

    assert (await totaliza.alimenta(6.0)).v == 0.0
    assert (await totaliza.alimenta(6.0)).v == pytest.approx(6.0)


async def test_integrator_acumula_na_base_minuto():
    """6 unidades/min com dt=1 s ⇒ 0,1 por varredura após a inicialização."""
    totaliza = Totaliza(integrator("min"))
    await totaliza.alimenta(6.0)  # inicializa o relógio
    for _ in range(59):
        await totaliza.alimenta(6.0)

    assert (await totaliza.alimenta(6.0)).v == pytest.approx(6.0)


async def test_integrator_acumula_na_base_segundo():
    totaliza = Totaliza(integrator("s"))
    await totaliza.alimenta(2.5)

    assert (await totaliza.alimenta(2.5)).v == pytest.approx(2.5)
    assert (await totaliza.alimenta(2.5)).v == pytest.approx(5.0)


async def test_integrator_acumula_na_base_hora():
    totaliza = Totaliza(integrator("h"), passo=0.5)
    await totaliza.alimenta(3600.0)

    assert (await totaliza.alimenta(3600.0)).v == pytest.approx(0.5)


async def test_integrator_usa_o_dt_do_scheduler_e_nao_o_ts_nominal():
    """Overrun pula fronteira sem compensar: dt=2 s com Ts=1 s soma 2×, não 1×."""
    totaliza = Totaliza(integrator("s"), passo=2.0)
    await totaliza.alimenta(3.0)

    assert (await totaliza.alimenta(3.0)).v == pytest.approx(6.0)


async def test_integrator_congela_em_salto_de_relogio():
    """dt > 10×Ts é salto de NTP/parada longa: somar seria integrar um delta corrupto."""
    totaliza = Totaliza(integrator("s"))
    await totaliza.alimenta(5.0)
    await totaliza.alimenta(5.0)  # total = 5

    totaliza.agora += timedelta(hours=1)
    suspeita = await totaliza.alimenta(5.0)
    assert suspeita.v == pytest.approx(5.0)
    assert suspeita.ok is False

    # O relógio foi reancorado na varredura do salto: a seguinte volta a acumular.
    assert (await totaliza.alimenta(5.0)).v == pytest.approx(10.0)


async def test_integrator_congela_em_dt_nao_positivo():
    bloco = integrator("s")
    await bloco.step({"in": PortSample(5.0, True)}, ts=T0)
    await bloco.step({"in": PortSample(5.0, True)}, ts=T0 + timedelta(seconds=1))

    saida = (await bloco.step({"in": PortSample(5.0, True)}, ts=T0))["out"]

    assert saida.v == pytest.approx(5.0)
    assert saida.ok is False


async def test_integrator_sem_ts_cai_no_ts_nominal():
    """Chamador fora do scheduler (teste de pureza) usa o Ts configurado."""
    bloco = integrator("s")

    assert (await bloco.step({"in": PortSample(2.5, True)}))["out"].v == pytest.approx(2.5)


async def test_integrator_integra_a_variavel_e_nao_o_valor_instantaneo():
    totaliza = Totaliza(integrator("s"), passo=2.0)
    await totaliza.alimenta(1.0)  # inicializa
    saida = await totaliza.alimenta(2.0)  # +4
    saida = await totaliza.alimenta(3.0)  # +6

    assert saida.v == pytest.approx(10.0)


async def test_integrator_reset_ativo_zera_o_total_e_a_varredura():
    totaliza = Totaliza(integrator("s"))
    await totaliza.alimenta(5.0)
    await totaliza.alimenta(5.0)

    assert (await totaliza.alimenta(5.0, reset=1.0)).v == 0.0
    # Zerou sem acumular a amostra da varredura do reset; a seguinte recomeça do zero —
    # o relógio foi reancorado no instante do reset.
    assert (await totaliza.alimenta(5.0)).v == pytest.approx(5.0)


async def test_integrator_sem_aresta_no_reset_nunca_zera():
    totaliza = Totaliza(integrator("s"))
    await totaliza.alimenta(1.0)
    for _ in range(2):
        saida = await totaliza.alimenta(1.0)

    assert saida.v == pytest.approx(2.0)


async def test_integrator_reset_cold_nao_zera():
    """`reset` conectado sem valor ainda (None) não é comando de zerar."""
    totaliza = Totaliza(integrator("s"))
    await totaliza.alimenta(5.0)

    assert (await totaliza.alimenta(5.0, reset=None)).v == pytest.approx(5.0)


async def test_integrator_ignora_reset_sem_qualidade():
    """Tag de reset morta e congelada em 1 não apaga o total da planta."""
    bloco = integrator("s")
    await bloco.step({"in": PortSample(5.0, True)}, ts=T0)
    await bloco.step({"in": PortSample(5.0, True)}, ts=T0 + timedelta(seconds=1))

    saida = (
        await bloco.step(
            {"in": PortSample(5.0, True), "reset": PortSample(1.0, False)},
            ts=T0 + timedelta(seconds=2),
        )
    )["out"]

    assert saida.v == pytest.approx(10.0)


async def test_integrator_amostra_sem_qualidade_nao_acumula():
    """A-6 não vale para totalizador: valor de tag morta congelaria erro no acumulado."""
    totaliza = Totaliza(integrator("s"))
    await totaliza.alimenta(5.0)
    await totaliza.alimenta(5.0)  # total = 5

    ruim = await totaliza.alimenta(999.0, ok=False)
    assert ruim.v == pytest.approx(5.0)
    assert ruim.ok is False

    assert (await totaliza.alimenta(5.0)).v == pytest.approx(10.0)


async def test_integrator_amostra_nao_finita_nao_envenena_o_total():
    """inf/nan não entram no acumulador: retém o total e marca a varredura inválida."""
    totaliza = Totaliza(integrator("s"))
    await totaliza.alimenta(5.0)
    await totaliza.alimenta(5.0)  # total = 5

    suja = await totaliza.alimenta(float("nan"))
    assert suja.v == pytest.approx(5.0)
    assert suja.ok is False
    # O estado se cura na amostra seguinte — nunca precisa de redeploy para voltar.
    assert (await totaliza.alimenta(5.0)).v == pytest.approx(10.0)


async def test_integrator_buraco_de_qualidade_e_pulado_nunca_preenchido_retroativamente():
    """3 scans ruins seguidos: a amostra boa seguinte integra só o seu dt — o relógio é
    reancorado a cada scan ruim, senão o intervalo morto seria somado com o valor novo."""
    totaliza = Totaliza(integrator("s"))
    await totaliza.alimenta(5.0)
    await totaliza.alimenta(5.0)  # total = 5

    for _ in range(3):
        await totaliza.alimenta(999.0, ok=False)

    assert (await totaliza.alimenta(5.0)).v == pytest.approx(10.0)


async def test_integrator_com_cold_start_nao_executa_nem_avanca_o_estado():
    totaliza = Totaliza(integrator("s"))

    nula = (await totaliza.bloco.step({"in": PortSample(None, False)}))["out"]
    assert nula.v is None
    assert nula.ok is False

    await totaliza.alimenta(5.0)  # inicializa
    assert (await totaliza.alimenta(5.0)).v == pytest.approx(5.0)


async def test_integrator_reset_de_deploy_zera_o_total_e_o_relogio():
    totaliza = Totaliza(integrator("s"))
    await totaliza.alimenta(5.0)
    await totaliza.alimenta(5.0)

    totaliza.bloco.reset()

    assert (await totaliza.alimenta(5.0)).v == 0.0  # primeiro scan pós-deploy só inicia
    assert (await totaliza.alimenta(5.0)).v == pytest.approx(5.0)


def test_integrator_declara_duas_entradas_e_uma_saida():
    bloco = integrator()

    assert bloco.input_ports == ("in", "reset")
    assert bloco.output_ports == ("out",)
