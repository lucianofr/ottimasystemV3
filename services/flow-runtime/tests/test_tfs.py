"""Contratos do bloco TFS contra a solução analítica (RF-521/522, ADR-022, spec F3 §3.4).

Fase da recorrência (contrato da fase): na varredura n o elemento consome a entrada já
atrasada e emite a resposta daquela fronteira, então um degrau unitário aplicado a partir da
varredura 1 dá `y[n] = K*(1 - a^n)` — exatamente `K*(1 - e^(-n*Ts/tau))`. É isso que permite
travar o caso de primeira ordem como igualdade, e não como aproximação.
"""

import math

import pytest

from ottima_core.flowgraph import IopdtParams, SopdtParams, TfsElement
from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.tfs import TfsBlock

TS = 0.5  # Ts do critério de aceite da fase (PRD §8-F3)


def sopdt(
    *, K: float = 1.0, tau1: float = 0.0, tau2: float = 0.0, theta: float = 0.0
) -> TfsElement:
    return TfsElement(
        enabled=True, kind="sopdt", params=SopdtParams(K=K, tau1=tau1, tau2=tau2, theta=theta)
    )


def iopdt(*, Ki: float, theta: float = 0.0) -> TfsElement:
    return TfsElement(enabled=True, kind="iopdt", params=IopdtParams(Ki=Ki, theta=theta))


def off() -> TfsElement:
    """Elemento desabilitado: ganho zero, sem estado e sem consumo de entrada."""
    return TfsElement(
        enabled=False, kind="sopdt", params=SopdtParams(K=1.0, tau1=1.0, tau2=0.0, theta=0.0)
    )


def tfs(
    *,
    y1: tuple[TfsElement, TfsElement] | None = None,
    y2: tuple[TfsElement, TfsElement] | None = None,
    ts: float = TS,
) -> TfsBlock:
    """`matrix[J][K]` = contribuição de `uK` para `yJ` (spec §3.4)."""
    rows = [list(y1 or (off(), off())), list(y2 or (off(), off()))]
    return TfsBlock("t1", matrix=rows, ts_seconds=ts)


async def series(
    block: TfsBlock,
    n: int,
    *,
    u1: float | None = 1.0,
    u2: float | None = None,
    port: str = "y1",
) -> list[float]:
    """Roda `n` varreduras com entrada constante e devolve a série de uma saída.

    `None` significa porta **ausente** de `inputs` (não conectada), não valor nulo.
    """
    values: list[float] = []
    for _ in range(n):
        inputs = {}
        if u1 is not None:
            inputs["u1"] = PortSample(u1, True)
        if u2 is not None:
            inputs["u2"] = PortSample(u2, True)
        values.append((await block.step(inputs))[port].v)
    return values


def first_order(K: float, tau: float, t: float) -> float:
    return K * (1.0 - math.exp(-t / tau))


def second_order(K: float, tau1: float, tau2: float, t: float) -> float:
    numerator = tau1 * math.exp(-t / tau1) - tau2 * math.exp(-t / tau2)
    return K * (1.0 - numerator / (tau1 - tau2))


def double_pole(K: float, tau: float, t: float) -> float:
    return K * (1.0 - (1.0 + t / tau) * math.exp(-t / tau))


# --------------------------------------------------------------------------------------
# Resposta ao degrau vs solução analítica
# --------------------------------------------------------------------------------------


async def test_primeira_ordem_pura_e_zoh_exata():
    """`tau2 < Ts/10` degrada o 2o estágio: sobra um 1a ordem, que o ZOH resolve exato."""
    block = tfs(y1=(sopdt(K=2.0, tau1=20.0, tau2=TS / 100), off()))

    got = await series(block, 80)

    for n, value in enumerate(got, start=1):
        assert value == pytest.approx(first_order(2.0, 20.0, n * TS), rel=1e-12)


async def test_segunda_ordem_segue_a_solucao_analitica():
    """Cascata de dois ZOH exatos != ZOH exato do produto.

    O 2o estágio consome `x1[n]` (fim do intervalo) como se fosse constante em todo o
    intervalo, o que adianta o sinal intermediário em meia amostra. O erro é então limitado
    por `Ts/2 * max|dy/dt|`: com Ts=0,5, tau1=20, tau2=5 e K=2 esse teto vale 0,0157 e o
    erro medido é 0,0154 (pico em t=9 s, 0,77% de K). Tolerância 0,02 = teto + ~30% de
    folga; ela cai proporcional a Ts (0,0091 em Ts=0,25), o que confirma o termo O(Ts).
    """
    block = tfs(y1=(sopdt(K=2.0, tau1=20.0, tau2=5.0), off()))

    got = await series(block, 400)

    for n, value in enumerate(got, start=1):
        assert value == pytest.approx(second_order(2.0, 20.0, 5.0, n * TS), abs=0.02)
    # Invariantes que valem exatamente, independentes da tolerância acima.
    # `strict=False` é deliberado: o par (y[n], y[n+1]) tem um elemento menos que a série.
    assert all(b > a for a, b in zip(got, got[1:], strict=False))  # monotônica crescente
    assert got[-1] == pytest.approx(2.0, abs=1e-3)  # regime permanente = K


async def test_degrau_ainda_nao_aplicado_da_saida_zero():
    """Sem excitação não há resposta: entrada 0.0 é valor legítimo, não invalidez."""
    block = tfs(y1=(sopdt(K=2.0, tau1=20.0, tau2=5.0), off()))

    out = await block.step({"u1": PortSample(0.0, True)})

    assert out["y1"] == PortSample(0.0, True)


async def test_polo_duplo_nao_divide_por_zero():
    """`tau1 == tau2`: a forma de polos distintos é singular, a implementação não pode ser.

    Mesmo raciocínio de tolerância do caso distinto: teto `Ts/2 * max|dy/dt|` = 0,0184 com
    tau=10 e K=2; erro medido 0,0181 (pico em t=10 s). Tolerância 0,025 = teto + ~35%.
    """
    block = tfs(y1=(sopdt(K=2.0, tau1=10.0, tau2=10.0), off()))

    got = await series(block, 400)

    for n, value in enumerate(got, start=1):
        assert value == pytest.approx(double_pole(2.0, 10.0, n * TS), abs=0.025)
    assert got[-1] == pytest.approx(2.0, abs=1e-3)


async def test_iopdt_integra_exatamente():
    block = tfs(y1=(iopdt(Ki=0.25), off()))

    got = await series(block, 40)

    for n, value in enumerate(got, start=1):
        assert value == pytest.approx(0.25 * n * TS, rel=1e-12)


# --------------------------------------------------------------------------------------
# Tempo morto
# --------------------------------------------------------------------------------------


async def test_tempo_morto_atrasa_a_resposta_em_d_amostras():
    delayed = await series(tfs(y1=(sopdt(K=2.0, tau1=20.0, tau2=5.0, theta=5 * TS), off())), 60)
    plain = await series(tfs(y1=(sopdt(K=2.0, tau1=20.0, tau2=5.0), off())), 60)

    assert delayed[:5] == [0.0] * 5
    assert delayed[5:] == plain[:-5]


@pytest.mark.parametrize(("theta", "samples"), [(2.6, 5), (3.4, 7)])
async def test_tempo_morto_arredonda_e_nao_trunca(theta: float, samples: int):
    """`d = round(theta/Ts)`: 2,6/0,5 = 5,2 -> 5; 3,4/0,5 = 6,8 -> 7 (truncar daria 6)."""
    got = await series(tfs(y1=(iopdt(Ki=1.0, theta=theta), off())), samples + 3)

    assert got[:samples] == [0.0] * samples
    assert got[samples] == pytest.approx(TS, rel=1e-12)


# --------------------------------------------------------------------------------------
# Robustez numérica: limiar Ts/10
# --------------------------------------------------------------------------------------


async def test_tau_desprezivel_degrada_para_passagem_direta():
    block = tfs(y1=(sopdt(K=3.0, tau1=TS / 100, tau2=TS / 100), off()))

    assert await series(block, 3) == [3.0, 3.0, 3.0]


async def test_tau_zero_degrada_para_passagem_direta():
    block = tfs(y1=(sopdt(K=3.0, tau1=0.0, tau2=0.0), off()))

    assert await series(block, 3) == [3.0, 3.0, 3.0]


async def test_tau_acima_do_limiar_continua_dinamico():
    """`tau = Ts/9` está acima de `Ts/10`: o par prova que o limiar é o da spec."""
    tau = TS / 9
    block = tfs(y1=(sopdt(K=3.0, tau1=tau, tau2=TS / 100), off()))

    got = await series(block, 4)

    assert got[0] != 3.0
    for n, value in enumerate(got, start=1):
        assert value == pytest.approx(first_order(3.0, tau, n * TS), rel=1e-12)


# --------------------------------------------------------------------------------------
# Matriz: superposição, linha desabilitada, colunas ausentes
# --------------------------------------------------------------------------------------


async def test_linha_soma_as_contribuicoes_habilitadas():
    from_u1 = sopdt(K=2.0, tau1=20.0, tau2=5.0)
    from_u2 = iopdt(Ki=0.1)

    both = await series(tfs(y1=(from_u1, from_u2)), 30, u1=1.0, u2=0.5)
    only_u1 = await series(tfs(y1=(from_u1, off())), 30, u1=1.0, u2=0.5)
    only_u2 = await series(tfs(y1=(off(), from_u2)), 30, u1=1.0, u2=0.5)

    for total, a, b in zip(both, only_u1, only_u2, strict=True):
        assert total == pytest.approx(a + b, rel=1e-12)


async def test_linha_toda_desabilitada_e_ganho_zero_valido():
    """ADR-022: ganho zero é valor legítimo, não invalidez."""
    block = tfs(y1=(sopdt(K=2.0, tau1=20.0, tau2=5.0), off()))

    for _ in range(3):
        out = await block.step({"u1": PortSample(1.0, True)})
        assert out["y2"] == PortSample(0.0, True)


async def test_coluna_sem_elemento_habilitado_pode_faltar_em_inputs():
    """`u2` é obrigatória só se a coluna 2 tem elemento habilitado (spec §3.4)."""
    block = tfs(y1=(iopdt(Ki=1.0), off()), y2=(iopdt(Ki=2.0), off()))

    out = await block.step({"u1": PortSample(1.0, True)})

    assert out["y1"] == PortSample(TS, True)
    assert out["y2"] == PortSample(2.0 * TS, True)


async def test_ok_reflete_apenas_as_entradas_consumidas_pela_linha():
    """Linha que não consome nada não pode herdar a invalidez de outra coluna."""
    block = tfs(y1=(iopdt(Ki=1.0), off()), y2=(off(), iopdt(Ki=1.0)))

    out = await block.step({"u1": PortSample(1.0, False), "u2": PortSample(1.0, True)})

    assert out["y1"].ok is False
    assert out["y2"].ok is True


async def test_invalidez_de_entrada_nao_impede_a_integracao():
    """Decisão A-6: com valor conhecido o TFS continua integrando e só propaga a flag."""
    block = tfs(y1=(iopdt(Ki=1.0), off()))

    out = await block.step({"u1": PortSample(2.0, False)})

    assert out["y1"] == PortSample(1.0, False)


# --------------------------------------------------------------------------------------
# Estado
# --------------------------------------------------------------------------------------


async def test_cold_start_nao_executa_nem_avanca_o_estado():
    """Spec §3.0: entrada sem valor não faz o integrador andar."""
    block = tfs(y1=(iopdt(Ki=1.0), off()))

    out = await block.step({"u1": PortSample(None, False)})
    assert out == {"y1": PortSample(None, False), "y2": PortSample(None, False)}

    # Se o estado tivesse avançado, a varredura seguinte devolveria 2*Ts.
    assert (await block.step({"u1": PortSample(1.0, True)}))["y1"].v == pytest.approx(TS)


async def test_reset_zera_estado_fila_de_atraso_e_acumulador():
    """Depois de um degrau longo, `reset()` faz a resposta recomeçar idêntica à primeira."""
    block = tfs(
        y1=(sopdt(K=2.0, tau1=20.0, tau2=5.0, theta=3 * TS), off()),
        y2=(iopdt(Ki=1.0, theta=2 * TS), off()),
    )

    async def sweep(n: int) -> list[tuple[float, float]]:
        collected: list[tuple[float, float]] = []
        for _ in range(n):
            out = await block.step({"u1": PortSample(1.0, True)})
            collected.append((out["y1"].v, out["y2"].v))
        return collected

    before = await sweep(30)
    block.reset()
    after = await sweep(30)

    assert before[0] == (0.0, 0.0)  # as filas de atraso começam cheias de zeros
    assert before[-1] != (0.0, 0.0)  # e o estado realmente andou antes do reset
    assert after == before


async def test_estado_nao_e_compartilhado_entre_instancias():
    element = iopdt(Ki=1.0)
    first = tfs(y1=(element, off()))
    second = tfs(y1=(element, off()))

    await series(first, 10)
    out = await second.step({"u1": PortSample(1.0, True)})

    assert out["y1"].v == pytest.approx(TS)


async def test_portas_declaradas_sao_fixas():
    block = tfs(y1=(iopdt(Ki=1.0), off()))

    assert block.input_ports == ("u1", "u2")
    assert block.output_ports == ("y1", "y2")
