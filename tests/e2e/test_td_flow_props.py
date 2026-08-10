"""L2 do fechamento de tech debts — propriedades do flow pelo PUT (cenário E2E-TD-09).

`PUT /api/flows/{id}` passou a aceitar `ts_seconds` e a tratar `graph_json` como opcional:
o diálogo de propriedades do editor troca nome e Ts sem carregar o desenho. Os dois casos
são provados contra o stack real, e a evidência do Ts novo é a CADÊNCIA do `flow.status`,
não o código HTTP — o que importa é o runtime ter recebido o reload, não a API ter gravado.

Trocar o Ts continua derrubando o MPC para LOCAL (fronteira deliberada do TD-006: o
transplante de estado vale para resintonia com o mesmo conjunto de MVs, nunca para troca de
Ts, que reconstrói todos os blocos do flow).
"""

from collections.abc import Callable, Iterator
from datetime import datetime
from statistics import median
from typing import Any

import httpx
import pytest
import redis

from .conftest import (
    TS_FLOW_MPC,
    AmbienteMpc,
    OpcSim,
    armar_ate_remoto,
    assinar_mpc_state,
    deploy_flow,
    grafo_mpc_tfs,
    resetar_atuador_mpc,
)
from .f3_support import StatusStream, assinantes_de_status

pytestmark = pytest.mark.e2e

TS_NOVO = 2.0
"""Ts alvo do cenário: 4x o Ts original, folga suficiente para a cadência ser inequívoca."""

AMOSTRAS_CADENCIA = 5
"""Amostras consecutivas de `flow.status` por medição — a mediana dos intervalos absorve o
jitter de uma varredura isolada sem precisar de tolerância larga."""


@pytest.fixture
def assinar_status(redis_bus: redis.Redis) -> Iterator[Any]:
    yield from assinantes_de_status(redis_bus)


def cadencia_mediana(status: StatusStream, *, descricao: str) -> float:
    """Intervalo mediano entre carimbos consecutivos de `flow.status` (= Ts efetivo).

    Cada medição usa uma assinatura RECÉM-ABERTA (ver chamadores): o pubsub acumula tudo o
    que chegou desde a inscrição, e uma assinatura antiga entregaria as centenas de amostras
    enfileiradas durante o arme e o reload — todas no Ts VELHO. Medir a cadência nova em cima
    de mensagens velhas foi exatamente o falso negativo que este comentário existe para evitar.
    """
    amostras = status.coletar(
        quantidade=AMOSTRAS_CADENCIA,
        timeout=AMOSTRAS_CADENCIA * TS_NOVO + 20.0,
        descricao=descricao,
    )
    carimbos = [datetime.fromisoformat(amostra["ts"]) for amostra in amostras]
    intervalos = [
        (depois - antes).total_seconds()
        for antes, depois in zip(carimbos, carimbos[1:], strict=False)
    ]
    assert intervalos, f"{descricao}: menos de duas amostras para medir cadência"
    return median(intervalos)


def test_e2e_td_09_trocar_o_ts_recadencia_o_flow_e_reseta_o_mpc(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Callable[..., int],
    opcsim_client: OpcSim,
    assinar_status: Callable[[int], StatusStream],
) -> None:
    """`PUT {ts_seconds}` em flow rodando: 200, varredura recadenciada e MPC de volta a LOCAL."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("td-09-ts", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        armar_ate_remoto(admin, fluxo, flow_id, "mpc1")

        antes = cadencia_mediana(assinar_status(flow_id), descricao="cadência antes da troca de Ts")
        assert abs(antes - TS_FLOW_MPC) < TS_FLOW_MPC / 2, (
            f"cadência inicial {antes:.3f}s não bate com o Ts de criação {TS_FLOW_MPC}s"
        )

        resposta = admin.put(f"/api/flows/{flow_id}", json={"ts_seconds": TS_NOVO})
        assert resposta.status_code == 200, (
            f"PUT do Ts: HTTP {resposta.status_code} {resposta.text}"
        )
        assert float(resposta.json()["flow"]["ts_seconds"]) == TS_NOVO

        # Reconstrução completa do flow: o bloco novo nasce zerado, em LOCAL.
        fluxo.esperar(
            lambda estado: estado["modes"]["local_remote"] == "local",
            timeout=60.0,
            descricao="MPC de volta a LOCAL depois da troca de Ts",
        )

        depois = cadencia_mediana(
            assinar_status(flow_id), descricao="cadência depois da troca de Ts"
        )

    assert abs(depois - TS_NOVO) < TS_NOVO / 2, (
        f"cadência depois da troca {depois:.3f}s não bate com o Ts novo {TS_NOVO}s "
        f"(antes: {antes:.3f}s)"
    )


def test_e2e_td_09_rename_sem_graph_json_preserva_o_desenho(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Callable[..., int],
) -> None:
    """`PUT {name}` sem `graph_json`: renomeia, mantém o grafo salvo e revalida sem reprovar.

    A revalidação acontece de qualquer jeito (o par grafo+Ts efetivo é validado junto), então
    o risco real é ela reprovar um grafo que já estava gravado. Um 422 aqui seria exatamente
    a regressão que este cenário existe para pegar.
    """
    flow_id = criar_flow_mpc("td-09-rename", grafo=grafo_mpc_tfs(ambiente_mpc))
    original = admin.get(f"/api/flows/{flow_id}")
    assert original.status_code == 200
    grafo_antes = original.json()["graph_json"]
    ts_antes = float(original.json()["ts_seconds"])

    nome_novo = f"{original.json()['name']}-renomeado"
    resposta = admin.put(f"/api/flows/{flow_id}", json={"name": nome_novo})
    assert resposta.status_code == 200, f"PUT do nome: HTTP {resposta.status_code} {resposta.text}"

    salvo = resposta.json()["flow"]
    assert salvo["name"] == nome_novo
    assert salvo["graph_json"] == grafo_antes, "rename não pode tocar no grafo salvo"
    assert float(salvo["ts_seconds"]) == ts_antes, "rename não pode tocar no Ts"
