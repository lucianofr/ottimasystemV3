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
`write_suppressed`/`flow_overrun`.

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

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from ottima_core.bus import (
    KIND_MPC_INPUT_INVALID,
    KIND_MPC_MODE_CHANGED,
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
from ottima_core.flowgraph import CvVar, MpcConfig, MvVar, PidBinding, derive_horizons

from ..mpc.host import MpcHost
from ..mpc.worker import SolveRequest, SolveResult
from ..snapshot import ValueSnapshot
from .base import Block, PortSample, has_cold_input, null_outputs

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
        return self._mv_ids

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
        self._sp: dict[str, float] = dict.fromkeys(self._cv_ids, 0.0)
        self._last_measured: dict[str, float] = {}
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

        samples = {pid: inputs.get(pid, PortSample(None, False)) for pid in self._entrada_ids}
        if has_cold_input(samples):
            if is_frontier:
                # Cold start (§3.0 F3): saídas nulas — mas §5.2 pede publicação a cada
                # execução MESMO fora de AUTO, então a fronteira ainda precisa emitir um
                # frame honesto (achado F-5): sem isso, um flow recém-implantado fica
                # mudo em `mpc.state.*` até a 1a varredura totalmente quente.
                self._input_ok = False
                await self._publish(self._build_state(ts))
            return null_outputs(self._mv_ids)

        valid = all(sample.ok for sample in samples.values())
        self._input_ok = valid
        if valid:
            self._input_invalid_reported = False
            for var_id, sample in samples.items():
                self._last_measured[var_id] = float(sample.v)  # type: ignore[arg-type]
            if not self._in_auto:
                for cv_id in self._cv_ids:
                    self._sp[cv_id] = self._last_measured[cv_id]
        else:
            await self._report_input_invalid()

        if is_frontier and valid:
            await self._run_frontier(ts)

        outputs = self._compute_outputs(ok=valid)
        # Saída fria (readback configurado e ainda sem valor) NÃO atualiza o hold: `_mv_last`
        # é "o último valor que a porta de fato apresentou", e um `None` não é um valor.
        self._mv_last = {
            mv_id: self._mv_last[mv_id] if sample.v is None else float(sample.v)
            for mv_id, sample in outputs.items()
        }
        await self._write_pid(outputs, ok=valid)

        if is_frontier:
            # Publica DEPOIS de `_mv_last` atualizado (achado F-5): publicar antes fazia
            # `vars.<mv_id>.v` reportar a MV da varredura ANTERIOR enquanto
            # `vars.<cv_id>.v` já reportava a atual — skew de uma varredura que corrompe
            # o overlay de trend do F5 (spec §5.2, "publicação a cada execução").
            await self._publish(self._build_state(ts))

        return outputs

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
                d={dv_id: self._last_measured[dv_id] for dv_id in self._dv_ids},
                sp=dict(self._sp),
                reinit=self._reinit_pending,
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
            elif self._man_auto == "man":
                v = _clamp(self._mv_manual[mv.id], mv.limits.min, mv.limits.max)
            else:
                v = self._plan[mv.id] if self._plan is not None else self._mv_last[mv.id]
            outputs[mv.id] = PortSample(v, ok)
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
        `_effective_value` e `auto_arm_blocked_reason` têm que concordar sobre onde olhar."""
        return mv.pid.readback_tag_id if mv.pid is not None else mv.readback_tag_id

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
        abaixo nunca é a base de um arme."""
        value = self._readback_value(mv)
        return self._mv_last[mv.id] if value is None else value

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
            await self._write_opc(
                OpcWrite(
                    conn_id=0,
                    tag_id=mv.pid.write_tag_id,
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
            var_state[mv_id] = MpcVarState(v=self._mv_last.get(mv_id, 0.0))

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
