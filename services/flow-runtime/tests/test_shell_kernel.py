"""Protocolo do kernel (ADR-039 secao 4.5) e o stub deterministico dos testes S."""

import math

from ottima_flow_runtime.blocks.shell.kernel import ControlKernel, StubKernel


def test_stub_satisfaz_o_protocol() -> None:
    kernel: ControlKernel = StubKernel()
    assert kernel.validate() == []


def test_stub_proporcional_ao_erro_mais_taxa_constante() -> None:
    k = StubKernel(gain=2.0, rate=0.5)
    assert k.compute(sp=10.0, pv=7.0, dt=0.5) == 2.0 * 3.0 + 0.5


def test_stub_registra_align_e_reset_limpa() -> None:
    k = StubKernel()
    k.align(50.0, 10.0, 9.0)
    assert k.align_calls == [(50.0, 10.0, 9.0)]
    k.reset()
    assert k.align_calls == []


def test_stub_pode_devolver_nan() -> None:
    k = StubKernel()
    k.rate = math.nan
    assert math.isnan(k.compute(0.0, 0.0, 1.0))


def test_stub_erros_de_validacao_configuraveis() -> None:
    k = StubKernel()
    k.errors.append("CONFIG_QUALQUER")
    assert k.validate() == ["CONFIG_QUALQUER"]
