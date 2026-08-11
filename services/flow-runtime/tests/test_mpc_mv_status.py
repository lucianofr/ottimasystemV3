"""Consumo do status de disponibilidade da MV pelo `MpcBlock` (ADR-028).

Complementa `test_mpc_availability.py` (classificador puro) com o comportamento do bloco:
o que vai no `SolveRequest`, o que sai na porta, o que é escrito no `pid` e o que é
publicado/auditado. Mesmos duplos de `test_mpc_block.py` (host/snapshot falsos, sem do-mpc
e sem Redis) — reusados por import para os dois arquivos nunca divergirem sobre o que é um
`MpcBlock` de teste.

Cenários de aceite do ADR-028:
(a) MV sai de RCAS durante a execução e volta — a saída não salta em nenhuma das duas
    transições, e o movimento de volta parte da posição REAL;
(b) MV com leitura de má qualidade é excluída da otimização e sua escrita no `pid` é
    suprimida — sem derrubar o bloco;
(c) reclassificar uma MV não afeta as MVs saudáveis do mesmo ciclo.
"""

from __future__ import annotations

from test_mpc_block import (
    OPERADOR,
    Events,
    FakeHost,
    FakeSnapshot,
    Publishes,
    Writes,
    _block,
    _resultado_ok,
    entradas,
)

from ottima_core.bus import KIND_MPC_MV_STATUS_CHANGED
from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.mpc import MpcBlock
from ottima_flow_runtime.mpc.availability import MvAvailability

READBACK_PID = 503
MODE_READ_PID = 504
WRITE_PID = 501
READBACK_DIRETO = 601


def _bloco_com_mode_read(
    **kwargs: object,
) -> tuple[MpcBlock, FakeHost, FakeSnapshot, Publishes, Writes, Events]:
    """Bloco com `mode_read` na MV com `pid` e readback na MV direta — só assim as duas MVs
    são observáveis e a independência entre elas pode ser exercitada."""
    return _block(mode_read=MODE_READ_PID, readback_direto=READBACK_DIRETO, **kwargs)  # type: ignore[arg-type]


def _tudo_saudavel(snapshot: FakeSnapshot, *, mv_pid: float = 40.0, mv_direto: float = 3.0) -> None:
    snapshot.set(READBACK_PID, mv_pid)
    snapshot.set(MODE_READ_PID, 1.0)
    snapshot.set(READBACK_DIRETO, mv_direto)


async def _arma_auto(block: MpcBlock) -> None:
    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    await block.command("mpc_mode", {"axis": "man_auto", "value": "auto"}, OPERADOR)


# --------------------------------------------------------------------------------------
# Classificação por varredura e publicação
# --------------------------------------------------------------------------------------


async def test_status_das_mvs_e_publicado_no_estado() -> None:
    block, _, snapshot, publish, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await block.step(entradas(20.0))
    vars_ = publish.states[-1].vars
    assert vars_["mv_pid"].status == MvAvailability.RCAS_OK.value
    assert vars_["mv_direto"].status == MvAvailability.RCAS_OK.value


async def test_status_ausente_nas_linhas_que_nao_sao_mv() -> None:
    """`status` é campo de MV — CV/Restrição/DV publicam `None`, como `sp` só existe em CV."""
    block, _, snapshot, publish, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await block.step(entradas(20.0))
    assert publish.states[-1].vars["cv_a"].status is None


async def test_mode_read_divergente_publica_local_override() -> None:
    block, _, snapshot, publish, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    snapshot.set(MODE_READ_PID, 0.0)
    await block.step(entradas(20.0))
    assert publish.states[-1].vars["mv_pid"].status == MvAvailability.LOCAL_OVERRIDE.value


# --------------------------------------------------------------------------------------
# (b) Exclusão da otimização
# --------------------------------------------------------------------------------------


async def test_mv_com_qualidade_ruim_entra_congelada_no_solve_request() -> None:
    block, host, snapshot, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await _arma_auto(block)
    snapshot.set(READBACK_PID, 40.0, quality=2)
    await block.step(entradas(20.0))
    assert host.requests[-1].frozen_mvs == frozenset({"mv_pid"})


async def test_mv_fora_de_rcas_entra_congelada_com_o_valor_medido() -> None:
    """LOCAL_OVERRIDE tem leitura VÁLIDA: o `u_applied` congelado é a posição real, que é o
    que faz a MV valer como distúrbio medido na predição das CVs (ADR-028)."""
    block, host, snapshot, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await _arma_auto(block)
    snapshot.set(READBACK_PID, 61.0)
    snapshot.set(MODE_READ_PID, 0.0)
    await block.step(entradas(20.0))
    assert host.requests[-1].frozen_mvs == frozenset({"mv_pid"})
    assert host.requests[-1].u_applied["mv_pid"] == 61.0


async def test_mv_com_leitura_ruim_congela_no_ultimo_valor_conhecido() -> None:
    """BAD_QUALITY não tem posição confiável: o `u_applied` segura o último valor bom
    (`_mv_last`), nunca o lixo da amostra ruim — visto em campo, readback voltando `0,0`
    com `quality=2` num restart da planta."""
    block, host, snapshot, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot, mv_pid=55.0)
    await _arma_auto(block)
    await block.step(entradas(20.0))
    snapshot.set(READBACK_PID, 0.0, quality=2)
    await block.step(entradas(20.0))
    assert host.requests[-1].u_applied["mv_pid"] == 55.0


async def test_escrita_no_pid_da_mv_indisponivel_e_suprimida() -> None:
    """O núcleo do problema: sem BKCAL, escrever numa MV que não está ouvindo é o que
    prepara o bump da volta. A escrita dela para; as demais seguem."""
    block, _, snapshot, _, writes, _ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await _arma_auto(block)
    snapshot.set(MODE_READ_PID, 0.0)
    writes.writes.clear()
    await block.step(entradas(20.0))
    assert [w.tag_id for w in writes.writes] == []


async def test_escrita_no_pid_volta_quando_a_mv_retorna_a_rcas() -> None:
    block, _, snapshot, _, writes, _ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await _arma_auto(block)
    snapshot.set(MODE_READ_PID, 0.0)
    await block.step(entradas(20.0))
    snapshot.set(MODE_READ_PID, 1.0)
    writes.writes.clear()
    await block.step(entradas(20.0))
    assert [w.tag_id for w in writes.writes] == [WRITE_PID]


# --------------------------------------------------------------------------------------
# (a) Sem bump na saída, ida e volta
# --------------------------------------------------------------------------------------


async def test_saida_da_mv_indisponivel_segue_a_posicao_real_sem_saltar() -> None:
    """Enquanto a malha está sob controle local, a porta da MV reporta a posição REAL — não
    o plano do MPC. Sem isso a porta contaria uma história que o atuador não viveu, e a
    devolução do controle partiria dessa ficção."""
    block, host, snapshot, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await _arma_auto(block)
    host.pending = _resultado_ok({"mv_pid": 44.0, "mv_direto": 3.0})
    await block.step(entradas(20.0))

    snapshot.set(MODE_READ_PID, 0.0)
    snapshot.set(READBACK_PID, 70.0)  # o PID local levou o atuador para outro lugar
    saida = await block.step(entradas(20.0))
    assert saida["mv_pid"] == PortSample(70.0, True)


async def test_volta_a_rcas_parte_da_posicao_real_e_nao_do_plano_antigo() -> None:
    """Aceite (a) do ADR-028: a MV volta a RCAS e o próximo movimento parte da posição
    física, não do último valor que o MPC calculou antes de perder a malha."""
    block, host, snapshot, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await _arma_auto(block)
    host.pending = _resultado_ok({"mv_pid": 44.0, "mv_direto": 3.0})
    await block.step(entradas(20.0))

    snapshot.set(MODE_READ_PID, 0.0)
    snapshot.set(READBACK_PID, 70.0)
    await block.step(entradas(20.0))

    snapshot.set(MODE_READ_PID, 1.0)
    await block.step(entradas(20.0))
    pedido = host.requests[-1]
    assert pedido.frozen_mvs == frozenset()
    assert pedido.u_applied["mv_pid"] == 70.0


async def test_volta_a_rcas_nao_reaplica_o_plano_anterior_a_perda_da_malha() -> None:
    """A porta na volta: o plano guardado foi calculado ANTES de a malha ser tomada, contra
    outra posição e outra condição de planta. Reaplicá-lo no primeiro quadro após o retorno
    é um degrau instantâneo, sem passar pelo Δu — o mesmo erro que a §4.4 já evita em
    MAN->AUTO (`_plan = None`). Enquanto a MV está congelada o solve devolve o plano dela
    igual à posição medida, então o caso perigoso é a janela em que NENHUM resultado novo
    chega (worker ocupado/overrun) — é essa que este teste força, não entregando nada."""
    block, host, snapshot, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await _arma_auto(block)
    host.pending = _resultado_ok({"mv_pid": 44.0, "mv_direto": 3.0})
    assert (await block.step(entradas(20.0)))["mv_pid"] == PortSample(44.0, True)

    snapshot.set(MODE_READ_PID, 0.0)
    snapshot.set(READBACK_PID, 70.0)  # o PID local moveu o atuador
    await block.step(entradas(20.0))

    snapshot.set(MODE_READ_PID, 1.0)
    saida = await block.step(entradas(20.0))
    assert saida["mv_pid"] == PortSample(70.0, True)
    assert saida["mv_direto"] == PortSample(3.0, True), "MV saudável mantém seu plano"


# --------------------------------------------------------------------------------------
# (c) Independência entre MVs
# --------------------------------------------------------------------------------------


async def test_mv_saudavel_segue_recebendo_o_plano_com_a_outra_congelada() -> None:
    block, host, snapshot, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await _arma_auto(block)
    snapshot.set(READBACK_PID, 40.0, quality=2)
    host.pending = _resultado_ok({"mv_pid": 40.0, "mv_direto": 4.0})
    saida = await block.step(entradas(20.0))
    assert saida["mv_direto"] == PortSample(4.0, True)


async def test_bloco_nao_sai_de_auto_por_causa_de_uma_mv_indisponivel() -> None:
    """Modo degradado: o MPC segue em AUTO com o conjunto reduzido de MVs (ADR-028 D1) —
    o shed do bloco inteiro fica reservado ao caso em que NENHUMA MV sobra."""
    block, _, snapshot, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await _arma_auto(block)
    snapshot.set(MODE_READ_PID, 0.0)
    await block.step(entradas(20.0))
    assert block.local_remote == "remote"
    assert block.health()["mode"]["man_auto"] == "auto"


# --------------------------------------------------------------------------------------
# Auditoria e gate de arme
# --------------------------------------------------------------------------------------


async def test_transicao_de_status_gera_evento_uma_vez_so() -> None:
    block, _, snapshot, _, _, events = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await block.step(entradas(20.0))
    snapshot.set(MODE_READ_PID, 0.0)
    await block.step(entradas(20.0))
    await block.step(entradas(20.0))  # mesma condição: não repete o evento
    emitidos = events.of_kind(KIND_MPC_MV_STATUS_CHANGED)
    assert len(emitidos) == 1
    assert emitidos[0]["payload"] == {
        "var_id": "mv_pid",
        "from": MvAvailability.RCAS_OK.value,
        "to": MvAvailability.LOCAL_OVERRIDE.value,
    }
    assert emitidos[0]["severity"] == "warning"


async def test_retorno_a_rcas_ok_e_auditado_como_info() -> None:
    block, _, snapshot, _, _, events = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await block.step(entradas(20.0))
    snapshot.set(MODE_READ_PID, 0.0)
    await block.step(entradas(20.0))
    snapshot.set(MODE_READ_PID, 1.0)
    await block.step(entradas(20.0))
    emitidos = events.of_kind(KIND_MPC_MV_STATUS_CHANGED)
    assert len(emitidos) == 2
    assert emitidos[-1]["severity"] == "info"
    assert emitidos[-1]["payload"]["to"] == MvAvailability.RCAS_OK.value


async def test_arme_nao_e_bloqueado_por_mode_read_fora_do_target() -> None:
    """O gate de arme NÃO olha disponibilidade de MV, e isso é deliberado (ADR-028): armar
    é exatamente o ato de escrever `mode_cmd = target`, então exigir `rcas_ok` antes seria
    circular. Quem cobre o PID que não entra em RCAS é o watchdog de confirmação
    (`no_confirm` em 2×Ts_mpc). Aqui se tranca a ausência do gate, para ninguém "consertar"
    isso depois e travar todo LOCAL->REMOTO da planta."""
    block, _, snapshot, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    snapshot.set(MODE_READ_PID, 0.0)
    await block.step(entradas(20.0))
    assert block.auto_arm_blocked_reason() is None


async def test_arme_segue_exigindo_readback_de_toda_mv_observavel() -> None:
    """A régua de OBSERVABILIDADE de entrada permanece a de antes do ADR-028: MV que declara
    tag de posição e ainda não a publicou (ou publicou com qualidade ruim) barra o arme com
    `cold_input`, mesmo com a outra MV saudável. Degradar é para depois de armado."""
    block, _, snapshot, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    snapshot.set(READBACK_DIRETO, 3.0, quality=2)
    await block.step(entradas(20.0))
    assert block.auto_arm_blocked_reason() == "cold_input"


async def test_mv_status_expostos_para_o_supervisor() -> None:
    """O `MpcOrchestrator` precisa ver o mapa por fora do `step()` para decidir o shed
    (mesmo idioma das properties `host`/`local_remote`/`pid_bindings`)."""
    block, _, snapshot, *_ = _bloco_com_mode_read()
    _tudo_saudavel(snapshot)
    await block.step(entradas(20.0))
    assert block.mv_status == {
        "mv_pid": MvAvailability.RCAS_OK,
        "mv_direto": MvAvailability.RCAS_OK,
    }
