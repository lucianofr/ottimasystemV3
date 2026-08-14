"""Classificação de disponibilidade das MVs por ciclo (ADR-028).

Camada PURA, anterior à montagem do problema de otimização: recebe as `MvVar` do config e o
espelho do barramento, devolve um status por MV. Não conhece do-mpc, não conhece solver e
não decide o que fazer com o status — quem decide é `MpcBlock` (congelar, suprimir escrita)
e o `MpcOrchestrator` (shed). Por isso os testes daqui são tabelas de entrada/saída, sem
bloco, sem host e sem Redis.

Regra de precedência exercitada (ADR-028 §Decisão): ausência de leitura vence qualidade
ruim, que vence divergência de modo — do sinal mais grave (não sei nada) para o mais brando
(sei, e o PID não está me ouvindo).
"""

from __future__ import annotations

from datetime import UTC, datetime

from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.mpc.availability import (
    MvAvailability,
    classify_mvs,
    frozen_mv_ids,
    readback_tag_id,
)
from ottima_flow_runtime.snapshot import TagValue

READBACK_PID = 503
MODE_READ_PID = 504
READBACK_DIRETO = 601


def _config(*, mode_read: int | None = MODE_READ_PID, readback_direto: int | None = None):
    """2 MVs: uma com `pid` completo (readback + mode_read), outra direta."""
    return MpcConfig.model_validate(
        {
            "name": "bloco_teste",
            "multiplier": 1,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_pid",
                        "name": "MV com pid",
                        "eu": "m3/h",
                        "limits": {"min": 0.0, "max": 100.0},
                        "max_rate": 5.0,
                        "initial_value": 10.0,
                        "pid": {
                            "write_tag_id": 501,
                            "target_mode": "rcas",
                            "mode_cmd_tag_id": 502,
                            "mode_read_tag_id": mode_read,
                            "readback_tag_id": READBACK_PID,
                            "mode_values": {"auto": 0, "target": 1},
                        },
                    },
                    {
                        "id": "mv_direto",
                        "name": "MV direta",
                        "eu": "%",
                        "limits": {"min": -10.0, "max": 10.0},
                        "max_rate": 2.0,
                        "initial_value": 1.5,
                        "readback_tag_id": readback_direto,
                        "pid": None,
                    },
                ],
                "cvs": [
                    {
                        "id": "cv_a",
                        "name": "CV a",
                        "eu": "C",
                        "kind": "selfreg",
                        "tss": 30.0,
                        "weight": 1.0,
                        "sp_limits": {"min": 0.0, "max": 200.0},
                    }
                ],
                "constraints": [],
                "dvs": [],
            },
            "models": {
                "cv_a": {
                    "mv_pid": {
                        "enabled": True,
                        "params": {"K": 1.0, "tau1": 10.0, "tau2": 0.0, "theta": 0.0},
                    },
                    "mv_direto": {
                        "enabled": True,
                        "params": {"K": 1.0, "tau1": 10.0, "tau2": 0.0, "theta": 0.0},
                    },
                }
            },
        }
    )


class FakeSnapshot:
    """Duplo de `ValueSnapshot` — só o `.get()` síncrono (mesmo duplo de test_mpc_block)."""

    def __init__(self) -> None:
        self._values: dict[int, TagValue] = {}

    def set(self, tag_id: int, value: float, *, quality: int = 0) -> None:
        self._values[tag_id] = TagValue(value=value, quality=quality, ts=datetime.now(UTC))

    def get(self, tag_id: int) -> TagValue | None:
        return self._values.get(tag_id)


def _mvs(**kwargs):
    return _config(**kwargs).variables.mvs


def _mv_pid(**kwargs):
    return _mvs(**kwargs)[0]


def _mv_direto(**kwargs):
    return _mvs(**kwargs)[1]


# --------------------------------------------------------------------------------------
# Tag de posição real: uma pergunta, um lugar
# --------------------------------------------------------------------------------------


def test_readback_tag_id_prefere_a_do_pid() -> None:
    assert readback_tag_id(_mv_pid()) == READBACK_PID


def test_readback_tag_id_da_mv_direta_e_a_propria() -> None:
    assert readback_tag_id(_mv_direto(readback_direto=READBACK_DIRETO)) == READBACK_DIRETO


def test_readback_tag_id_ausente_na_mv_direta_cega() -> None:
    assert readback_tag_id(_mv_direto()) is None


# --------------------------------------------------------------------------------------
# Classificação (ADR-028)
# --------------------------------------------------------------------------------------


def test_tudo_no_lugar_classifica_rcas_ok() -> None:
    snapshot = FakeSnapshot()
    snapshot.set(READBACK_PID, 42.0)
    snapshot.set(MODE_READ_PID, 1.0)
    assert classify_mvs(_mvs(), snapshot)["mv_pid"] is MvAvailability.RCAS_OK


def test_readback_nunca_publicado_classifica_out_of_service() -> None:
    """Tag configurada e nada no espelho: o sistema não sabe onde o atuador está. Pior sinal
    possível — vence qualquer outro, inclusive um `mode_read` que diga `target`."""
    snapshot = FakeSnapshot()
    snapshot.set(MODE_READ_PID, 1.0)
    assert classify_mvs(_mvs(), snapshot)["mv_pid"] is MvAvailability.OUT_OF_SERVICE


def test_readback_com_qualidade_ruim_classifica_bad_quality() -> None:
    """`quality != 0` invalida (uncertain inclusive) — mesma régua conservadora do
    `opc_read` (spec F3 §3.1) e do `MpcBlock._readback_value`."""
    snapshot = FakeSnapshot()
    snapshot.set(READBACK_PID, 42.0, quality=2)
    snapshot.set(MODE_READ_PID, 1.0)
    assert classify_mvs(_mvs(), snapshot)["mv_pid"] is MvAvailability.BAD_QUALITY


def test_readback_uncertain_tambem_e_bad_quality() -> None:
    snapshot = FakeSnapshot()
    snapshot.set(READBACK_PID, 42.0, quality=1)
    snapshot.set(MODE_READ_PID, 1.0)
    assert classify_mvs(_mvs(), snapshot)["mv_pid"] is MvAvailability.BAD_QUALITY


def test_mode_read_divergente_com_leitura_boa_classifica_local_override() -> None:
    """O operador tirou o PID de RCAS no painel: a posição é confiável, o comando não."""
    snapshot = FakeSnapshot()
    snapshot.set(READBACK_PID, 42.0)
    snapshot.set(MODE_READ_PID, 0.0)
    assert classify_mvs(_mvs(), snapshot)["mv_pid"] is MvAvailability.LOCAL_OVERRIDE


def test_mode_read_nunca_publicado_classifica_out_of_service() -> None:
    snapshot = FakeSnapshot()
    snapshot.set(READBACK_PID, 42.0)
    assert classify_mvs(_mvs(), snapshot)["mv_pid"] is MvAvailability.OUT_OF_SERVICE


def test_mode_read_com_qualidade_ruim_classifica_bad_quality() -> None:
    """Modo lido com qualidade ruim não confirma RCAS — não dá para tratar como se
    confirmasse. Mesma régua do readback."""
    snapshot = FakeSnapshot()
    snapshot.set(READBACK_PID, 42.0)
    snapshot.set(MODE_READ_PID, 1.0, quality=2)
    assert classify_mvs(_mvs(), snapshot)["mv_pid"] is MvAvailability.BAD_QUALITY


def test_sem_mode_read_configurado_nao_ha_o_que_divergir() -> None:
    """Sem `mode_read` não há confirmação nem shed (spec F4 §4.4/§4.5) — a MV segue elegível
    enquanto a posição real for confiável. ADR-028 não inventa observabilidade que o config
    não tem."""
    snapshot = FakeSnapshot()
    snapshot.set(READBACK_PID, 42.0)
    assert classify_mvs(_mvs(mode_read=None), snapshot)["mv_pid"] is MvAvailability.RCAS_OK


def test_mv_direta_cega_e_sempre_rcas_ok() -> None:
    """MV sem `pid` e sem `readback_tag_id`: nada a observar, comportamento pré-ADR-028
    preservado bit a bit (nunca congela por falta de um dado que o config não pede)."""
    assert classify_mvs(_mvs(), FakeSnapshot())["mv_direto"] is MvAvailability.RCAS_OK


def test_mv_direta_com_readback_ruim_classifica_bad_quality() -> None:
    """MV direta COM `readback_tag_id`: a posição real é observável, então vale a mesma
    régua da MV com `pid` — o que falta é só o eixo de modo."""
    snapshot = FakeSnapshot()
    snapshot.set(READBACK_DIRETO, 3.0, quality=2)
    mvs = _mvs(readback_direto=READBACK_DIRETO)
    assert classify_mvs(mvs, snapshot)["mv_direto"] is MvAvailability.BAD_QUALITY


# --------------------------------------------------------------------------------------
# Independência entre MVs (Estado-Alvo 5c) e conjunto congelado
# --------------------------------------------------------------------------------------


def test_uma_mv_degradada_nao_contamina_a_outra() -> None:
    snapshot = FakeSnapshot()
    snapshot.set(READBACK_PID, 42.0, quality=2)
    snapshot.set(MODE_READ_PID, 0.0)
    snapshot.set(READBACK_DIRETO, 3.0)
    status = classify_mvs(_mvs(readback_direto=READBACK_DIRETO), snapshot)
    assert status["mv_pid"] is MvAvailability.BAD_QUALITY
    assert status["mv_direto"] is MvAvailability.RCAS_OK


def test_frozen_mv_ids_pega_tudo_que_nao_e_rcas_ok() -> None:
    status = {
        "a": MvAvailability.RCAS_OK,
        "b": MvAvailability.LOCAL_OVERRIDE,
        "c": MvAvailability.BAD_QUALITY,
        "d": MvAvailability.OUT_OF_SERVICE,
    }
    assert frozen_mv_ids(status) == frozenset({"b", "c", "d"})


def test_frozen_mv_ids_vazio_quando_tudo_saudavel() -> None:
    assert frozen_mv_ids({"a": MvAvailability.RCAS_OK}) == frozenset()
