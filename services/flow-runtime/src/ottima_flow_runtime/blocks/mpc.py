"""Bloco MPC: cadência, modos e write-back do runtime (spec F4 §4.2/§4.3/§4.6/§4.9/§5;
plano F4b, tarefa 2.1).

Bloco "fino" (brief da tarefa): TODA a matemática do MPC mora em `mpc/worker.py`
(montagem + solve) e `mpc/host.py` (processo, orçamento, kill/respawn) — nada disso é
redefinido aqui. Este módulo só decide QUANDO disparar um `SolveRequest` (cadência do
`multiplier`, spec §4.2), COMO aplicar o `SolveResult` (na fronteira de varredura seguinte
à conclusão, nunca no meio — determinismo RF-401) e QUAL valor de MV sai por modo
(LOCAL/REMOTO×MAN/AUTO, spec §4.3).

Fronteira de cadência: `n mod multiplier == 0`, `n` contado desde o deploy (`reset()` zera
o contador — hot-swap/stop reinicia a fase, igual aos demais blocos F3). `n=0` já É
fronteira, então a primeira varredura após o deploy dispara.

Cold start (`v=None` em qualquer CV/Restrição/DV) segue o padrão universal do F3 §3.0
(`has_cold_input`/`null_outputs`, o mesmo gate de TFS/Script): saídas nulas, nada mais
avaliado nessa varredura. Invalidez (`ok=False`, valor conhecido) é mais branda — decisão
A-6 da F3: o bloco segue rodando, mas pula o solve na fronteira, mantém as saídas com a
flag ruim e suprime as escritas do `pid` (spec §4.6); dedupe por período, mesmo padrão de
`write_suppressed`/`flow_overrun`. DV fica FORA desse gate (ADR-038): amostra ruim congela
o último valor bom internamente e o solve segue — feedforward parado não impacta o
algoritmo; ação default fixa, sem fail action de DV.

CONTRATO VINCULANTE herdado do host (docstring de `mpc/host.py`, achado da revisão 1.1):
um `SolveResult` com `status="no_convergence"` chega com `u_plan`/predição/`cost`
POPULADOS — nunca aplicados à planta. O gate é sempre `status == "ok"`, tanto aqui quanto
em qualquer lugar que decida repetir essa checagem.

Escopo desta tarefa (2.1) — o que NÃO mora aqui: escrita de `mode_cmd` no PID nas
transições LOCAL<->REMOTO, confirmação por `mode_read` (2×Ts_mpc), shed por divergência de
`mode_read` (§4.5) e hot-swap (§4.7) são orquestração do supervisor (plano F4b, tarefa 2.2,
`mpc_arming.py` + `supervisor.py`) — o bloco só materializa o campo de modo e audita, via
`command()`, respeitando as regras §4.8 (idempotência, `man_auto` em LOCAL ignorado,
clamps, e materialização condicionada ao modo vigente). O supervisor precisa ver por fora
do `step()` (host pronto, entrada quente/válida, `pid` de cada MV, `Ts_mpc`) para orquestrar
sem duplicar essa configuração — daí as properties `host`/`local_remote`/`ts_mpc`/
`pid_bindings` e o predicado puro `auto_arm_blocked_reason()`: leitura só, sem write, sem
mudar o comportamento desta tarefa (achado da tarefa 2.2, documentado no relatório dela).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from ottima_core.bus import (
    KIND_MPC_INPUT_INVALID,
    KIND_MPC_MODE_CHANGED,
    KIND_MPC_MV_STATUS_CHANGED,
    KIND_MPC_MV_WRITTEN,
    KIND_MPC_OVERRUN,
    KIND_MPC_SOLVER_ERROR,
    KIND_MPC_SP_WRITTEN,
    KIND_SSTO_INFEASIBLE,
    MpcModes,
    MpcPrediction,
    MpcState,
    MpcStatus,
    MpcVarState,
    OpcWrite,
    SstoRun,
)
from ottima_core.flowgraph import (
    MPC_FIXED_OUTPUT_PORTS,
    MPC_PORT_AUTO,
    MPC_PORT_LOCAL,
    CvVar,
    MpcConfig,
    MvVar,
    PidBinding,
    derive_horizons,
)
from ottima_core.snapshot import ValueSnapshot

from ..mpc.availability import (
    MvAvailability,
    classify_mvs,
    frozen_mv_ids,
    readback_tag_id,
)
from ..mpc.host import MpcHost
from ..mpc.worker import SolveRequest, SolveResult
from .base import Block, PortSample, has_cold_input, null_outputs

logger = logging.getLogger(__name__)

_LocalRemote = Literal["local", "remote"]
_ManAuto = Literal["man", "auto"]
_SolverStatus = Literal["ok", "overrun", "error"]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _empty_prediction(ts: datetime) -> MpcPrediction:
    """Predição vazia fora de AUTO (spec F5 §2.1-2): `prediction.ts == ts` do quadro, `t: []`."""
    return MpcPrediction(ts=ts, t=[], cv=[], mv=[])


@dataclass(frozen=True, slots=True)
class EstadoMpcTransplante:
    """Estado transplantável de um `MpcBlock` para hot-swap sem queda de modo (TD-006) e
    para a retomada automática pós `comm_restored` (TD-005, ADR-025).

    Tirado do bloco velho ANTES de ele sair de cena (`snapshot_estado`) e aplicado no
    bloco novo logo depois de instanciado (`aplicar_estado`) — os dois métodos moram no
    próprio `MpcBlock` porque só ele conhece o nome real dos atributos internos que
    compõem o estado "vivo" de um MPC armado: os dois eixos de modo, o último valor
    manual/aplicado de cada MV e o SP de cada CV. Não inclui plano/predição/custo: são
    artefatos do ÚLTIMO solve, presos ao worker antigo — o novo nasce sem eles e
    reconstrói tudo no primeiro solve genuíno (bumpless, `_run_frontier`).
    """

    local_remote: _LocalRemote
    man_auto: _ManAuto
    mv_manual: dict[str, float]
    mv_last: dict[str, float]
    sp: dict[str, float]


class MpcBlock(Block):
    """Entradas: uma por CV/Restrição/DV (ordem do config, spec §2.1-5). Saídas: uma por MV.

    `host` já é dono do processo do worker (spec F4 §3.6/§4.2) — este bloco só chama
    `dispatch()`/`poll()`/`stats()`/`ready`, nunca sobe/mata processo (quem faz isso é o
    supervisor, plano F4b tarefa 2.2, dono do ciclo de vida do host por flow). `snapshot` é
    o espelho do barramento (F3) usado só para o readback do PID em LOCAL (spec §4.3);
    `publish`/`write_opc`/`emit_event` são os pontos de saída para o barramento, injetados
    para o bloco nunca falar com Redis diretamente (testável em processo, sem I/O).
    """

    def __init__(
        self,
        block_id: str,
        *,
        config: MpcConfig,
        ts_flow: float,
        snapshot: ValueSnapshot,
        host: MpcHost,
        flow_id: int,
        publish: Callable[[MpcState], Awaitable[None]],
        write_opc: Callable[[OpcWrite], Awaitable[None]],
        emit_event: Callable[..., Awaitable[None]],
        now: Callable[[], datetime] | None = None,
        escreve_sem_watchdog: bool = False,
        sp_seed: Mapping[str, float] | None = None,
        persist_sp: Callable[[str, float], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(block_id)
        self._snapshot = snapshot
        self._host = host
        self._publish = publish
        self._write_opc = write_opc
        self._emit_event = emit_event
        # TD-004: alguma MV deste bloco escreve numa conexão sem watchdog (`definition.py`
        # decide, config estática) — `auto_arm_blocked_reason()` barra o arme antes de o
        # supervisor materializar um comando que o `writes.py` do opc-worker recusaria de
        # qualquer forma (somente leitura de fato).
        self._escreve_sem_watchdog = escreve_sem_watchdog
        # Persistência do SP do operador (emenda da decisão A-4 da spec F4): `sp_seed` é o
        # que `mpc_setpoints` guarda deste bloco — semente de `reset()` (deploy/redeploy/
        # stop/restart), clampada na própria `reset()` aos `sp_limits` vigentes. `persist_sp`
        # é o upsert fire-and-forget (fechado em `definition.py`); os MODOS seguem voláteis.
        self._sp_seed: Mapping[str, float] = dict(sp_seed) if sp_seed is not None else {}
        self._persist_sp = persist_sp
        # Clock injetável (spec F5 §2.1, achado da tarefa 1.2): fallback para quando `step()`
        # não recebe `ts` do scheduler (publicações imediatas, que não têm fronteira; e
        # testes de unidade que chamam `step()` direto). Em produção o scheduler SEMPRE passa
        # `ts` na fronteira (fix round 1, achado 1) — este clock nunca é a fonte da verdade
        # de `flow.status.ts` em produção.
        self._now: Callable[[], datetime] = now if now is not None else lambda: datetime.now(UTC)
        # `flow_id` entra só para compor `_source` no padrão F3 (`flow:<fid>/block:<bid>`,
        # igual a `OpcWriteBlock`) — achado do carry-over da tarefa 2.1: o bloco nasceu
        # isolado (host/snapshot falsos, sem Redis) e não tinha o `flow_id` à mão; quem
        # monta o bloco de verdade (`definition.py`, tarefa 2.2) sempre tem — a costura de
        # string fica na fonte, não espalhada por quem publica os eventos/writes do bloco.
        self._source = f"flow:{flow_id}/block:{block_id}"

        tss = [v.tss for v in (*config.variables.cvs, *config.variables.constraints)]
        self._multiplier = config.multiplier
        self._ts_mpc = derive_horizons(config.multiplier, ts_flow, tss).ts_mpc

        self._mvs: dict[str, MvVar] = {v.id: v for v in config.variables.mvs}
        self._cvs: dict[str, CvVar] = {v.id: v for v in config.variables.cvs}
        # RF-612/614: PV-tracking fora de AUTO por CV, e SP remoto por tag OPC-UA.
        self._track_sp = {cv.id: cv.track_sp for cv in config.variables.cvs}
        self._remote_sp = {
            cv.id: cv.remote_sp_tag_id
            for cv in config.variables.cvs
            if cv.remote_sp_tag_id is not None
        }
        # RF-613: ação de falha por variável (rows + MVs) e timeout de simulação (só rows).
        self._fail_action = {
            v.id: v.fail_action
            for v in (*config.variables.cvs, *config.variables.constraints, *config.variables.mvs)
        }
        self._fail_timeout = {
            v.id: v.fail_timeout_s for v in (*config.variables.cvs, *config.variables.constraints)
        }
        self.tem_fail_action = any(acao != "no_action" for acao in self._fail_action.values())
        self._mv_ids = tuple(self._mvs)
        self._cv_ids = tuple(self._cvs)
        self._co_ids = tuple(v.id for v in config.variables.constraints)
        self._dv_ids = tuple(v.id for v in config.variables.dvs)
        self._row_ids = self._cv_ids + self._co_ids
        self._entrada_ids = self._row_ids + self._dv_ids
        # TD-006 (hot-swap bumpless): `True` só quando ESTE bloco nasceu de um transplante
        # de estado (`definition.py::build_definition`) — `MpcOrchestrator.
        # reconcile_mpc_hosts` usa o flag para pular a devolução de `mode_cmd=auto` ao PLC
        # (os modos não mudaram, não há o que devolver) e para escolher o motivo do evento
        # de auditoria (`hot_swap_bumpless` em vez de `hot_swap`). Atributo público
        # (não `_transplantado`): quem marca é `definition.py`, de fora da instância.
        self.transplantado = False

        self.reset()

    @property
    def input_ports(self) -> tuple[str, ...]:
        return self._entrada_ids

    @property
    def output_ports(self) -> tuple[str, ...]:
        """Uma por MV + as 2 portas fixas de modo (decisão A-10 revista, spec F4 §2.1-5) —
        estas últimas SEMPRE presentes, mesmo com o bloco recém-criado sem nenhuma MV."""
        return self._mv_ids + MPC_FIXED_OUTPUT_PORTS

    @property
    def host(self) -> MpcHost:
        """O `MpcHost` deste bloco — o supervisor é dono do ciclo de vida dele (start no
        deploy, stop no stop/hot-swap; plano F4b tarefa 2.2)."""
        return self._host

    @property
    def local_remote(self) -> _LocalRemote:
        """Leitura pura do eixo LOCAL/REMOTO — o supervisor usa para decidir se uma
        transição `local_remote` de fato mudou algo (comando idempotente não dispara
        escrita de `mode_cmd` nem arma confirmação, tarefa 2.2)."""
        return self._local_remote

    @property
    def ts_mpc(self) -> float:
        """`Ts_mpc` derivado (spec §2.2-5) — cadência que o supervisor usa para o relógio
        de confirmação (2×Ts_mpc, §4.4) e shed (§4.5): mesma conta, não duplicada."""
        return self._ts_mpc

    @property
    def mv_status(self) -> dict[str, MvAvailability]:
        """Disponibilidade por MV apurada na ÚLTIMA varredura (ADR-028) — leitura só.

        O `MpcOrchestrator` (supervisor_mpc.py) precisa ver o mapa por fora do `step()` para
        decidir o shed do bloco (nenhuma MV sobrou), no mesmo idioma das demais properties
        de inspeção (`host`/`local_remote`/`ts_mpc`/`pid_bindings`): o supervisor não
        reclassifica nada por conta própria, para nunca discordar do que o bloco usou no
        `SolveRequest` daquela varredura.
        """
        return dict(self._mv_status)

    @property
    def pid_bindings(self) -> tuple[tuple[str, PidBinding], ...]:
        """`(var_id, pid)` de cada MV com `pid` — o supervisor usa para escrever `mode_cmd`
        e ler `mode_read` nas transições §4.4/§4.5 sem reparsear o `MpcConfig` a partir do
        JSON salvo (o bloco já fez esse parse)."""
        return tuple((mv_id, mv.pid) for mv_id, mv in self._mvs.items() if mv.pid is not None)

    def auto_arm_blocked_reason(self) -> str | None:
        """Predicado puro e ÚNICO do gate de armar em AMBOS os eixos (fix-final, achado do
        arquiteto F-4): host pronto + entradas quentes (já medidas ao menos uma vez, nunca
        frias) + válidas (última varredura `ok=True`) + toda MV com tag de readback já com
        valor publicado no `snapshot`. Sem o último item, `_effective_value` cai no
        `initial_value` — `u_applied` do solve e o init bumpless (§3.6) partiam de uma
        ficção em vez da posição física real do atuador. `local_remote -> remote` (contrato
        com `MpcOrchestrator`, supervisor_mpc.py) e `MAN -> AUTO` (spec §4.4, tabela de
        transições) chamam o MESMO predicado — nenhum eixo arma sobre entrada fria.

        Reaproveita o motivo `"cold_input"` para o readback ausente (em vez de cunhar um
        motivo novo): do ponto de vista do operador é a mesma história — "ainda não vi o
        valor real dessa variável" —, e `"cold_input"` já está no enum de `mpc_arm_failed`
        (spec §5.3); justificativa completa no relatório da tarefa.

        Só LÊ estado — quem decide o que fazer com o motivo (emitir `mpc_arm_failed` e não
        materializar o comando) é o supervisor, que intercepta o comando ANTES de rotear a
        `command()` (tarefa 2.2).

        TD-004 (achado do registro de débitos): "escreve numa conexão sem watchdog" é o
        NOVO PRIMEIRO check, antes até de `worker_not_ready` — a causa é 100% estática
        (config da conexão, resolvida no deploy por `definition.py`) e nunca se resolve
        sozinha como um host que ainda vai ficar pronto ou uma entrada que ainda vai
        esquentar; erro de configuração ganha de condição transiente."""
        if self._escreve_sem_watchdog:
            return "write_target_sem_watchdog"
        if not self._host.ready:
            return "worker_not_ready"
        warm = all(var_id in self._last_measured for var_id in self._entrada_ids)
        if not warm:
            return "cold_input"
        # ADR-028 NÃO acrescenta aqui um gate de "nenhuma MV em RCAS": seria circular.
        # LOCAL->REMOTO é justamente o ato de escrever `mode_cmd = target` nos PIDs — exigir
        # `rcas_ok` antes dele é exigir que a malha já esteja em RCAS antes do comando que a
        # põe em RCAS. Quem cobre o caso "o operador travou o PID fora de RCAS" é o watchdog
        # de confirmação de sempre (`mpc_arming.watch_arm`: sem confirmação em 2×Ts_mpc,
        # `mpc_arm_failed {reason: no_confirm}` e volta a LOCAL). Em MAN->AUTO o bloco já
        # está REMOTO e confirmado, e a perda total posterior é o shed. Os dois eixos ficam
        # com a régua de ENTRADA intacta; o ADR-028 relaxa o conjunto de MVs ativas só
        # DURANTE a operação.
        # Mesma régua de `_readback_value` (ausente OU qualidade ruim): armar sobre uma
        # amostra que o próprio bloco não aceita como posição seria contraditório.
        sem_readback = any(
            self._readback_value(mv) is None
            for mv in self._mvs.values()
            if self._readback_tag_id(mv) is not None
        )
        if sem_readback:
            return "cold_input"
        if not self._input_ok:
            return "invalid_input"
        return None

    @property
    def _in_auto(self) -> bool:
        """`True` só em REMOTO+AUTO — fonte única para o gate de tracking do SP (§4.4,
        achado da revisão: entrar em AUTO e sair para LOCAL sem passar por MAN deixava
        `_man_auto` "auto" órfão, e um gate que checasse só `_man_auto` travava o
        PV-tracking em LOCAL) e para `_build_state`."""
        return self._local_remote == "remote" and self._man_auto == "auto"

    def reset(self) -> None:
        self._n = 0
        self._local_remote: _LocalRemote = "local"
        self._man_auto: _ManAuto = "man"
        self._mv_manual: dict[str, float] = {mv.id: mv.initial_value for mv in self._mvs.values()}
        self._mv_last: dict[str, float] = {mv.id: mv.initial_value for mv in self._mvs.values()}
        self._plan: dict[str, float] | None = None
        # SP nasce da semente persistida quando existe (clampado aos `sp_limits` vigentes —
        # a faixa pode ter sido estreitada na config entre a gravação e este reset); CV sem
        # semente (ou com CV removido da config) nasce 0.0 como antes. Sem semente, o
        # comportamento é bit a bit o anterior.
        self._sp: dict[str, float] = {
            cv_id: _clamp(float(self._sp_seed[cv_id]), cv.sp_limits.min, cv.sp_limits.max)
            if cv_id in self._sp_seed
            else 0.0
            for cv_id, cv in self._cvs.items()
        }
        self._last_measured: dict[str, float] = {}
        # ADR-028 — disponibilidade por MV, reapurada a cada varredura. Nasce VAZIO de
        # propósito: a primeira classificação é a linha de base e não emite evento de
        # transição. Semear aqui classificando o espelho faria todo deploy publicar uma
        # enxurrada de "MV voltou a rcas_ok" conforme as tags de readback chegassem — o
        # estado publicado em `mpc.state.*` já mostra a situação corrente a cada fronteira;
        # o evento existe para MUDANÇA, e antes da primeira varredura não houve nenhuma.
        self._mv_status: dict[str, MvAvailability] = {}
        # Última posição REAL confiável de cada MV (ADR-028): âncora de congelamento quando
        # a leitura para de prestar. Sem isto o congelamento cairia em `_mv_last` — que em
        # AUTO é o último valor que o PRÓPRIO MPC calculou, exatamente a realimentação que
        # o ADR proíbe como base de bias/delta.
        self._last_good_readback: dict[str, float] = {}
        self._last_prediction = _empty_prediction(self._now())
        # Guarda a fronteira do último `host.dispatch()` aceito (spec §3.5): a âncora que
        # `_apply_result` aplica ao resultado correspondente, consumido no `poll()` da
        # fronteira seguinte — nunca o ts do quadro que está consumindo o resultado.
        self._dispatch_ts: datetime | None = None
        # Honesto por padrão (achado da tarefa 4.2, E2E F4b): só vira "ok" via
        # `_apply_result` sob evidência real (`SolveResult.status == "ok"` aplicado) —
        # nunca antes do primeiro solve genuíno concluído.
        self._solver_status: _SolverStatus | Literal["idle"] = "idle"
        self._cost = 0.0
        self._overruns = 0
        self._reinit_pending = False
        self._overrun_reported = False
        self._input_invalid_reported = False
        self._input_ok = True
        # RF-613 — debounce de 2 execuções por variável (mesma régua do shed RF-628):
        # `_fail_streak` conta fronteiras ruins consecutivas; `_fail_pending` guarda o
        # (ação final, motivo) pronto para o orquestrador consumir; `_fail_fired` é o
        # edge-trigger (não re-dispara enquanto a condição não sanear); `_simulacao_desde`
        # marca o início da janela de simulação (`fail_timeout_s`) por linha.
        self._fail_streak: dict[str, int] = {}
        self._fail_pending: dict[str, tuple[str, str]] = {}
        self._fail_fired: set[str] = set()
        self._simulacao_desde: dict[str, float] = {}
        # Registro do SSTO à espera de publicação (ADR-027 §11): preenchido ao aplicar o
        # resultado, consumido pela publicação da MESMA fronteira. Uma execução, um
        # registro — republicá-lo duplicaria linha em `ssto_runs`.
        self._ssto_pending: SstoRun | None = None
        self._ssto_infeasible_reported = False
        # Baseline p/ distinguir crash real de exceção isolada do worker (fix-final,
        # `_apply_result`): conta reposições JÁ ocorridas até aqui — inclusive de um host
        # reaproveitado num reset() de hot-swap — para nunca acusar "crash" por um respawn
        # anterior a este bloco/host observar pela 1a vez.
        self._last_respawns: int = self._host.stats()["respawns"]

    def snapshot_estado(self) -> EstadoMpcTransplante:
        """Tira uma foto do estado transplantável (TD-006/TD-005) — cópias defensivas dos
        dicts internos, nunca as referências vivas (o bloco velho segue mutando os seus até
        sair de cena de vez)."""
        return EstadoMpcTransplante(
            local_remote=self._local_remote,
            man_auto=self._man_auto,
            mv_manual=dict(self._mv_manual),
            mv_last=dict(self._mv_last),
            sp=dict(self._sp),
        )

    def aplicar_estado(self, estado: EstadoMpcTransplante) -> None:
        """Aplica um snapshot (TD-006 hot-swap; TD-005 retomada pós `comm_restored`): modos
        e últimos valores voltam a valer no bloco novo, SEM o degrau de um `reset()` normal
        (que os zeraria para LOCAL/MAN/`initial_value`).

        `_plan` é forçado a `None` — mesma semântica MAN->AUTO do TD-003 (`_command_mode`,
        §4.4): a saída segura `mv_last` até o primeiro `SolveResult` NOVO deste worker
        chegar, nunca salta para um plano calculado por outro processo/config. `_n = 0`
        realinha a fase de cadência do multiplicador, igual a um hot-swap comum."""
        self._local_remote = estado.local_remote
        self._man_auto = estado.man_auto
        self._mv_manual = dict(estado.mv_manual)
        self._mv_last = dict(estado.mv_last)
        self._sp = dict(estado.sp)
        self._plan = None
        self._n = 0

    # ------------------------------------------------------------------------------
    # Varredura
    # ------------------------------------------------------------------------------

    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        is_frontier = self._n % self._multiplier == 0
        self._n += 1
        # Carimbo real da fronteira (spec F5 §2.1-1, fix round 1 achado 1): `ts` vem do
        # scheduler (`FlowTask._scan`, o MESMO relógio de `flow.status.ts`) — nunca o clock
        # próprio do bloco quando o scheduler o fornece. `self._now()` só entra como
        # fallback (unidade sem scheduler, publicações imediatas fora deste método). Um só
        # valor por varredura, reaproveitado em toda publicação e no guardado de
        # `_dispatch_ts` desta mesma fronteira — nunca recomputado por chamada.
        ts = (ts if ts is not None else self._now()) if is_frontier else None

        # ADR-028 — reclassificação das MVs ANTES de qualquer decisão desta varredura: o
        # `SolveRequest` da fronteira, a saída de cada porta e a supressão de escrita no
        # `pid` leem todos o MESMO mapa, apurado uma vez só. Não depende das portas de
        # entrada (só do espelho do barramento), então roda antes do gate de cold start —
        # inclusive o quadro de cold start publica um status honesto.
        await self._reclassify_mvs()

        # SP remoto (RF-614): a cada varredura, antes de qualquer gate — qualidade boa
        # atualiza `_sp` (clamp em sp_limits); ruim/ausente mantém o último (dado cíclico,
        # sem evento). A cada varredura, não só na fronteira: o operador vê o SP seguir a
        # tag no `mpc.state` mesmo entre execuções.
        for cv_id, tag_id in self._remote_sp.items():
            if tag_id is None:
                continue
            tag = self._snapshot.get(tag_id)
            if tag is None or tag.quality != 0:
                continue
            cv = self._cvs[cv_id]
            self._sp[cv_id] = _clamp(float(tag.value), cv.sp_limits.min, cv.sp_limits.max)

        samples = {pid: inputs.get(pid, PortSample(None, False)) for pid in self._entrada_ids}
        if has_cold_input(samples):
            if is_frontier:
                # Cold start (§3.0 F3): saídas nulas — mas §5.2 pede publicação a cada
                # execução MESMO fora de AUTO, então a fronteira ainda precisa emitir um
                # frame honesto (achado F-5): sem isso, um flow recém-implantado fica
                # mudo em `mpc.state.*` até a 1a varredura totalmente quente.
                self._input_ok = False
                await self._publish(self._build_state(ts))
            return null_outputs(self.output_ports)

        # RF-613 — validez por linha: CV/Restrição com amostra ruim e `fail_action`
        # `simulate_*` DENTRO de `fail_timeout_s` recebe o valor previsto da última
        # predição aplicada (ou, sem predição, a última medição boa) e conta como válida
        # para o solve. DVs ficam FORA do gate (ADR-038): amostra ruim de DV congela
        # internamente — o bloco segue resolvendo com o último valor bom (feedforward
        # parado não impacta o algoritmo); ação default fixa, sem fail action de DV.
        # Expirada a janela, a linha volta a contar como ruim e a ação final corre pelo
        # debounce da fronteira (`_avaliar_fail_actions`).
        agora_mono = time.monotonic()
        simuladas: set[str] = set()
        for row_id in self._row_ids:
            if samples[row_id].ok:
                self._simulacao_desde.pop(row_id, None)
                continue
            if self._fail_action.get(row_id) not in ("simulate_manual", "simulate_shed_local"):
                continue
            inicio = self._simulacao_desde.setdefault(row_id, agora_mono)
            if agora_mono - inicio > self._fail_timeout.get(row_id, 60.0):
                continue
            previsto = self._valor_previsto(row_id)
            if previsto is None:
                continue
            self._last_measured[row_id] = previsto
            simuladas.add(row_id)

        valid = all(samples[row_id].ok or row_id in simuladas for row_id in self._row_ids)
        self._input_ok = valid
        if valid:
            self._input_invalid_reported = False
            for var_id, sample in samples.items():
                if not sample.ok:
                    # Linha simulada: `_last_measured` já recebeu o previsto. DV ruim
                    # (ADR-038): congela no último valor bom — não atualiza, não invalida.
                    continue
                self._last_measured[var_id] = float(sample.v)  # type: ignore[arg-type]
            if not self._in_auto:
                for cv_id in self._cv_ids:
                    # SP remoto (RF-614) segue a tag, não o PV; `track_sp=False` (RF-612)
                    # segura o SP do operador fora de AUTO.
                    if cv_id in self._remote_sp or not self._track_sp[cv_id]:
                        continue
                    self._sp[cv_id] = self._last_measured[cv_id]
        else:
            await self._report_input_invalid()

        if is_frontier:
            self._avaliar_fail_actions(samples, simuladas)

        if is_frontier and valid:
            await self._run_frontier(ts)

        outputs = self._compute_outputs(ok=valid)
        # Saída fria (readback configurado e ainda sem valor) NÃO atualiza o hold: `_mv_last`
        # é "o último valor que a porta de fato apresentou", e um `None` não é um valor.
        # Só as chaves de MV (`self._mv_ids`) — nunca `outputs.items()` cru: desde a decisão
        # A-10 revista `outputs` também carrega `local`/`auto` (portas fixas de modo, sem
        # `mv.limits`/`initial_value`), que não pertencem a este dict (contrato de
        # `reset()`/`EstadoMpcTransplante.mv_last`: só MV).
        self._mv_last = {
            mv_id: self._mv_last[mv_id] if outputs[mv_id].v is None else float(outputs[mv_id].v)  # type: ignore[arg-type]
            for mv_id in self._mv_ids
        }
        await self._write_pid(outputs, ok=valid)

        if is_frontier:
            # Publica DEPOIS de `_mv_last` atualizado (achado F-5): publicar antes fazia
            # `vars.<mv_id>.v` reportar a MV da varredura ANTERIOR enquanto
            # `vars.<cv_id>.v` já reportava a atual — skew de uma varredura que corrompe
            # o overlay de trend do F5 (spec §5.2, "publicação a cada execução").
            await self._publish(self._build_state(ts))

        return outputs

    def _valor_previsto(self, row_id: str) -> float | None:
        """Valor simulado de uma linha com medição ruim (RF-613): o primeiro passo à frente
        da última predição aplicada (índice 1 da série — o 0 é o instante do solve); sem
        predição disponível, a última medição boa (`_last_measured`, hold conservador)."""
        idx = self._row_ids.index(row_id)
        serie = self._last_prediction.cv[idx] if idx < len(self._last_prediction.cv) else []
        if len(serie) > 1:
            return float(serie[1])
        return self._last_measured.get(row_id)

    def _avaliar_fail_actions(self, samples: Mapping[str, PortSample], simuladas: set[str]) -> None:
        """Debounce das fail actions (RF-613), na cadência da fronteira (Ts_mpc): 2
        execuções ruins consecutivas registram a ação final em `_fail_pending` para o
        orquestrador consumir. Só em REMOTO — em LOCAL o MPC não escreve, a ação não teria
        efeito (e os contadores zeram: a entrada em REMOTO recomeça a régua).

        Condição "ruim": linha com amostra ruim NÃO simulada (sem `simulate_*` ou janela
        expirada — motivo `simulate_timeout`) / MV fora de `rcas_ok` (`mv_unavailable`,
        lido do `_mv_status` já apurado nesta varredura). Sã: zera o streak, limpa o
        pendente não consumido e rearma o edge-trigger.
        """
        if self._local_remote != "remote":
            self._fail_streak.clear()
            self._fail_pending.clear()
            self._fail_fired.clear()
            return
        for var_id in (*self._row_ids, *self._mv_ids):
            acao = self._fail_action.get(var_id, "no_action")
            if acao == "no_action":
                continue
            if var_id in self._mv_ids:
                ruim = (
                    self._mv_status.get(var_id, MvAvailability.RCAS_OK)
                    is not MvAvailability.RCAS_OK
                )
                motivo = "mv_unavailable"
                final = acao
            else:
                ruim = not samples[var_id].ok and var_id not in simuladas
                expirou = ruim and var_id in self._simulacao_desde
                motivo = "bad_quality"
                if expirou:
                    agora = time.monotonic()
                    if acao in (
                        "simulate_manual",
                        "simulate_shed_local",
                    ) and agora - self._simulacao_desde[var_id] > self._fail_timeout.get(
                        var_id, 60.0
                    ):
                        motivo = "simulate_timeout"
                final = {
                    "simulate_manual": "manual",
                    "simulate_shed_local": "shed_local",
                }.get(acao, acao)
            if not ruim:
                self._fail_streak.pop(var_id, None)
                self._fail_pending.pop(var_id, None)
                self._fail_fired.discard(var_id)
                self._simulacao_desde.pop(var_id, None)
                continue
            if var_id in self._fail_fired:
                continue
            streak = self._fail_streak.get(var_id, 0) + 1
            self._fail_streak[var_id] = streak
            if streak >= 2:
                self._fail_pending[var_id] = (final, motivo)
                self._fail_fired.add(var_id)

    @property
    def fail_pending(self) -> dict[str, tuple[str, str]]:
        """Fail actions prontas para o orquestrador: `var_id -> (ação final, motivo)`
        (RF-613). Leitura só — mesmo idioma das properties `mv_status`/`pid_bindings`."""
        return dict(self._fail_pending)

    def pop_fail_pending(self) -> dict[str, tuple[str, str]]:
        """Consome o mapa de fail actions pendentes (orquestrador, um tick por Ts_mpc)."""
        pendente = self._fail_pending
        self._fail_pending = {}
        return pendente

    @property
    def local_shed_modes(self) -> dict[str, int | None]:
        """`var_id -> local_shed_mode` das MVs com `pid` (RF-613): o valor escrito no
        `mode_cmd` em QUALQUER devolução ao controle local; `None` = `mode_values.auto`."""
        return {mv.id: mv.local_shed_mode for mv in self._mvs.values() if mv.pid is not None}

    async def _reclassify_mvs(self) -> None:
        """Reapura o status de cada MV, atualiza a âncora de posição real e audita só as
        TRANSIÇÕES (ADR-028).

        A âncora (`_last_good_readback`) é gravada ANTES de o status novo valer, e a partir
        da leitura viva: é a última posição em que se pode confiar quando a tag azedar na
        varredura seguinte. Sair de `rcas_ok` é `warning` (o MPC perdeu uma alavanca);
        voltar é `info`. A primeira classificação de uma MV nunca emite evento — ver
        `reset()`.
        """
        novo = classify_mvs(self._mvs.values(), self._snapshot)
        for mv in self._mvs.values():
            posicao = self._readback_value(mv)
            if posicao is not None:
                self._last_good_readback[mv.id] = posicao
        for var_id, status in novo.items():
            anterior = self._mv_status.get(var_id)
            if anterior is None or anterior is status:
                continue
            voltou = status is MvAvailability.RCAS_OK
            if voltou and self._plan is not None:
                # O plano guardado para ESTA MV foi calculado antes de a malha ser tomada,
                # contra outra posição e outra condição de planta. Aplicá-lo no primeiro
                # quadro após o retorno é um degrau instantâneo, sem passar pelo Δu — o
                # mesmo erro que a §4.4 já evita em MAN->AUTO zerando `_plan` inteiro. Aqui
                # só a entrada desta MV morre: as demais seguem com o plano vigente, que é
                # legítimo para elas. Sem entrada no plano, a saída segura `_mv_last` (a
                # posição real, mantida enquanto a MV esteve congelada) até o primeiro
                # `SolveResult` NOVO chegar.
                self._plan.pop(var_id, None)
            await self._emit_event(
                origin=self._source,
                severity="info" if voltou else "warning",
                message=(f"MPC '{self.block_id}': MV {var_id} {anterior.value} -> {status.value}"),
                kind=KIND_MPC_MV_STATUS_CHANGED,
                payload={"var_id": var_id, "from": anterior.value, "to": status.value},
            )
        self._mv_status = novo

    def _mv_disponivel(self, mv_id: str) -> bool:
        """`True` quando a MV está sob comando do MPC neste ciclo (ADR-028). MV ainda não
        classificada (antes da 1a varredura) conta como disponível: é o comportamento
        pré-ADR-028, e nenhuma escrita acontece antes de a varredura rodar."""
        return self._mv_status.get(mv_id, MvAvailability.RCAS_OK) is MvAvailability.RCAS_OK

    async def _run_frontier(self, ts: datetime) -> None:
        """Consome um resultado pendente (se houver) e dispara o próximo, se em AUTO.

        `host.poll()` só é chamado aqui — nunca fora de fronteira — então um resultado que
        o worker termina "no meio" de um ciclo do multiplicador fica retido no buffer de
        uma posição do próprio `host` até a PRÓXIMA fronteira: é assim que a porta nunca
        muda no meio da varredura (RF-401) sem o bloco precisar de um buffer próprio.

        `ts` é o instante DESTA fronteira: guardado em `_dispatch_ts` só quando o
        `dispatch()` abaixo é de fato aceito (spec §3.5) — ocupado ⇒ `False` ⇒ o instante
        guardado permanece o da última dispatch aceita, a mesma que o `poll()` de uma
        fronteira futura vai consumir.
        """
        result = self._host.poll()
        if result is not None:
            await self._apply_result(result, ts)

        if self._in_auto:
            request = SolveRequest(
                y={row_id: self._last_measured[row_id] for row_id in self._row_ids},
                # Realimentação por bias (spec §3.3, DMC) precisa do `u` EFETIVAMENTE
                # aplicado à planta — nunca o plano/manual comandado. Por MV: com `pid`, o
                # que está de fato em vigor é o readback (a posição real, que pode divergir
                # do que o bloco escreveu); sem `pid`, o próprio valor mantido pelo bloco JÁ
                # é a posição real (não há malha física entre os dois). `_effective_value`
                # é a mesma resolução usada em LOCAL — u_applied é a mesma pergunta ("qual é
                # o valor físico agora?"), não uma nova regra.
                u_applied={mv_id: self._effective_value(mv) for mv_id, mv in self._mvs.items()},
                d={dv_id: self._last_measured.get(dv_id, 0.0) for dv_id in self._dv_ids},
                sp=dict(self._sp),
                reinit=self._reinit_pending,
                # ADR-028: MVs que não estão sob comando do MPC neste ciclo. O worker as
                # congela no `u_applied` acima (que já é a posição REAL medida, ou o hold
                # do último valor bom quando a leitura não presta) zerando o `dumax` delas
                # no horizonte — elas continuam no modelo, como distúrbio medido, para a
                # predição das CVs seguir correta. Nenhuma exclusão estrutural, nenhum
                # segundo caminho de montagem.
                frozen_mvs=frozen_mv_ids(self._mv_status),
            )
            self._reinit_pending = False
            if self._host.dispatch(request):
                self._dispatch_ts = ts
            else:
                # Worker indisponível na fronteira (não pronto/ocupado/morto): conta e
                # pula, sem novo evento (spec §4.2) — o `mpc_overrun` já saiu (ou sairá)
                # pelo caminho de `poll()` quando o host sintetizar o resultado.
                self._overruns += 1

    async def _apply_result(self, result: SolveResult, ts: datetime) -> None:
        """`ts` é a fronteira que consumiu este resultado (a de `_run_frontier`) — usada só
        como fallback de `_dispatch_ts` (ver abaixo)."""
        if result.status != "overrun":
            self._overrun_reported = False

        # Baseline ANTES de atualizar (fix-final, achado F-1): o host sintetiza o MESMO
        # `status="error"` tanto pra um crash de verdade (pipe morreu, `_CRASHED` em
        # `host.py::_await_response`, respawn agendado) quanto pra
        # `worker.py::_handle` isolar uma exceção de UM pedido (processo segue vivo,
        # NENHUM respawn). Comparar `stats()["respawns"]` com o valor observado da
        # ÚLTIMA vez que este método rodou — não só quando o resultado é "error" —
        # evita falso positivo quando um overrun anterior já tiver disparado um respawn
        # nesse meio-tempo.
        respawns_antes = self._last_respawns
        self._last_respawns = self._host.stats()["respawns"]

        await self._absorver_ssto(result.ssto)

        if result.status == "ok":
            self._plan = dict(result.u_plan)
            self._cost = result.cost
            self._last_prediction = MpcPrediction(
                # Âncora do overlay (spec §3.5, F5R-01): a fronteira em que ESTE resultado
                # foi despachado, guardada por `_run_frontier` — nunca o ts do quadro
                # atual, que já avançou (pelo menos) uma fronteira além do dispatch.
                # Fallback no `ts` desta fronteira (parâmetro do método, não `self._now()`)
                # só cobre um host devolvendo resultado sem dispatch prévio deste bloco
                # (double de teste/hot-swap com host reaproveitado).
                ts=self._dispatch_ts if self._dispatch_ts is not None else ts,
                t=result.prediction_t,
                cv=result.prediction_cv,
                mv=result.prediction_mv,
            )
            self._solver_status = "ok"
        elif result.status == "overrun":
            self._overruns += 1
            self._solver_status = "overrun"
            await self._report_overrun()
        else:
            # `error` (crash real OU exceção isolada, achado F-1) ou `no_convergence`:
            # falha de solver != overrun (RF-624). `u_plan` chega POPULADO (carryover
            # 1.1/1.2) e NUNCA é aplicado — só o ramo `status == "ok"` acima toca
            # `self._plan`.
            self._solver_status = "error"
            if result.status == "no_convergence":
                reason = "no_convergence"
            elif self._last_respawns > respawns_antes:
                reason = "crash"
            else:
                # Worker vivo, nenhum respawn: `worker.py::_handle` isolou uma exceção
                # de UM pedido — não é o crash literal do §4.9. Extensão deliberada do
                # enum de `mpc_solver_error` (§5.3 documenta `no_convergence|crash`);
                # justificativa completa no relatório da tarefa.
                reason = "exception"
            await self._report_solver_error(reason, result.detail)

    # ------------------------------------------------------------------------------
    # Saída por modo (spec §4.3)
    # ------------------------------------------------------------------------------

    def _compute_outputs(self, *, ok: bool) -> dict[str, PortSample]:
        outputs: dict[str, PortSample] = {}
        for mv in self._mvs.values():
            if self._local_remote == "local":
                rastreado = self._local_output(mv)
                if rastreado is None:
                    outputs[mv.id] = PortSample(None, False)
                    continue
                v = rastreado
            elif not self._mv_disponivel(mv.id):
                # MV indisponível em REMOTO (ADR-028): quem manda naquele atuador é a
                # planta, então a porta reporta a posição vigente — leitura viva, última
                # leitura confiável, e só então o hold — em vez do plano do MPC. É o que
                # faz a devolução do controle ser bumpless: a porta nunca conta uma
                # história que o atuador não viveu, e o `_mv_last` que ancora o retorno é a
                # posição física, não o cálculo do próprio controlador.
                #
                # NÃO cai na porta fria do LOCAL: lá o `None` existe para o `opc_write` a
                # jusante não escrever um `initial_value` que ninguém comandou. Aqui a
                # escrita desta MV já está suprimida em `_write_pid`, e apagar a porta
                # apagaria também o hold que o retorno usa como âncora.
                v = self._effective_value(mv)
                if self._man_auto == "man":
                    # Mesma regra de "MV manual := vigente" das transições (spec §4.4):
                    # sem isto, a MV voltando a RCAS em MAN saltaria para o valor manual
                    # de antes da perda da malha.
                    self._mv_manual[mv.id] = _clamp(v, mv.limits.min, mv.limits.max)
            elif self._man_auto == "man":
                v = _clamp(self._mv_manual[mv.id], mv.limits.min, mv.limits.max)
            else:
                # `.get`: a entrada de uma MV que acabou de voltar a RCAS foi removida do
                # plano (`_reclassify_mvs`) — sem plano para ela, vale o hold da posição
                # real até o primeiro `SolveResult` novo.
                plano = self._plan.get(mv.id) if self._plan is not None else None
                v = self._mv_last[mv.id] if plano is None else plano
            outputs[mv.id] = PortSample(v, ok)
        # Portas fixas de modo (decisão A-10 revista, spec F4 §2.1-5): eixos LOCAL/REMOTO e
        # MAN/AUTO do próprio bloco, nunca uma variável do usuário — sempre numéricas
        # (decisão A-5), 1.0/0.0. Mesmo `ok` do resto da varredura (decisão A-6: uma
        # invalidez, uma flag, em toda porta do bloco).
        outputs[MPC_PORT_LOCAL] = PortSample(1.0 if self._local_remote == "local" else 0.0, ok)
        outputs[MPC_PORT_AUTO] = PortSample(1.0 if self._man_auto == "auto" else 0.0, ok)
        return outputs

    def _local_output(self, mv: MvVar) -> float | None:
        """Saída da MV em LOCAL (spec §4.3): a posição real lida da planta.

        `None` quando a MV tem tag de readback configurada e ela ainda não publicou nada — a
        porta sai FRIA (padrão F3 §3.0) e o `opc_write` a jusante suprime a escrita. Emitir o
        `initial_value` aqui seria pior que não emitir: em LOCAL quem manda no atuador é a
        planta, e um valor de config escrito por cima é um degrau que ninguém comandou (o
        caso concreto é a janela de cada redeploy, antes da 1a amostra da tag chegar). É o
        mesmo estado que `auto_arm_blocked_reason()` já chama de `cold_input`.

        Sem tag de readback não há o que esperar: vale o hold de sempre."""
        if self._readback_tag_id(mv) is None:
            return self._mv_last[mv.id]
        return self._readback_value(mv)

    def _readback_tag_id(self, mv: MvVar) -> int | None:
        """Tag da posição real da MV: com `pid`, a do `pid` (spec §2.1-3); sem `pid`, a
        `readback_tag_id` da própria MV, quando configurada. Uma pergunta só num lugar só —
        `_effective_value`, `auto_arm_blocked_reason` e o classificador do ADR-028 têm que
        concordar sobre onde olhar; por isso a resposta mora em `mpc/availability.py` e aqui
        só se delega."""
        return readback_tag_id(mv)

    def _readback_value(self, mv: MvVar) -> float | None:
        """Posição real da MV lida do barramento. `None` quando não há tag de readback
        configurada, quando a tag ainda não publicou nada, OU quando a última amostra veio
        com qualidade ruim — quem chama decide se isso vira hold (`_effective_value`) ou
        porta fria (`_local_output`).

        `quality != 0` invalida, uncertain inclusive: é a mesma régua conservadora do
        `opc_read` (spec F3 §3.1). Uma amostra ruim NÃO é medição de posição — adotá-la
        faria a MV seguir lixo em LOCAL e semear `_mv_manual` com ele na entrada em
        REMOTO+MAN. Visto em campo: num restart da planta as tags de readback voltaram
        `0,0` com `quality=2`."""
        tag_id = self._readback_tag_id(mv)
        if tag_id is None:
            return None
        tag = self._snapshot.get(tag_id)
        if tag is None or tag.quality != 0:
            return None
        return float(tag.value)

    def _effective_value(self, mv: MvVar) -> float:
        """Valor físico "vigente" de uma MV: a posição real lida da planta quando há tag de
        readback, ou o hold do último valor/`initial_value` enquanto ela não chega. É o
        `u_applied` do `SolveRequest` (§3.3) — "qual é a posição real agora?".

        É também o que torna a transferência bumpless: entrar em REMOTO+MAN copia o valor
        vigente (§4.4) e entrar em AUTO arma sobre esse mesmo valor (§3.6), então nenhuma
        das duas transições move o atuador. O gate de `auto_arm_blocked_reason()` garante
        que, com tag configurada, nenhum dos dois eixos arma antes de ela chegar — o hold
        abaixo nunca é a base de um arme.

        ADR-028 insere um degrau entre a leitura viva e o hold: a ÚLTIMA posição real
        confiável. Só entra em cena quando a tag existia e parou de prestar (MV virou
        `bad_quality`/`out_of_service`), e é o que mantém o congelamento ancorado na planta
        em vez de no último plano do próprio MPC — que é o que `_mv_last` guarda em AUTO."""
        value = self._readback_value(mv)
        if value is not None:
            return value
        ultimo_bom = self._last_good_readback.get(mv.id)
        return self._mv_last[mv.id] if ultimo_bom is None else ultimo_bom

    async def _write_pid(self, outputs: Mapping[str, PortSample], *, ok: bool) -> None:
        """Publica `OpcWrite` por MV com `pid`, a cada varredura, só em REMOTO com entrada
        válida (spec §4.3/§4.6) — em LOCAL não escreve nada, RF-621.

        `conn_id` sai como `0`: `PidBinding` não carrega a conexão da tag (só o
        `write_tag_id`) — a resolução tag->conexão é de quem monta o `write_opc` real
        (`definition.py`, mesma consulta de `_project_tags`, débito #3 da spec F4 §8,
        fechado na tarefa 2.2: o `write_opc` injetado já resolve o `conn_id` verdadeiro
        antes de publicar).
        """
        if self._local_remote != "remote" or not ok:
            return
        for mv in self._mvs.values():
            if mv.pid is None:
                continue
            if not self._mv_disponivel(mv.id):
                # ADR-028: MV fora de RCAS / sem leitura confiável não recebe escrita. É o
                # núcleo do problema que o ADR resolve: sem BKCAL, escrever numa malha que
                # não está ouvindo é exatamente o que arma o bump da devolução — o PID
                # ignora o valor enquanto está em LOCAL e, no instante em que volta a
                # RCAS, encontra um comando velho já no registrador.
                continue
            await self._write_opc(
                OpcWrite(
                    conn_id=0,
                    tag_id=mv.pid.write_tag_id,
                    flow_id=0,
                    value=float(outputs[mv.id].v),  # type: ignore[arg-type]
                    source=self._source,
                    ts=datetime.now(UTC),
                )
            )

    # ------------------------------------------------------------------------------
    # Eventos (spec §5.3) — dedupe por período nos que a spec pede (overrun/invalidez)
    # ------------------------------------------------------------------------------

    async def _absorver_ssto(self, run: SstoRun | None) -> None:
        """Guarda o registro da camada de alvos para a publicação desta fronteira e alarma
        quando ela não fechou (ADR-027 §10/§11).

        `relaxed` não alarma: desistir de linha de baixa prioridade é o comportamento
        projetado do SSTO e já fica registrado em `given_up`. Só o fracasso — que faz o
        ciclo cair no SP do operador — é evento operacional, deduplicado por episódio.
        """
        if run is None:
            return
        self._ssto_pending = run
        if run.status in ("optimal", "relaxed"):
            self._ssto_infeasible_reported = False
            return
        if self._ssto_infeasible_reported:
            return
        self._ssto_infeasible_reported = True
        await self._emit_event(
            origin=self._source,
            severity="warning",
            message=(
                f"MPC '{self.block_id}': SSTO não fechou ({run.status})"
                " — alvos caíram no SP do operador"
            ),
            kind=KIND_SSTO_INFEASIBLE,
            payload={"status": run.status, "solver": run.solver},
        )

    async def _report_overrun(self) -> None:
        if self._overrun_reported:
            return
        self._overrun_reported = True
        await self._emit_event(
            origin=self._source,
            severity="warning",
            message=f"MPC '{self.block_id}': orçamento do solve estourado",
            kind=KIND_MPC_OVERRUN,
            payload={"overruns": self._overruns},
        )

    async def _report_solver_error(self, reason: str, detail: str) -> None:
        message = f"MPC '{self.block_id}': falha do solver ({reason})"
        if detail:
            # Diagnóstico do worker (traceback aparado de `worker.py::_handle`, ou o
            # `detail` sintético do host pro crash) — achado F-1: antes ficava só no
            # `SolveResult`, nunca chegava a lugar nenhum. Mensagem, não payload: o
            # payload `{reason: ...}` é o documentado em §5.3 e não ganha campo novo.
            message = f"{message} — {detail}"
        await self._emit_event(
            origin=self._source,
            severity="alarm",
            message=message,
            kind=KIND_MPC_SOLVER_ERROR,
            payload={"reason": reason},
        )

    async def _report_input_invalid(self) -> None:
        if self._input_invalid_reported:
            return
        self._input_invalid_reported = True
        await self._emit_event(
            origin=self._source,
            severity="warning",
            message=f"MPC '{self.block_id}': entrada inválida — solve pulado",
            kind=KIND_MPC_INPUT_INVALID,
            payload={},
        )

    # ------------------------------------------------------------------------------
    # Comandos (spec §4.8) — `flow.commands` já roteado pelo supervisor (tarefa 2.2)
    # ------------------------------------------------------------------------------

    async def command(self, cmd: str, args: dict, user: str | None) -> None:
        if cmd == "mpc_mode":
            await self._command_mode(args, user)
        elif cmd == "mpc_sp":
            await self._command_sp(args, user)
        elif cmd == "mpc_mv":
            await self._command_mv(args, user)
        # `cmd` desconhecido: ignora (padrão F3 §2.2-7, comando inválido não derruba nada).

    async def _command_mode(self, args: dict, user: str | None) -> None:
        axis = args["axis"]
        value = args["value"]
        if axis == "local_remote" and value in ("local", "remote"):
            if value == self._local_remote:
                return  # idempotente
            old = self._local_remote
            self._local_remote = value
            if value == "remote":
                # Entra em MAN; MV manual := vigente (spec §4.4, sem salto na transição).
                self._man_auto = "man"
                self._mv_manual = dict(self._mv_last)
            await self._audit_mode_changed("local_remote", old, value, user)
        elif axis == "man_auto" and value in ("man", "auto"):
            if self._local_remote == "local":
                return  # sub-modo só existe em REMOTO (ADR-010)
            if value == self._man_auto:
                return  # idempotente
            old = self._man_auto
            self._man_auto = value
            if value == "auto":
                # Bumpless (spec §3.6): a PRÓXIMA dispatch precisa de `reinit=True` — o host
                # só força isso sozinho em boot/respawn (docstring de `mpc/host.py`), não em
                # MAN->AUTO, então o bloco carrega o sinalizador até o próximo `dispatch()`.
                self._reinit_pending = True
                # E o plano guardado MORRE aqui. Ele foi calculado antes de o operador
                # assumir, contra outro `u_prev` e outra condição de planta; como a saída em
                # AUTO é `_plan` quando existe, mantê-lo faria a MV pular para ele no
                # primeiro quadro — degrau instantâneo, sem passar pelo Δu, exatamente no
                # instante da devolução do controle. Sem plano, a saída segura o último valor
                # do MAN (`_mv_last`) até o primeiro `SolveResult` NOVO chegar: é o "a partir
                # do último valor em MAN" da §4.4. Visto em planta: MV reposta em 52 % no MAN
                # e a volta para AUTO jogando o atuador para os 7 % de um plano anterior.
                self._plan = None
            else:
                self._mv_manual = dict(self._mv_last)  # AUTO->MAN: MV manual := MV vigente
            await self._audit_mode_changed("man_auto", old, value, user)

    async def _audit_mode_changed(self, axis: str, old: str, new: str, user: str | None) -> None:
        await self._emit_event(
            origin=self._source,
            severity="info",
            message=f"MPC '{self.block_id}': modo {axis} {old} -> {new}",
            kind=KIND_MPC_MODE_CHANGED,
            payload={"axis": axis, "from": old, "to": new, "user": user},
        )
        await self._publish(self._build_state(self._now()))

    async def _command_sp(self, args: dict, user: str | None) -> None:
        if not self._in_auto:
            return  # fora de AUTO o PV-tracking manda (spec §4.8)
        var_id = args["var_id"]
        cv = self._cvs.get(var_id)
        if cv is None:
            return
        clamped = _clamp(float(args["value"]), cv.sp_limits.min, cv.sp_limits.max)
        if self._sp.get(var_id) == clamped:
            return  # idempotente
        self._sp[var_id] = clamped
        if self._persist_sp is not None:
            try:
                await self._persist_sp(var_id, clamped)
            except Exception:
                # Persistência é telemetria do estado do operador: o banco cair não pode
                # derrubar o laço de controle nem desfazer o SP materializado (RNF-05).
                logger.exception(
                    "Falha ao persistir SP de '%s' do bloco MPC '%s'", var_id, self.block_id
                )
        await self._emit_event(
            origin=self._source,
            severity="info",
            message=f"MPC '{self.block_id}': SP de {var_id} escrito para {clamped}",
            kind=KIND_MPC_SP_WRITTEN,
            payload={"var_id": var_id, "value": clamped, "user": user},
        )
        await self._publish(self._build_state(self._now()))

    async def _command_mv(self, args: dict, user: str | None) -> None:
        if self._local_remote != "remote" or self._man_auto != "man":
            return  # só materializa em REMOTO+MAN (spec §4.8)
        var_id = args["var_id"]
        mv = self._mvs.get(var_id)
        if mv is None:
            return
        clamped = _clamp(float(args["value"]), mv.limits.min, mv.limits.max)
        if self._mv_manual.get(var_id) == clamped:
            return  # idempotente
        self._mv_manual[var_id] = clamped
        await self._emit_event(
            origin=self._source,
            severity="info",
            message=f"MPC '{self.block_id}': MV manual de {var_id} escrita para {clamped}",
            kind=KIND_MPC_MV_WRITTEN,
            payload={"var_id": var_id, "value": clamped, "user": user},
        )
        await self._publish(self._build_state(self._now()))

    # ------------------------------------------------------------------------------
    # Estado publicado (spec §5.1) e `/health` (spec §4.10, tarefa 2.3)
    # ------------------------------------------------------------------------------

    def _build_state(self, ts: datetime) -> MpcState:
        """`ts` vem de quem chama: a fronteira de varredura nas publicações de fronteira
        (spec F5 §2.1-1), o instante da própria publicação nas imediatas (mudança de modo,
        SP/MV materializada — F4 §5.2). Nunca decidido aqui."""
        armed = self._local_remote == "remote"
        auto = self._in_auto
        cv_id_set = set(self._cv_ids)

        var_state: dict[str, MpcVarState] = {}
        for row_id in self._row_ids:
            var_state[row_id] = MpcVarState(
                v=self._last_measured.get(row_id, 0.0),
                sp=self._sp.get(row_id) if row_id in cv_id_set else None,
            )
        for dv_id in self._dv_ids:
            var_state[dv_id] = MpcVarState(v=self._last_measured.get(dv_id, 0.0))
        for mv_id in self._mv_ids:
            status_mv = self._mv_status.get(mv_id)
            var_state[mv_id] = MpcVarState(
                v=self._mv_last.get(mv_id, 0.0),
                # ADR-028: só MV publica `status` (como só CV publica `sp`). `None` antes da
                # primeira classificação — nunca um `rcas_ok` que ninguém verificou.
                status=status_mv.value if status_mv is not None else None,
            )

        if not self._host.ready:
            # spec F5 §6.2 (emenda F4 §4.2/§5.1, tarefa 4.1 F5a — F-1): `building` precede
            # `idle` em QUALQUER modo, LOCAL/REMOTO+MAN inclusive — não só AUTO. `idle`
            # fica reservado a "worker pronto e ocioso fora de AUTO". Antes desta tarefa o
            # `not auto` abaixo saía primeiro e forçava `idle` sem olhar `host.ready`: como
            # o deploy nasce sempre LOCAL (RNF-03), `building` nunca era alcançado — o
            # operador não tinha nenhum estado publicado que explicasse a janela de boot.
            solver: _SolverStatus | Literal["building", "idle"] = "building"
        elif not auto:
            solver = "idle"
        elif self._solver_status == "ok" and self._plan is None:
            # Defesa em profundidade (achado da tarefa 4.2): "ok" sem `_plan` aplicado
            # seria o rótulo sem evidência — mantém o valor honesto anterior (o padrão
            # "idle" do `reset()`, ou o último status real já aplicado) até o primeiro
            # `SolveResult` genuíno.
            solver = "idle"
        else:
            solver = self._solver_status

        stats = self._host.stats()
        # Consome o registro pendente: ele sobe UMA vez, no quadro seguinte à aplicação do
        # resultado que o produziu (ADR-027 §11). Publicações imediatas (mudança de modo,
        # SP/MV) também o consomem se estiverem à frente — o que importa é não repetir.
        ssto, self._ssto_pending = self._ssto_pending, None
        return MpcState(
            ts=ts,
            modes=MpcModes(local_remote=self._local_remote, man_auto=self._man_auto),
            status=MpcStatus(
                solver=solver,
                overruns=self._overruns,
                last_solve_ms=stats["last_solve_ms"] or 0.0,
                armed=armed,
                input_valid=self._input_ok,
            ),
            vars=var_state,
            cost=self._cost,
            prediction=self._last_prediction if auto else _empty_prediction(ts),
            ssto=ssto,
        )

    def health(self) -> dict:
        stats = self._host.stats()
        return {
            "mode": {"local_remote": self._local_remote, "man_auto": self._man_auto},
            "overruns": self._overruns,
            "last_solve_ms": stats["last_solve_ms"],
            "worker": stats,
        }
