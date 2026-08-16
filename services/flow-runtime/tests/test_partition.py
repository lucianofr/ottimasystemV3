"""Posse de flow por partição e agregação de saúde do pai (ADR-004, `partition.py`).

O que estes testes protegem, na ordem da gravidade:

1. **Cobertura exata.** Todo `flow_id` pertence a EXATAMENTE uma partição. Se dois processos se
   dissessem donos do mesmo flow, os dois escreveriam na mesma tag OPC — o pior defeito
   possível num sistema de controle. Se nenhum se dissesse dono, o `deploy` cairia no vazio e o
   operador veria um comando sem efeito e sem recusa.
2. **`count == 1` é o caminho de sempre.** Sem partição, `owns` é sempre verdadeiro e o
   `service` do `/health` sai sem sufixo — é o que mantém intactos o agregador da API, a chave
   única do frontend e o assert do `deploy/smoke.sh`.
3. **Filtro de comando.** `flow.commands` é canal único: toda partição recebe todo comando, e
   quem não é dono precisa sair sem tocar em nada.
4. **Forma do `/health` do pai.** As três chaves de `script_pool` que o smoke exige
   (`smoke.sh:164`) e a união de `flows` continuam existindo com N processos.
"""

from datetime import UTC, datetime

import pytest
from runtime_test_helpers import counter_graph, create_flow, create_project

from ottima_core.bus import FlowCommand
from ottima_flow_runtime.partition import UNPARTITIONED, Partition, PartitionParent


def test_todo_flow_id_pertence_a_exatamente_uma_particao():
    """Invariante central: nem flow órfão, nem flow com dois donos."""
    for count in (1, 2, 3, 4, 8):
        particoes = [Partition(index=i, count=count) for i in range(count)]
        for flow_id in range(200):
            donos = [p.index for p in particoes if p.owns(flow_id)]
            assert donos == [flow_id % count], f"count={count} flow={flow_id} donos={donos}"


def test_sem_particao_tudo_e_meu_e_o_rotulo_e_vazio():
    """`count == 1` não pode mudar nada: nem posse, nem o `service` do `/health`."""
    assert UNPARTITIONED == Partition(index=0, count=1)
    assert not UNPARTITIONED.enabled
    assert UNPARTITIONED.label == ""
    assert all(UNPARTITIONED.owns(flow_id) for flow_id in (0, 1, 7, 12345))


def test_particao_real_se_identifica_no_rotulo():
    """Com N processos, log e `/health` precisam dizer QUAL processo falou."""
    particao = Partition(index=2, count=4)
    assert particao.enabled
    assert particao.label == "[2/4]"


@pytest.mark.parametrize(
    ("index", "count"),
    [(0, 0), (-1, 1), (1, 1), (4, 4), (-1, 4)],
)
def test_particao_invalida_levanta_na_construcao(index: int, count: int):
    """Índice fora de `0..count-1` é erro de configuração e tem de aparecer no boot, não em
    silêncio — um índice inválido significaria flows sem dono nenhum."""
    with pytest.raises(ValueError):
        Partition(index=index, count=count)


async def test_supervisor_ignora_comando_de_flow_de_outra_particao(
    harness_factory, session_factory
):
    """Canal único: a partição que não é dona sai sem tocar em nada.

    O flow existe e o grafo é válido — o único motivo de nada acontecer é a posse. Sem o
    filtro, este mesmo comando subiria uma segunda `FlowTask` do mesmo flow noutro processo,
    e as duas escreveriam na mesma tag.
    """
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=counter_graph())
    # Índice derivado do id REAL (serial do banco), nunca de paridade presumida.
    alheia = Partition(index=(flow_id + 1) % 2, count=2)
    harness = await harness_factory(partition=alheia)

    await harness.supervisor.handle_command(_deploy(flow_id))

    assert harness.supervisor.flows == {}


async def test_supervisor_atende_comando_do_proprio_flow(harness_factory, session_factory):
    """Controle do teste acima: mesma montagem, partição dona — o deploy acontece."""
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=counter_graph())
    minha = Partition(index=flow_id % 2, count=2)
    harness = await harness_factory(partition=minha)

    await harness.supervisor.handle_command(_deploy(flow_id))

    assert list(harness.supervisor.flows) == [flow_id]


def _deploy(flow_id: int) -> FlowCommand:
    return FlowCommand(flow_id=flow_id, cmd="deploy", args={}, user="teste", ts=datetime.now(UTC))


async def test_health_do_pai_preserva_o_formato_com_filhos_mortos():
    """Pai sem filho vivo responde `degraded` mantendo as chaves que os consumidores exigem.

    Não sobe filho nenhum de propósito (`target` que retorna na hora): o que está sob teste é a
    FORMA do corpo no pior caso, que é justamente quando um consumidor quebraria por chave
    faltante. As três chaves de `script_pool` são contrato do `deploy/smoke.sh`.
    """
    parent = PartitionParent(2, target=_filho_que_sai)
    await parent.start()
    try:
        corpo = await parent.health()
    finally:
        await parent.stop()

    assert corpo["status"] == "degraded"
    assert corpo["flows"] == {}
    assert set(corpo["script_pool"]) == {"size", "busy", "respawns"}
    assert set(corpo["partitions"]) == {"0", "1"}
    assert all(fatia["status"] == "degraded" for fatia in corpo["partitions"].values())


async def test_particao_que_falhou_no_spawn_volta_na_passada_seguinte(monkeypatch):
    """Falha de `spawn` não pode aposentar um índice.

    `_terminate_owned` tira a entrada do mapa ANTES de repor, então um `proc.start()` que levante
    deixa o índice ausente. Se a passada de reposição iterasse só `self._children`, aquela
    partição ficaria morta para sempre — os flows dela surdos a todo `deploy` — e o `try/except`
    do laço do monitor não resolveria nada disso: ele salva a task, não a partição.

    Também cobre `start()`: a falha de um índice não pode abortar os outros nem impedir a criação
    do monitor, que é justamente quem repõe.
    """
    parent = PartitionParent(2, target=_filho_que_sai)
    original = parent._start_child
    falhou_uma_vez = False

    def start_child_falhando(index: int):
        nonlocal falhou_uma_vez
        if index == 1 and not falhou_uma_vez:
            falhou_uma_vez = True
            raise OSError("sem recurso do SO para o fork/exec")
        return original(index)

    monkeypatch.setattr(parent, "_start_child", start_child_falhando)

    await parent.start()
    try:
        assert falhou_uma_vez, "o cenário não exercitou a falha de spawn"
        assert 0 in parent.child_pids, "a falha do índice 1 não podia derrubar o índice 0"
        assert 1 not in parent.child_pids, "índice que falhou deveria estar ausente do mapa"

        # Uma passada do monitor, chamada direto para o teste não esperar MONITOR_INTERVAL_S.
        await parent._repor_mortos()

        assert 1 in parent.child_pids, "a partição ausente não foi reposta"
    finally:
        await parent.stop()

    assert parent.child_pids == {}, "stop() deixou filho para trás"


def _filho_que_sai(index: int, count: int, port: int) -> None:
    """Alvo de `spawn` que retorna na hora — nível de módulo porque `spawn` precisa importá-lo."""
    return
