"""L2 do fechamento de tech debts — hot-swap com transplante de estado (TD-006).

Cenários E2E-TD-01/02/03. A política fixada é: mudar a SINTONIA do MPC (pesos, limites,
max_rate) com o MESMO conjunto de MVs preserva REMOTO/AUTO com rearme bumpless; mudar o
CONJUNTO de MVs continua derrubando o bloco para LOCAL. Salvar o flow com o grafo idêntico
não pode nem reconstruir o bloco.

O que estes cenários protegem é um incidente real: em 2026-08-09T15:19:58Z um `flow_updated`
disparado pela UI derrubou um controlador em regime no meio de um degrau. O gate aqui é o
evento de auditoria MAIS a continuidade observada da MV — só o evento provaria a intenção,
não o efeito.
"""

import copy
import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import redis

from ottima_core.bus import CHANNEL_EVENTS

from .conftest import (
    DU_MAX_MV,
    LIMITES_MV,
    AmbienteMpc,
    OpcSim,
    armar_ate_remoto,
    armar_auto_com_retentativa,
    assinar_mpc_state,
    deploy_flow,
    evento_mpc,
    grafo_mpc_tfs,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e

JANELA_SWAP_S = 25.0
"""Folga para o supervisor reconstruir o bloco e o host novo terminar o build."""

QUADROS_APOS_SWAP = 12
"""Quadros observados depois do PUT — cobre o build do host novo e os primeiros solves."""

TOLERANCIA_DU = 1e-6


class ColetorEventos:
    """Todos os eventos do canal numa janela — para provar AUSÊNCIA, que `EventStream` não faz.

    `EventStream.esperar` responde "veio o evento X"; aqui a pergunta é a inversa ("nenhum
    evento de reset apareceu"), e ela só tem resposta honesta drenando a janela inteira.
    """

    def __init__(self, pubsub: redis.client.PubSub) -> None:
        self._pubsub = pubsub

    def drenar(self, *, duracao: float) -> list[dict[str, Any]]:
        fim = time.monotonic() + duracao
        recebidos: list[dict[str, Any]] = []
        while time.monotonic() < fim:
            mensagem = self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
            if mensagem is not None and mensagem.get("type") == "message":
                recebidos.append(json.loads(mensagem["data"]))
        return recebidos


@pytest.fixture
def coletor_eventos(redis_bus: redis.Redis) -> Any:
    pubsub = redis_bus.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(CHANNEL_EVENTS)
    try:
        yield ColetorEventos(pubsub)
    finally:
        pubsub.close()


def motivos_de_modo(eventos: list[dict[str, Any]], flow_id: int, block_id: str) -> list[str]:
    """`reason` de cada `mpc_mode_changed` do bloco, na ordem em que chegaram."""
    casa = evento_mpc("mpc_mode_changed", flow_id, block_id)
    return [str(e.get("payload", {}).get("reason", "")) for e in eventos if casa(e)]


def _bloco_mpc(grafo: dict[str, Any], block_id: str = "mpc1") -> dict[str, Any]:
    for no in grafo["nodes"]:
        if no["id"] == block_id:
            return no
    raise AssertionError(f"bloco {block_id} ausente do grafo")


def grafo_com_peso_de_cv(ambiente: AmbienteMpc, *, peso: float) -> dict[str, Any]:
    """Mesma topologia, só o `weight` de `cv_1` muda: resintonia pura, MVs intactas."""
    grafo = copy.deepcopy(grafo_mpc_tfs(ambiente))
    _bloco_mpc(grafo)["data"]["variables"]["cvs"][0]["weight"] = peso
    return grafo


def grafo_com_mv_extra(ambiente: AmbienteMpc) -> dict[str, Any]:
    """MV nova no bloco. Sem aresta (como `mv_direta`), mas com par habilitado em `co_1` —
    exigência da validação: toda MV precisa de pelo menos um par na matriz (spec §2.2-3)."""
    grafo = copy.deepcopy(grafo_mpc_tfs(ambiente))
    dados = _bloco_mpc(grafo)["data"]
    dados["variables"]["mvs"].append(
        {
            "id": "mv_extra",
            "name": "MV acrescentada",
            "eu": "%",
            "limits": dict(LIMITES_MV),
            "max_rate": DU_MAX_MV,
            "initial_value": 0.0,
        }
    )
    dados["models"]["co_1"]["mv_extra"] = {"enabled": True, "params": {"Ki": 1e-4, "theta": 0.0}}
    return grafo


def salvar_grafo(admin: httpx.Client, flow_id: int, grafo: dict[str, Any]) -> dict[str, Any]:
    resposta = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo})
    assert resposta.status_code == 200, f"PUT do grafo: HTTP {resposta.status_code} {resposta.text}"
    return resposta.json()


def _armar_em_auto(admin: httpx.Client, fluxo: Any, flow_id: int, block_id: str = "mpc1") -> None:
    armar_ate_remoto(admin, fluxo, flow_id, block_id)
    armar_auto_com_retentativa(admin, fluxo, flow_id, block_id)


def test_e2e_td_01_resintonia_preserva_auto_e_nao_da_salto_na_mv(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Callable[..., int],
    opcsim_client: OpcSim,
    coletor_eventos: ColetorEventos,
) -> None:
    """E2E-TD-01: mudar o peso de uma CV mantém AUTO, com rearme bumpless e MV sem salto."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("td-01", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        _armar_em_auto(admin, fluxo, flow_id)
        # Descarta os `mpc_mode_changed` das transições de ARMAR: o que este cenário observa
        # é só o que o PUT provoca, e um evento de arme sem `reason` poluiria a lista.
        coletor_eventos.drenar(duracao=1.0)
        salvar_grafo(admin, flow_id, grafo_com_peso_de_cv(ambiente_mpc, peso=2.0))

        quadros = fluxo.coletar(
            quantidade=QUADROS_APOS_SWAP,
            timeout=JANELA_SWAP_S + 20.0,
            descricao="quadros durante e depois do hot-swap",
        )
        eventos = coletor_eventos.drenar(duracao=2.0)

    modos = [quadro["modes"]["man_auto"] for quadro in quadros]
    assert all(modo == "auto" for modo in modos), (
        f"o bloco saiu de AUTO durante a resintonia: {modos}"
    )
    remoto = [quadro["modes"]["local_remote"] for quadro in quadros]
    assert all(estado == "remote" for estado in remoto), (
        f"o bloco caiu para LOCAL durante a resintonia: {remoto}"
    )

    motivos = motivos_de_modo(eventos, flow_id, "mpc1")
    assert "hot_swap_bumpless" in motivos, (
        f"faltou a auditoria do transplante em `mpc_mode_changed`; motivos vistos: {motivos}"
    )
    assert "hot_swap" not in motivos, (
        f"o supervisor devolveu o comando ao PLC (reset), motivos vistos: {motivos}"
    )

    valores = [quadro["vars"]["mv_pid"]["v"] for quadro in quadros]
    saltos = [abs(depois - antes) for antes, depois in zip(valores, valores[1:], strict=False)]
    assert all(salto <= DU_MAX_MV + TOLERANCIA_DU for salto in saltos), (
        f"MV saltou além de du_max/ciclo ({DU_MAX_MV}) durante o swap: {saltos}"
    )


def test_e2e_td_02_adicionar_mv_ainda_derruba_para_local(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Callable[..., int],
    opcsim_client: OpcSim,
    coletor_eventos: ColetorEventos,
) -> None:
    """E2E-TD-02: mudar o CONJUNTO de MVs continua sendo reset — a fronteira do transplante.

    O bloco novo tem outra dimensão de estado: transplantar `u_prev` de um conjunto para
    outro seria semear o modelo interno com um valor sem dono.
    """
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("td-02", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        _armar_em_auto(admin, fluxo, flow_id)
        coletor_eventos.drenar(duracao=1.0)
        salvar_grafo(admin, flow_id, grafo_com_mv_extra(ambiente_mpc))

        fluxo.esperar(
            lambda estado: estado["modes"]["local_remote"] == "local",
            timeout=JANELA_SWAP_S + 20.0,
            descricao="bloco de volta a LOCAL depois de mudar o conjunto de MVs",
        )
        eventos = coletor_eventos.drenar(duracao=2.0)

    motivos = motivos_de_modo(eventos, flow_id, "mpc1")
    assert "hot_swap" in motivos, f"faltou o evento de reset do hot-swap; motivos vistos: {motivos}"


def test_e2e_td_03_salvar_grafo_identico_nao_reconstroi_o_bloco(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Callable[..., int],
    opcsim_client: OpcSim,
    coletor_eventos: ColetorEventos,
) -> None:
    """E2E-TD-03: PUT com o grafo idêntico é persistência pura — nenhuma troca de modo.

    Regressão do reuse por igualdade de `functional_config()`: se ele quebrar, todo salvamento
    de layout (arrastar um bloco) passa a reconstruir o controlador.
    """
    resetar_atuador_mpc(opcsim_client)
    grafo = grafo_mpc_tfs(ambiente_mpc)
    flow_id = criar_flow_mpc("td-03", grafo=grafo)

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        _armar_em_auto(admin, fluxo, flow_id)

        antes = fluxo.esperar(
            lambda estado: estado["modes"]["man_auto"] == "auto",
            timeout=20.0,
            descricao="quadro de referência antes do PUT",
        )
        coletor_eventos.drenar(duracao=1.0)
        salvar_grafo(admin, flow_id, grafo)

        quadros = fluxo.coletar(
            quantidade=QUADROS_APOS_SWAP,
            timeout=JANELA_SWAP_S + 20.0,
            descricao="quadros depois do PUT idêntico",
        )
        eventos = coletor_eventos.drenar(duracao=2.0)

    motivos = motivos_de_modo(eventos, flow_id, "mpc1")
    assert motivos == [], f"PUT idêntico não pode mexer em modo; motivos vistos: {motivos}"

    assert all(quadro["modes"]["man_auto"] == "auto" for quadro in quadros)
    assert all(quadro["status"]["solver"] != "building" for quadro in quadros), (
        "o host foi reconstruído num PUT idêntico — o reuse por config quebrou"
    )
    contadores = [quadro["status"]["overruns"] for quadro in quadros]
    assert all(
        depois >= antes_c for antes_c, depois in zip(contadores, contadores[1:], strict=False)
    ), f"o contador de overruns regrediu, sinal de instância nova: {contadores}"
    assert contadores[0] >= antes["status"]["overruns"], (
        "o contador de overruns zerou depois do PUT idêntico — instância nova"
    )
