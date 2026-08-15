"""Disponibilidade de cada MV por ciclo de controle (ADR-028).

Camada de PRÉ-PROCESSAMENTO: roda antes de qualquer montagem de problema de otimização e é
pura — recebe as `MvVar` do config e o espelho do barramento (`ValueSnapshot`), devolve um
status por MV. Não conhece do-mpc, não conhece IPOPT e não decide o que fazer com o status:
`MpcBlock` decide (congela a MV no `SolveRequest`, suprime a escrita no `pid` dela) e o
`MpcOrchestrator` decide o shed do bloco. Este módulo só responde "essa MV está me
ouvindo agora?".

É o substituto local do par BKCAL_IN/BKCAL_OUT do Foundation Fieldbus, que o OPC-UA não
oferece: em vez de um handshake do bloco a jusante, o status é INFERIDO das tags que o
config já obriga a existir para a transferência bumpless (`readback_tag_id` — posição real —
e `pid.mode_read_tag_id` — modo real do PID).

Precedência (do sinal mais grave para o mais brando):

1. `OUT_OF_SERVICE` — tag configurada e NADA no espelho. Não se sabe onde o atuador está
   (ou em que modo o PID está). Vence tudo, inclusive um `mode_read` que diga `target`.
2. `BAD_QUALITY` — tag no espelho com `quality != 0` (uncertain inclusive, mesma régua
   conservadora do `opc_read`, spec F3 §3.1). A leitura existe e não vale.
3. `LOCAL_OVERRIDE` — leituras boas, mas o modo real do PID diverge de `mode_values.target`:
   o operador tirou a malha de RCAS no painel, ou um override a tomou. O sistema sabe onde o
   atuador está; simplesmente não manda nele.
4. `RCAS_OK` — nada a objetar; a MV entra na otimização normalmente.

O que NÃO é status de disponibilidade: **saturação**. Uma MV encostada no limite continua
controlável (pode sair do limite no sentido oposto) — congelá-la degradaria o controle sem
nenhum ganho de segurança. Os limites duros já são `mpc.bounds` do builder (spec F4 §3.4).

Ausência de observabilidade não é falha: MV sem `pid` e sem `readback_tag_id` ("MV direta
cega") e MV com `pid` sem `mode_read_tag_id` seguem `RCAS_OK` — a spec F4 §4.4/§4.5 já diz
"sem `mode_read`, sem shed", e o ADR-028 não inventa um dado que o config não pede.

NÃO confundir com o watchdog de comunicação (ADR-009, bit alternante por conexão): aquele
mede se o PLC inteiro está vivo e, em falha, para o flow. Este mede se UMA malha está sob
comando do MPC. São camadas independentes e permanecem assim.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum

from ottima_core.flowgraph import MvVar
from ottima_core.snapshot import ValueSnapshot


class MvAvailability(StrEnum):
    """Status de disponibilidade de uma MV no ciclo corrente (ADR-028).

    `StrEnum` porque o valor viaja no `MpcState` publicado em `mpc.state.*` (contrato do
    barramento, PRD §7.1) — serializa como a string minúscula, no mesmo idioma dos demais
    literais publicados (`local`/`remote`, `ok`/`building`).
    """

    RCAS_OK = "rcas_ok"
    LOCAL_OVERRIDE = "local_override"
    BAD_QUALITY = "bad_quality"
    OUT_OF_SERVICE = "out_of_service"


def readback_tag_id(mv: MvVar) -> int | None:
    """Tag da posição real da MV: com `pid`, a do `pid` (spec F4 §2.1-3); sem `pid`, a
    `readback_tag_id` da própria MV, quando configurada.

    Uma pergunta num lugar só — `MpcBlock._readback_tag_id` delega para cá, para o
    classificador e o bloco nunca discordarem sobre onde olhar.
    """
    return mv.pid.readback_tag_id if mv.pid is not None else mv.readback_tag_id


def _classify(mv: MvVar, snapshot: ValueSnapshot) -> MvAvailability:
    tag_id = readback_tag_id(mv)
    if tag_id is not None:
        tag = snapshot.get(tag_id)
        if tag is None:
            return MvAvailability.OUT_OF_SERVICE
        if tag.quality != 0:
            return MvAvailability.BAD_QUALITY

    if mv.pid is not None and mv.pid.mode_read_tag_id is not None:
        modo = snapshot.get(mv.pid.mode_read_tag_id)
        if modo is None:
            return MvAvailability.OUT_OF_SERVICE
        if modo.quality != 0:
            return MvAvailability.BAD_QUALITY
        if float(modo.value) != float(mv.pid.mode_values.target):
            return MvAvailability.LOCAL_OVERRIDE

    return MvAvailability.RCAS_OK


def classify_mvs(mvs: Iterable[MvVar], snapshot: ValueSnapshot) -> dict[str, MvAvailability]:
    """`var_id -> status` de cada MV, avaliado de forma INDEPENDENTE: o resultado de uma MV
    nunca entra na conta de outra (Estado-Alvo 5c do ADR-028)."""
    return {mv.id: _classify(mv, snapshot) for mv in mvs}


def frozen_mv_ids(status: Mapping[str, MvAvailability]) -> frozenset[str]:
    """MVs excluídas da otimização neste ciclo — tudo que não é `RCAS_OK`.

    "Excluída" não quer dizer removida do problema: a MV continua no modelo (é o que
    mantém a predição das CVs correta), só que congelada no valor real medido — o worker
    zera o `dumax` dela no horizonte (`mpc/worker.py::_apply_tvp`). É a formulação
    incremental fazendo o papel de distúrbio medido, sem um segundo caminho de código e sem
    tocar na montagem do problema.
    """
    return frozenset(var_id for var_id, s in status.items() if s is not MvAvailability.RCAS_OK)
