"""BlockShell: a maquina de modos FF que envolve um ControlKernel (ADR-039).

Nenhum `if` deste arquivo testa uma TRANSICAO especifica de modo — as transicoes emergem
da resolucao por prioridade (secao 4.3) e da tabela de saida forcada (secao 4.4). Um `if`
de transicao aqui e defeito de projeto (ADR-039 secao 4.7).
"""

import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ottima_core.bus import LoopState
from ottima_flow_runtime.blocks.base import Block, PortSample
from ottima_flow_runtime.blocks.shell.config import ShellCfg, clamp, scale_pct, unscale_pct
from ottima_flow_runtime.blocks.shell.kernel import ControlKernel
from ottima_flow_runtime.blocks.shell.mode import (
    CALCULATING_MODES,
    MODE_NAMES,
    Mode,
    ModeBlock,
    mode_from_name,
)
from ottima_flow_runtime.blocks.shell.signal import (
    Quality,
    Substatus,
    as_signal,
    make_signal,
)

KIND_LOOP_MODE_CHANGED = "loop_mode_changed"
KIND_LOOP_SHED = "loop_shed"
KIND_LOOP_MODE_REJECTED = "loop_mode_rejected"
KIND_LOOP_ALARM = "loop_alarm"
KIND_LOOP_LIMITED = "loop_limited"

LOOP_STATE_MIN_INTERVAL_S = 0.25

EmitEvent = Callable[..., Awaitable[None]]
PublishState = Callable[[Any], Awaitable[None]]
PersistOp = Callable[[str, float | str], Awaitable[None]]

_SHED_DESTINO = {"shed_to_auto": Mode.AUTO, "shed_to_man": Mode.MAN}


@dataclass(frozen=True, slots=True)
class CarriedState:
    """Estado carregado de uma instancia anterior no hot-swap estrutural (ADR-039 D11)."""

    u: float
    sp_op: float
    man_out: float
    was_calculating: bool


class BlockShell(Block):
    def __init__(
        self,
        block_id: str,
        *,
        kernel: ControlKernel,
        cfg: ShellCfg,
        emit_event: EmitEvent | None = None,
        publish_state: PublishState | None = None,
        persist_op: PersistOp | None = None,
        sp_seed: float | None = None,
        man_out_seed: float | None = None,
        carry: CarriedState | None = None,
    ) -> None:
        super().__init__(block_id)
        self.kernel = kernel
        self.cfg = cfg
        self._emit_event = emit_event
        self._publish_state = publish_state
        self._persist_op = persist_op

        self.mode = ModeBlock(permitted=cfg.permitted, normal=cfg.normal)
        self.pv: float | None = None
        self.pv_ok = False
        self.diag: dict[str, float] = {}
        self._ts_prev: datetime | None = None
        self._prev_actual = Mode.OOS
        self._bias = 0.0
        self._rebase_bias = False
        self._pendentes: list[dict[str, Any]] = []
        # Alarmes de NIVEL (ADR-039: evento por transicao, nao por scan). O rearme e por
        # scan: `_finish` — funil unico de todos os returns de `step` — promove as condicoes
        # observadas nesta varredura a `_prev`, entao um scan que NAO observa a condicao
        # encerra o episodio. Latch por flag exigia um clear em cada rota que pula a
        # avaliacao, e as que faltavam (saida forcada e dt invalido, ambas sem `compute()`)
        # silenciavam `kernel_invalid_output` para sempre. Dois conjuntos reusados: a troca
        # e por referencia, sem alocar por varredura.
        self._alarmes: set[str] = set()
        self._alarmes_prev: set[str] = set()

        if carry is not None:
            self.u = clamp(carry.u, cfg.out_lo_lim, cfg.out_hi_lim)
            self.sp_op = clamp(carry.sp_op, cfg.sp_lo_lim, cfg.sp_hi_lim)
            self.man_out = clamp(carry.man_out, cfg.out_lo_lim, cfg.out_hi_lim)
            if carry.was_calculating:
                self._defer_event(
                    kind=KIND_LOOP_ALARM,
                    severity="warning",
                    message="Config estrutural trocada com a malha calculante: aterrissagem em MAN",
                    payload={"block_id": block_id, "code": "structural_swap_landed_man"},
                )
        else:
            self.u = clamp(cfg.out_startup, cfg.out_lo_lim, cfg.out_hi_lim)
            self.sp_op = clamp(
                sp_seed if sp_seed is not None else cfg.sp_lo_lim, cfg.sp_lo_lim, cfg.sp_hi_lim
            )
            self.man_out = clamp(
                man_out_seed if man_out_seed is not None else self.u,
                cfg.out_lo_lim,
                cfg.out_hi_lim,
            )
        self.u_int = self.u
        self.u_prev = self.u
        self.sp = self.sp_op
        self._last_publish = 0.0

    # -- portas -------------------------------------------------------------
    @property
    def input_ports(self) -> tuple[str, ...]:
        return (
            "in",
            "cas_in",
            "rcas_in",
            "rout_in",
            "bkcal_in",
            "bias_in",
            "trk_in_d",
            "lo_in_d",
        )

    @property
    def output_ports(self) -> tuple[str, ...]:
        return ("out", "bkcal_out")

    # -- escritas de operacao ------------------------------------------------
    def write_target(self, mode: Mode) -> bool:
        if not (mode & self.cfg.permitted):
            self._defer_event(
                kind=KIND_LOOP_MODE_REJECTED,
                severity="warning",
                message=f"Modo '{MODE_NAMES[mode]}' fora de PERMITTED",
                payload={"block_id": self.block_id, "requested": MODE_NAMES[mode]},
            )
            return False
        self.mode.target = mode
        return True

    def write_sp(self, value: float) -> None:
        self.sp_op = clamp(value, self.cfg.sp_lo_lim, self.cfg.sp_hi_lim)

    def write_out(self, value: float) -> None:
        self.man_out = clamp(value, self.cfg.out_lo_lim, self.cfg.out_hi_lim)

    async def command(self, cmd: str, args: dict[str, Any], user: str | None) -> None:
        """Comandos de operacao (RNF-05): a API publica, o runtime materializa e audita."""
        if cmd == "loop_mode":
            alvo = mode_from_name(str(args["target"]))
            if self.write_target(alvo):
                await self._audit("loop_target_written", user, {"target": args["target"]})
                if self._persist_op is not None:
                    await self._persist_op("target", str(args["target"]))
        elif cmd == "loop_sp":
            self.write_sp(float(args["value"]))
            await self._audit("loop_sp_written", user, {"value": self.sp_op})
            if self._persist_op is not None:
                await self._persist_op("sp", self.sp_op)
        elif cmd == "loop_out":
            self.write_out(float(args["value"]))
            await self._audit("loop_out_written", user, {"value": self.man_out})
            if self._persist_op is not None:
                await self._persist_op("man_out", self.man_out)

    async def _audit(self, kind: str, user: str | None, payload: dict[str, Any]) -> None:
        if self._emit_event is None:
            return
        await self._emit_event(
            kind=kind,
            severity="info",
            message=f"Escrita de operacao ({kind}) por {user or 'desconhecido'}",
            origin=f"bloco:{self.block_id}",
            payload={"block_id": self.block_id, "user": user, **payload},
        )

    def apply_tuning(self, cfg: ShellCfg, kernel_cfg: Any | None = None) -> None:
        """Classe de sintonia do hot-swap (ADR-039 D11): in-place, sem perder estado."""
        self.cfg = cfg
        self.mode.permitted = cfg.permitted
        self.mode.normal = cfg.normal
        if kernel_cfg is not None:
            self.kernel.cfg = kernel_cfg  # type: ignore[attr-defined]
        self._rebase_bias = True

    def carry_state(self) -> CarriedState:
        return CarriedState(
            u=self.u,
            sp_op=self.sp_op,
            man_out=self.man_out,
            was_calculating=self.mode.actual in CALCULATING_MODES,
        )

    # -- ciclo ---------------------------------------------------------------
    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        dt = self._measure_dt(ts)
        self._update_pv(inputs.get("in"), dt)
        pv_k = self.pv if self.pv is not None else self.sp
        kernel_errors = self.kernel.validate()

        if dt is None or not (0.0 < dt <= self.cfg.max_dt):
            if dt is not None:
                self._alarme_nivelado(
                    "scan_lost",
                    kind=KIND_LOOP_ALARM,
                    message=f"Scan perdido (dt={dt:.3f}s)",
                    payload={"block_id": self.block_id, "code": "scan_lost", "dt": dt},
                )
            if not kernel_errors and dt is None:
                self.mode.actual = self._resolve_mode(inputs, kernel_errors)
                m = self.mode.actual
                # Partida: o SP operacional e o alvo do align (SPEC_PID §3.2) — sem isto,
                # um write_sp antes do primeiro scan fica invisivel ao kernel e o primeiro
                # AUTO carrega um chute proporcional fantasma (ep_prev alinhado em sp=0).
                self.sp = clamp(self.sp_op, self.cfg.sp_lo_lim, self.cfg.sp_hi_lim)
                self._entrar_em_man_inicializa_man_out(m)
                forced = self._forced_output(m, inputs)
                if forced is not None:
                    self.u = clamp(forced, self.cfg.out_lo_lim, self.cfg.out_hi_lim)
                    self.u_int = self.u - self._bias
                    self.u_prev = self.u
            self.kernel.align(self.u, self.sp, pv_k)
            return await self._finish(inputs)

        self.mode.actual = self._resolve_mode(inputs, kernel_errors)
        m = self.mode.actual
        self.sp = self._resolve_sp(m, inputs, dt)
        bias = self._resolve_bias(inputs.get("bias_in"))
        if self._rebase_bias:
            self.u_int = self.u - bias
            self._rebase_bias = False

        self._entrar_em_man_inicializa_man_out(m)
        forced = self._forced_output(m, inputs)
        if forced is not None:
            self.u = clamp(forced, self.cfg.out_lo_lim, self.cfg.out_hi_lim)
            self.u_int = self.u - bias
            self.kernel.align(self.u, self.sp, pv_k)
            self.u_prev = self.u
            return await self._finish(inputs)

        du_dt = self.kernel.compute(self.sp, pv_k, dt)
        if not math.isfinite(du_dt):
            self._alarme_nivelado(
                "kernel_invalid_output",
                kind=KIND_LOOP_ALARM,
                message="Kernel devolveu resultado invalido; OUT mantido",
                payload={"block_id": self.block_id, "code": "kernel_invalid_output"},
            )
            self.kernel.align(self.u, self.sp, pv_k)
            return await self._finish(inputs)
        # Diagnostico do kernel (SPEC_FUZZY secao 8): so depois de um compute VALIDO — num
        # scan invalido o `return` acima preserva o ultimo quadro bom, que e o que o
        # operador precisa ver no faceplate para achar a regiao sem regra.
        kernel_diag = getattr(self.kernel, "diag", None)
        if kernel_diag:
            self.diag = dict(kernel_diag)
        u = self._rate_limit(self.u_int + du_dt * dt + bias, dt)
        self.u = clamp(u, self.cfg.out_lo_lim, self.cfg.out_hi_lim)
        self.u_int = self.u - bias
        self.u_prev = self.u
        return await self._finish(inputs)

    # -- pedacos -------------------------------------------------------------
    def _measure_dt(self, ts: datetime | None) -> float | None:
        if ts is None:
            return None
        prev, self._ts_prev = self._ts_prev, ts
        if prev is None:
            return None
        return (ts - prev).total_seconds()

    def _update_pv(self, sample: PortSample | None, dt: float | None) -> None:
        if sample is None or sample.v is None:
            self.pv_ok = False
            return
        v = float(sample.v)
        if not math.isfinite(v):
            self.pv_ok = False
            return
        self.pv_ok = as_signal(sample).is_good
        if self.pv is None or self.cfg.pv_ftime <= 0.0 or dt is None or dt <= 0.0:
            self.pv = v
            return
        a = dt / (self.cfg.pv_ftime + dt)
        self.pv = self.pv + a * (v - self.pv)

    def _resolve_mode(self, inputs: Mapping[str, PortSample], kernel_errors: list[str]) -> Mode:
        cfg = self.cfg
        target = self.mode.target
        if kernel_errors or target is Mode.OOS:
            return Mode.OOS
        efetivo = target if (target & cfg.permitted) else self.mode.normal
        bk = inputs.get("bkcal_in")
        if bk is not None and bk.v is not None and as_signal(bk).init_request:
            return Mode.IMAN
        lo = inputs.get("lo_in_d")
        if lo is not None and bool(lo.v) and lo.ok:
            return Mode.LO
        if not self.pv_ok and efetivo in CALCULATING_MODES:
            return Mode.MAN
        for modo, porta in ((Mode.CAS, "cas_in"), (Mode.RCAS, "rcas_in"), (Mode.ROUT, "rout_in")):
            if efetivo is modo:
                fonte = inputs.get(porta)
                if fonte is None or fonte.v is None or not as_signal(fonte).is_good:
                    return self._shed(efetivo)
        return efetivo

    def _shed(self, alvo: Mode) -> Mode:
        destino = _SHED_DESTINO.get(self.cfg.shed_opt, self.mode.normal)
        if self.cfg.shed_no_return and self.mode.target is alvo:
            self.mode.target = destino
        self._alarme_nivelado(
            "shed",
            kind=KIND_LOOP_SHED,
            message=f"Fonte remota degradada: rebaixado para '{MODE_NAMES[destino]}'",
            payload={
                "block_id": self.block_id,
                "target": MODE_NAMES[alvo],
                "actual": MODE_NAMES[destino],
                "shed_opt": self.cfg.shed_opt,
            },
        )
        return destino

    def _resolve_sp(self, m: Mode, inputs: Mapping[str, PortSample], dt: float) -> float:
        cfg = self.cfg
        remoto = {Mode.CAS: "cas_in", Mode.RCAS: "rcas_in"}.get(m)
        if remoto is not None:
            fonte = inputs.get(remoto)
            if fonte is not None and fonte.v is not None:
                return clamp(float(fonte.v), cfg.sp_lo_lim, cfg.sp_hi_lim)
            return self.sp
        if m is Mode.AUTO:
            alvo = clamp(self.sp_op, cfg.sp_lo_lim, cfg.sp_hi_lim)
            subida = alvo - self.sp
            if cfg.sp_rate_up is not None and subida > cfg.sp_rate_up * dt:
                return self.sp + cfg.sp_rate_up * dt
            if cfg.sp_rate_dn is not None and -subida > cfg.sp_rate_dn * dt:
                return self.sp - cfg.sp_rate_dn * dt
            return alvo
        if cfg.sp_pv_track_in_man and self.pv is not None:
            rastreado = clamp(self.pv, cfg.sp_lo_lim, cfg.sp_hi_lim)
            self.sp_op = rastreado
            return rastreado
        return self.sp

    def _entrar_em_man_inicializa_man_out(self, m: Mode) -> None:
        if m is Mode.MAN and self._prev_actual is not Mode.MAN:
            self.man_out = self.u  # transicao para MAN nunca salta (ADR-039 secao 4.4)

    def _forced_output(self, m: Mode, inputs: Mapping[str, PortSample]) -> float | None:
        cfg = self.cfg
        trk = inputs.get("trk_in_d")
        rastreando = trk is not None and bool(trk.v) and trk.ok
        if m is Mode.OOS:
            return self.u
        if m is Mode.IMAN:
            bk = inputs.get("bkcal_in")
            if bk is not None and bk.v is not None:
                return unscale_pct(float(bk.v), cfg.out_scale_lo, cfg.out_scale_hi)
            return self.u
        if m is Mode.LO:
            return cfg.lo_val
        if m is Mode.MAN:
            if rastreando and cfg.track_in_manual:
                return cfg.trk_val
            return self.man_out
        if m is Mode.ROUT:
            ro = inputs.get("rout_in")
            if ro is not None and ro.v is not None:
                return unscale_pct(float(ro.v), cfg.out_scale_lo, cfg.out_scale_hi)
            return self.u
        if rastreando and cfg.track_enable:
            return cfg.trk_val
        return None

    def _resolve_bias(self, sample: PortSample | None) -> float:
        cfg = self.cfg
        if not cfg.ff_enable or sample is None or sample.v is None:
            return self._bias
        sinal = as_signal(sample)
        if not sinal.is_good or not math.isfinite(float(sinal.v)):
            return self._bias  # BAD: mantem o ultimo bom (ADR-039 D10)
        pct = unscale_pct(float(sinal.v), cfg.ff_scale_lo, cfg.ff_scale_hi)
        self._bias = cfg.ff_gain * pct
        return self._bias

    def _rate_limit(self, u: float, dt: float) -> float:
        cfg = self.cfg
        delta = u - self.u_prev
        if cfg.out_rate_up is not None and delta > cfg.out_rate_up * dt:
            return self.u_prev + cfg.out_rate_up * dt
        if cfg.out_rate_dn is not None and -delta > cfg.out_rate_dn * dt:
            return self.u_prev - cfg.out_rate_dn * dt
        return u

    # -- emissao -------------------------------------------------------------
    async def _finish(self, inputs: Mapping[str, PortSample]) -> dict[str, PortSample]:
        m = self.mode.actual
        if m is not self._prev_actual:
            self._defer_event(
                kind=KIND_LOOP_MODE_CHANGED,
                severity="info",
                message=f"Modo: {MODE_NAMES[self._prev_actual]} -> {MODE_NAMES[m]}",
                payload={
                    "block_id": self.block_id,
                    "from": MODE_NAMES[self._prev_actual],
                    "to": MODE_NAMES[m],
                },
            )
            self._prev_actual = m
        # Fecha a contabilidade de alarmes de nivel com a varredura: o que foi observado
        # agora vira `_prev` (suprime a repeticao no proximo scan) e o conjunto reciclado
        # entra vazio no scan seguinte, entao condicao nao observada = episodio encerrado.
        self._alarmes_prev, self._alarmes = self._alarmes, self._alarmes_prev
        self._alarmes.clear()
        await self._flush_events()
        if self._publish_state is not None:
            agora = time.monotonic()
            if agora - self._last_publish >= LOOP_STATE_MIN_INTERVAL_S:
                self._last_publish = agora
                await self._publish_state(self._loop_state())
        return self._emit()

    def _alarme_nivelado(
        self, code: str, *, kind: str, message: str, payload: dict[str, Any]
    ) -> None:
        """Alarme de NIVEL: registra a condicao neste scan, emite so na borda de subida."""
        self._alarmes.add(code)
        if code in self._alarmes_prev:
            return
        self._defer_event(kind=kind, severity="warning", message=message, payload=payload)

    def _emit(self) -> dict[str, PortSample]:
        cfg, m = self.cfg, self.mode.actual
        hi = self.u >= cfg.out_hi_lim
        lo = self.u <= cfg.out_lo_lim
        out = make_signal(
            scale_pct(self.u, cfg.out_scale_lo, cfg.out_scale_hi),
            Quality.BAD if m is Mode.OOS else Quality.GOOD,
            substatus=Substatus.LOCAL_OVERRIDE if m is Mode.LO else Substatus.NON_SPECIFIC,
            hi_limited=hi,
            lo_limited=lo,
        )
        d = cfg.direct_acting
        valor_bkcal = self.pv if (cfg.use_pv_for_bkcal and self.pv is not None) else self.sp
        bkcal = make_signal(
            valor_bkcal,
            Quality.GOOD,
            substatus=Substatus.NON_SPECIFIC if m is Mode.CAS else Substatus.INIT_REQUEST,
            hi_limited=lo if d else hi,
            lo_limited=hi if d else lo,
        )
        return {"out": out, "bkcal_out": bkcal}

    def _loop_state(self) -> LoopState:
        cfg = self.cfg
        return LoopState(
            ts=datetime.now(UTC),
            target=MODE_NAMES[self.mode.target],
            actual=MODE_NAMES[self.mode.actual],
            permitted=[MODE_NAMES[m] for m in Mode if m & cfg.permitted],
            pv=self.pv,
            pv_ok=self.pv_ok,
            sp=self.sp,
            out=scale_pct(self.u, cfg.out_scale_lo, cfg.out_scale_hi),
            u_pct=self.u,
            man_out=self.man_out,
            hi_limited=self.u >= cfg.out_hi_lim,
            lo_limited=self.u <= cfg.out_lo_lim,
            diag=dict(self.diag),
        )

    def _defer_event(self, **kwargs: Any) -> None:
        self._pendentes.append(kwargs)

    async def _flush_events(self) -> None:
        pendentes, self._pendentes = self._pendentes, []
        if self._emit_event is None:
            return
        for evento in pendentes:
            await self._emit_event(origin=f"bloco:{self.block_id}", **evento)
