"""L2 do fechamento de tech debts — blocos de filtro sem cenário no gate E2E (TD-012).

Cenário E2E-TD-10. Os blocos de filtro (ADR-026, `first_order`/`kalman`) têm 39 casos de
contrato/validação, 28 de runtime e 6 de instanciação/hot-swap, mas nenhum cenário L2 — o
plano da feature declarou a prova ponta a ponta fora do escopo. Este arquivo cobre o que
faltou: um flow `opc_read -> kalman -> opc_write` deployado contra o stack real, provando que
o bloco filtra de verdade (a saída diverge da leitura bruta na MESMA varredura, porque o
Kalman suaviza em vez de repassar) e que o valor filtrado chega de fato à planta simulada, não
só ao barramento interno do runtime.

`first_order` não ganha cenário próprio aqui: os dois blocos de filtro têm o mesmo contrato
de porta única/config escalar (RF-531) e o mesmo caminho de execução no motor de varredura —
o E2E-TD-10 cobre o gênero "bloco de filtro deployado" através do Kalman, que é o mais rico
dos dois para provar (o 1ª ordem em regime permanente pode convergir para igual ao bruto; o
Kalman com ruído de medição alto não).
"""

from typing import Any

import httpx
import pytest

from opcsim import NODE_MIRROR_FLOAT

from .conftest import Ambiente, OpcSim, esperar_ate
from .f3_support import (
    aresta,
    assinantes_de_status,
    bloco,
    de_varredura,
    deploy,
    fabrica_de_flows,
    montar_grafo,
    valor,
)

pytestmark = pytest.mark.e2e

# `measurement_noise` bem acima da amplitude de ruído real da senoide (que não tem ruído
# nenhum, só variação determinística) força um ganho de Kalman baixo: a saída anda devagar
# atrás da leitura bruta em vez de segui-la quase exata varredura a varredura — é o que torna
# a divergência visível em qualquer amostra pós-partida, não só nas primeiras.
MEASUREMENT_NOISE = 6.0
PROCESS_NOISE = 0.2


@pytest.fixture
def assinar_status(redis_bus: Any) -> Any:
    yield from assinantes_de_status(redis_bus)


@pytest.fixture
def criar_flow(admin: httpx.Client, projeto_com_conexao: Ambiente) -> Any:
    yield from fabrica_de_flows(admin, projeto_com_conexao)


def _grafo_kalman(ambiente: Ambiente) -> dict:
    return montar_grafo(
        [
            bloco("leitura", "opc_read", 1, tag_id=ambiente.sine),
            bloco(
                "filtro",
                "kalman",
                2,
                measurement_noise=MEASUREMENT_NOISE,
                process_noise=PROCESS_NOISE,
            ),
            bloco("escrita", "opc_write", 3, tag_id=ambiente.w_float),
        ],
        [
            aresta("leitura", "out", "filtro", "in"),
            aresta("filtro", "out", "escrita", "in"),
        ],
    )


def test_e2e_td_10_kalman_deployado_filtra_e_escreve_na_planta(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    criar_flow: Any,
    assinar_status: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-TD-10/TD-012: `opc_read -> kalman -> opc_write` deployado contra o stack real."""
    ambiente = projeto_com_conexao
    flow_id = criar_flow("td-10-kalman", grafo=_grafo_kalman(ambiente))
    status = assinar_status(flow_id)

    deploy(admin, flow_id)
    primeira = status.esperar(
        de_varredura, timeout=30.0, descricao="primeira varredura do flow leitura->kalman->escrita"
    )
    assert primeira["state"] == "running"

    # A 1ª varredura nasce com `x = medição` (partida sem salto do bloco): já foi consumida
    # acima de propósito, para as amostras seguintes começarem depois da inicialização.
    amostras = status.coletar(
        quantidade=8, timeout=30.0, descricao="varreduras do kalman após a partida"
    )
    divergiu = False
    for amostra in amostras:
        assert de_varredura(amostra), "amostra sem `ports` no meio da coleta"
        bruto = valor(amostra, "leitura", "out")
        filtrado = valor(amostra, "filtro", "out")
        escrito = valor(amostra, "escrita", "in")
        assert isinstance(filtrado, float), (
            f"porta `out` do kalman sem valor numérico: {filtrado!r}"
        )
        # O `opc_write` a jusante recebe, íntegra, a mesma amostra que o filtro publicou.
        assert escrito == pytest.approx(filtrado)
        if abs(float(filtrado) - float(bruto)) > 1e-6:
            divergiu = True
    assert divergiu, "saída do Kalman idêntica à leitura bruta em toda a janela — não filtrou"

    # Prova ponta a ponta: o valor filtrado não fica só no barramento interno do runtime — a
    # tag de destino chega a refletir uma escrita real na planta simulada (espelho de
    # `sim.w.float`), e a escrita continua viva (não travou num valor só).
    def _ler_espelho() -> float | None:
        valor_lido = opcsim_client.read(NODE_MIRROR_FLOAT)
        return valor_lido if valor_lido else None

    espelho_inicial = esperar_ate(
        _ler_espelho,
        timeout=20.0,
        intervalo=1.0,
        descricao="espelho do opcsim (sim.mirror.float) refletir a escrita do kalman",
    )
    assert 0.0 <= espelho_inicial <= 100.0, (
        f"espelho fora da faixa física da senoide (fonte do filtro): {espelho_inicial}"
    )
    esperar_ate(
        lambda: abs(opcsim_client.read(NODE_MIRROR_FLOAT) - espelho_inicial) > 1e-6,
        timeout=20.0,
        intervalo=1.0,
        descricao="espelho do opcsim seguir mudando (escrita contínua do kalman, não travada)",
    )
    print("\nE2E-TD-10: kalman deployado filtrou (divergiu do bruto) e escreveu na planta")
