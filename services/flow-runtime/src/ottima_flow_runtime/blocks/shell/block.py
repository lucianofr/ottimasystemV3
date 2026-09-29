"""BlockShell: a maquina de modos FF que envolve um ControlKernel (ADR-039).

Nenhum `if` deste arquivo testa uma TRANSICAO especifica de modo — as transicoes emergem
da resolucao por prioridade (secao 4.3) e da tabela de saida forcada (secao 4.4). Um `if`
de transicao aqui e defeito de projeto (ADR-039 secao 4.7).

v2 multicanal (fuzzy_loop MIMO, SPEC_FUZZY §3.2 v2): `n_channels` canais de controle
compartilham a maquina de modos, os limites e o kernel (`MultiControlKernel` — um unico
`process()` do motor por varredura, porque as regras cruzam canais). Por canal: PV
filtrado, SP operacional, integrador com anti-windup, limitador de taxa e saida manual.
O bloco SISO (`pid_loop`, e o proprio `fuzzy_loop` com n_loops=1 no kernel) mantem o
comportamento e a API originais — os atributos de estado (`u`, `pv`, `sp`, `sp_op`,
`man_out`, ...) sao vistas do canal 0.

Portas: SISO classico usa `in`/`out`/`bkcal_out` + portas remotas; `channel_ports=True`
(fuzzy_loop v2) usa `pv_1..pv_n`/`out_1..out_n` e NAO tem portas remotas/cascata — a
config restringe permitted a {oos, man, auto} e os ramos CAS/RCAS/ROUT/IMAN/LO ficam
naturalmente inalcancaveis (inputs ausentes).
"""

import math
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ottima_core.bus import LoopState
from ottima_flow_runtime.blocks.base import Block, PortSample
from ottima_flow_runtime.blocks.shell.config import ShellCfg, clamp, scale_pct, unscale_pct
from ottima_flow_runtime.blocks.shell.kernel import ControlKernel, MultiControlKernel
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
# (campo, valor, canal) — o upsert de `loop_setpoints` e por (flow, block, channel).
PersistOp = Callable[..., Awaitable[None]]

_SHED_DESTINO = {"shed_to_auto": Mode.AUTO, "shed_to_man": Mode.MAN}


@dataclass(frozen=True, slots=True)
class CarriedState:
    """Estado carregado de uma instancia anterior no hot-swap estrutural (ADR-039 D11).

    `canais` traz (u, sp_op, man_out) por canal; vazio = o trio SISO (`u`, `sp_op`,
    `man_out`) vale para o canal 0 (compatibilidade com carry de bloco SISO).
    """

    u: float
    sp_op: float
    man_out: float
    was_calculating: bool
    canais: tuple[tuple[float, float, float], ...] = ()


@dataclass(slots=True)
class _Canal:
    """Estado de controle de um canal (bloco SISO tem exatamente um)."""

    pv: float | None
    pv_ok: bool
    sp: float
    sp_op: float
    man_out: float
    u: float
    u_int: float
    u_prev: float
    bias: float


def _seeds(valor: float | Sequence[float | None] | None, n: int) -> list[float | None]:
    """Normaliza semente escalar/lista para `n` canais (None = sem semente)."""
    if valor is None:
        return [None] * n
    if isinstance(valor, (float, int)):
        return [float(valor)] + [None] * (n - 1)
    lista: list[float | None] = [None if v is None else float(v) for v in valor]
    if len(lista) < n:
        lista.extend([None] * (n - len(lista)))
    return lista[:n]


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
        sp_seed: float | Sequence[float | None] | None = None,
        man_out_seed: float | Sequence[float | None] | None = None,
        carry: CarriedState | None = None,
        n_channels: int = 1,
        channel_ports: bool = False,
    ) -> None:
        super().__init__(block_id)
        if n_channels < 1:
            raise ValueError(f"n_channels precisa ser >= 1: {n_channels}")
        self.kernel = kernel
        self.cfg = cfg
        self._multi = isinstance(kernel, MultiControlKernel)
        if n_channels > 1 and not self._multi:
            raise ValueError("kernel nao e multicanal (MultiControlKernel) para n_channels > 1")
        self.n_channels = n_channels if self._multi else 1
        self._channel_ports = channel_ports
        self._emit_event = emit_event
        self._publish_state = publish_state
        self._persist_op = persist_op

        self.mode = ModeBlock(permitted=cfg.permitted, normal=cfg.normal)
        self.diag: dict[str, float] = {}
        self.diag_channels: list[dict[str, float]] = [dict() for _ in range(self.n_channels)]
        self._ts_prev: datetime | None = None
        self._prev_actual = Mode.OOS
        self._rebase_bias = False
        self._pendentes: list[dict[str, Any]] = []
        # Alarmes de NIVEL (ADR-039: evento por transicao, nao por scan). O rearme e por
        # scan: `_finish` — funil unico de todos os returns de `step` — promove as condicoes
        # observadas nesta varredura a `_prev`, entao um scan que NAO observa a condicao
        # encerra o episodio. Latch por flag exigiria um clear em cada rota que pula a
        # avaliacao, e as que faltavam (saida forcada e dt invalido, ambas sem `compute()`)
        # silenciavam `kernel_invalid_output` para sempre. Dois conjuntos reusados: a troca
        # e por referencia, sem alocar por varredura.
        self._alarmes: set[str] = set()
        self._alarmes_prev: set[str] = set()
        self._last_publish = 0.0

        seeds_sp = _seeds(sp_seed, self.n_channels)
        seeds_man = _seeds(man_out_seed, self.n_channels)
        canais: list[_Canal] = []
        for i in range(self.n_channels):
            carregado: tuple[float, float, float] | None = None
            if carry is not None:
                if i < len(carry.canais):
                    carregado = carry.canais[i]
                elif i == 0 and not carry.canais:
                    carregado = (carry.u, carry.sp_op, carry.man_out)
            if carregado is not None:
                u0 = clamp(carregado[0], cfg.out_lo_lim, cfg.out_hi_lim)
                sp0 = clamp(carregado[1], cfg.sp_lo_lim, cfg.sp_hi_lim)
                man0 = clamp(carregado[2], cfg.out_lo_lim, cfg.out_hi_lim)
            else:
                u0 = clamp(cfg.out_startup, cfg.out_lo_lim, cfg.out_hi_lim)
                seed_sp = seeds_sp[i]
                sp0 = clamp(
                    seed_sp if seed_sp is not None else cfg.sp_lo_lim,
                    cfg.sp_lo_lim,
                    cfg.sp_hi_lim,
                )
                seed_man = seeds_man[i]
                man0 = clamp(
                    seed_man if seed_man is not None else u0, cfg.out_lo_lim, cfg.out_hi_lim
                )
            canais.append(
                _Canal(
                    pv=None,
                    pv_ok=False,
                    sp=sp0,
                    sp_op=sp0,
                    man_out=man0,
                    u=u0,
                    u_int=u0,
                    u_prev=u0,
                    bias=0.0,
                )
            )
        self._canais = canais
        if carry is not None and carry.was_calculating:
            self._defer_event(
                kind=KIND_LOOP_ALARM,
                severity="warning",
                message="Config estrutural trocada com a malha calculante: aterrissagem em MAN",
                payload={"block_id": block_id, "code": "structural_swap_landed_man"},
            )

    # -- vistas SISO (canal 0) — API historica dos testes e do hot-swap ---------
    @property
    def _c0(self) -> _Canal:
        return self._canais[0]

    @property
    def pv(self) -> float | None:
        return self._c0.pv

    @pv.setter
    def pv(self, valor: float | None) -> None:
        self._c0.pv = valor

    @property
    def pv_ok(self) -> bool:
        return self._c0.pv_ok

    @pv_ok.setter
    def pv_ok(self, valor: bool) -> None:
        self._c0.pv_ok = valor

    @property
    def sp(self) -> float:
        return self._c0.sp

    @sp.setter
    def sp(self, valor: float) -> None:
        self._c0.sp = valor

    @property
    def sp_op(self) -> float:
        return self._c0.sp_op

    @sp_op.setter
    def sp_op(self, valor: float) -> None:
        self._c0.sp_op = valor

    @property
    def man_out(self) -> float:
        return self._c0.man_out

    @man_out.setter
    def man_out(self, valor: float) -> None:
        self._c0.man_out = valor

    @property
    def u(self) -> float:
        return self._c0.u

    @u.setter
    def u(self, valor: float) -> None:
        self._c0.u = valor

    @property
    def u_int(self) -> float:
        return self._c0.u_int

    @u_int.setter
    def u_int(self, valor: float) -> None:
        self._c0.u_int = valor

    @property
    def u_prev(self) -> float:
        return self._c0.u_prev

    @u_prev.setter
    def u_prev(self, valor: float) -> None:
        self._c0.u_prev = valor

    # -- portas -------------------------------------------------------------
    @property
    def input_ports(self) -> tuple[str, ...]:
        if self._channel_ports:
            return tuple(f"pv_{i + 1}" for i in range(self.n_channels))
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
        if self._channel_ports:
            return tuple(f"out_{i + 1}" for i in range(self.n_channels))
        return ("out", "bkcal_out")

    def _porta_pv(self, i: int) -> str:
        return f"pv_{i + 1}" if self._channel_ports else "in"

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

    def write_sp(self, value: float, channel: int = 0) -> None:
        if not 0 <= channel < self.n_channels:
            return
        self._canais[channel].sp_op = clamp(value, self.cfg.sp_lo_lim, self.cfg.sp_hi_lim)

    def write_out(self, value: float, channel: int = 0) -> None:
        if not 0 <= channel < self.n_channels:
            return
        self._canais[channel].man_out = clamp(value, self.cfg.out_lo_lim, self.cfg.out_hi_lim)

    def _canal_do_comando(self, args: dict[str, Any]) -> int:
        try:
            canal = int(args.get("channel", 0))
        except (TypeError, ValueError):
            return -1
        return canal if 0 <= canal < self.n_channels else -1

    async def command(self, cmd: str, args: dict[str, Any], user: str | None) -> None:
        """Comandos de operacao (RNF-05): a API publica, o runtime materializa e audita."""
        if cmd == "loop_mode":
            alvo = mode_from_name(str(args["target"]))
            if self.write_target(alvo):
                await self._audit("loop_target_written", user, {"target": args["target"]})
                if self._persist_op is not None:
                    await self._persist_op("target", str(args["target"]), 0)
        elif cmd == "loop_sp":
            canal = self._canal_do_comando(args)
            if canal < 0:
                return  # canal fora do bloco: comando ignorado (defesa do runtime)
            self.write_sp(float(args["value"]), canal)
            await self._audit(
                "loop_sp_written", user, {"value": self._canais[canal].sp_op, "channel": canal}
            )
            if self._persist_op is not None:
                await self._persist_op("sp", self._canais[canal].sp_op, canal)
        elif cmd == "loop_out":
            canal = self._canal_do_comando(args)
            if canal < 0:
                return
            self.write_out(float(args["value"]), canal)
            await self._audit(
                "loop_out_written",
                user,
                {"value": self._canais[canal].man_out, "channel": canal},
            )
            if self._persist_op is not None:
                await self._persist_op("man_out", self._canais[canal].man_out, canal)

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
        c0 = self._c0
        return CarriedState(
            u=c0.u,
            sp_op=c0.sp_op,
            man_out=c0.man_out,
            was_calculating=self.mode.actual in CALCULATING_MODES,
            canais=tuple((c.u, c.sp_op, c.man_out) for c in self._canais),
        )

    # -- ciclo ---------------------------------------------------------------
    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        dt = self._measure_dt(ts)
        for i in range(self.n_channels):
            self._update_pv(i, inputs.get(self._porta_pv(i)), dt)
        pv_ks = [c.pv if c.pv is not None else c.sp for c in self._canais]
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
                for c in self._canais:
                    c.sp = clamp(c.sp_op, self.cfg.sp_lo_lim, self.cfg.sp_hi_lim)
                self._entrar_em_man_inicializa_man_out(m)
                forced = self._forced_outputs(m, inputs)
                for i, c in enumerate(self._canais):
                    if forced[i] is not None:
                        c.u = clamp(forced[i], self.cfg.out_lo_lim, self.cfg.out_hi_lim)
                        c.u_int = c.u - c.bias
                        c.u_prev = c.u
            self._alinhar(pv_ks)
            return await self._finish(inputs)

        self.mode.actual = self._resolve_mode(inputs, kernel_errors)
        m = self.mode.actual
        for i, c in enumerate(self._canais):
            c.sp = self._resolve_sp(i, m, inputs, dt)
        bias_amostra = None if self._channel_ports else inputs.get("bias_in")
        biases = [self._resolve_bias(i, bias_amostra) for i in range(self.n_channels)]
        if self._rebase_bias:
            for i, c in enumerate(self._canais):
                c.u_int = c.u - biases[i]
            self._rebase_bias = False

        self._entrar_em_man_inicializa_man_out(m)
        forced = self._forced_outputs(m, inputs)
        if any(f is not None for f in forced):
            for i, c in enumerate(self._canais):
                if forced[i] is not None:
                    c.u = clamp(forced[i], self.cfg.out_lo_lim, self.cfg.out_hi_lim)
                    c.u_int = c.u - biases[i]
                    c.u_prev = c.u
            self._alinhar(pv_ks)
            return await self._finish(inputs)

        sps = [c.sp for c in self._canais]
        if self._multi:
            multi = self.kernel  # type: ignore[assignment]
            dus = multi.compute_all(sps, pv_ks, dt)
        else:
            dus = [self.kernel.compute(sps[0], pv_ks[0], dt)]
        # Diagnostico do kernel (SPEC_FUZZY secao 8) copiado ANTES do portao de finitude:
        # num scan sem regra o ponto de operacao corrente e exatamente o que o
        # comissionador procura no heatmap — publicar o ultimo ponto COBERTO marcaria a
        # celula errada justamente durante o alarme. O kernel garante diag finito (e omite
        # `du_n` quando nao houve saida), entao o quadro segue valido para o recorder.
        self._copiar_diag()
        if any(not math.isfinite(du) for du in dus):
            self._alarme_nivelado(
                "kernel_invalid_output",
                kind=KIND_LOOP_ALARM,
                message="Kernel devolveu resultado invalido; OUT mantido",
                payload={"block_id": self.block_id, "code": "kernel_invalid_output"},
            )
            self._alinhar(pv_ks)
            return await self._finish(inputs)
        for i, c in enumerate(self._canais):
            u = self._rate_limit(i, c.u_int + dus[i] * dt + biases[i], dt)
            c.u = clamp(u, self.cfg.out_lo_lim, self.cfg.out_hi_lim)
            c.u_int = c.u - biases[i]
            c.u_prev = c.u
        return await self._finish(inputs)

    def _alinhar(self, pv_ks: Sequence[float]) -> None:
        us = [c.u for c in self._canais]
        sps = [c.sp for c in self._canais]
        if self._multi:
            multi = self.kernel  # type: ignore[assignment]
            multi.align_all(us, sps, pv_ks)
        else:
            self.kernel.align(us[0], sps[0], pv_ks[0])

    def _copiar_diag(self) -> None:
        diags = getattr(self.kernel, "diag_channels", None)
        if diags:
            for i in range(min(self.n_channels, len(diags))):
                self.diag_channels[i] = dict(diags[i])
        else:
            kernel_diag = getattr(self.kernel, "diag", None)
            if kernel_diag:
                self.diag_channels[0] = dict(kernel_diag)
        self.diag = self.diag_channels[0]

    # -- pedacos ---------------------------------------------------------------
    def _measure_dt(self, ts: datetime | None) -> float | None:
        if ts is None:
            return None
        prev, self._ts_prev = self._ts_prev, ts
        if prev is None:
            return None
        return (ts - prev).total_seconds()

    def _update_pv(self, canal: int, sample: PortSample | None, dt: float | None) -> None:
        c = self._canais[canal]
        if sample is None or sample.v is None:
            c.pv_ok = False
            return
        v = float(sample.v)
        if not math.isfinite(v):
            c.pv_ok = False
            return
        c.pv_ok = as_signal(sample).is_good
        if c.pv is None or self.cfg.pv_ftime <= 0.0 or dt is None or dt <= 0.0:
            c.pv = v
            return
        a = dt / (self.cfg.pv_ftime + dt)
        c.pv = c.pv + a * (v - c.pv)

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
        # Multicanal: PV sem qualidade em QUALQUER canal tira o bloco do modo calculante —
        # o motor de inferencia e compartilhado, e canal cego nao tem erro confiavel.
        if not all(c.pv_ok for c in self._canais) and efetivo in CALCULATING_MODES:
            return Mode.MAN
        for modo, porta in ((Mode.CAS, "cas_in"), (Mode.RCAS, "rcas_in"), (Mode.ROUT, "rout_in")):
            if efetivo is modo:
                fonte = inputs.get(porta)
                if fonte is None or fonte.v is None or not as_signal(fonte).is_good:
                    return self._shed(modo)
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

    def _resolve_sp(
        self, canal: int, m: Mode, inputs: Mapping[str, PortSample], dt: float
    ) -> float:
        cfg = self.cfg
        c = self._canais[canal]
        remoto = {Mode.CAS: "cas_in", Mode.RCAS: "rcas_in"}.get(m)
        if remoto is not None:
            fonte = inputs.get(remoto)
            if fonte is not None and fonte.v is not None:
                return clamp(float(fonte.v), cfg.sp_lo_lim, cfg.sp_hi_lim)
            return c.sp
        if m is Mode.AUTO:
            alvo = clamp(c.sp_op, cfg.sp_lo_lim, cfg.sp_hi_lim)
            subida = alvo - c.sp
            if cfg.sp_rate_up is not None and subida > cfg.sp_rate_up * dt:
                return c.sp + cfg.sp_rate_up * dt
            if cfg.sp_rate_dn is not None and -subida > cfg.sp_rate_dn * dt:
                return c.sp - cfg.sp_rate_dn * dt
            return alvo
        if cfg.sp_pv_track_in_man and c.pv is not None:
            rastreado = clamp(c.pv, cfg.sp_lo_lim, cfg.sp_hi_lim)
            c.sp_op = rastreado
            return rastreado
        return c.sp

    def _entrar_em_man_inicializa_man_out(self, m: Mode) -> None:
        if m is Mode.MAN and self._prev_actual is not Mode.MAN:
            for c in self._canais:
                c.man_out = c.u  # transicao para MAN nunca salta (ADR-039 secao 4.4)

    def _forced_outputs(self, m: Mode, inputs: Mapping[str, PortSample]) -> list[float | None]:
        cfg = self.cfg
        trk = None if self._channel_ports else inputs.get("trk_in_d")
        rastreando = trk is not None and bool(trk.v) and trk.ok
        if m is Mode.OOS:
            return [c.u for c in self._canais]
        if m is Mode.IMAN:
            bk = inputs.get("bkcal_in")
            if bk is not None and bk.v is not None:
                valor = unscale_pct(float(bk.v), cfg.out_scale_lo, cfg.out_scale_hi)
                return [valor] * self.n_channels
            return [c.u for c in self._canais]
        if m is Mode.LO:
            return [cfg.lo_val] * self.n_channels
        if m is Mode.MAN:
            if rastreando and cfg.track_in_manual:
                return [cfg.trk_val] * self.n_channels
            return [c.man_out for c in self._canais]
        if m is Mode.ROUT:
            ro = inputs.get("rout_in")
            if ro is not None and ro.v is not None:
                valor = unscale_pct(float(ro.v), cfg.out_scale_lo, cfg.out_scale_hi)
                return [valor] * self.n_channels
            return [c.u for c in self._canais]
        if rastreando and cfg.track_enable:
            return [cfg.trk_val] * self.n_channels
        return [None] * self.n_channels

    def _resolve_bias(self, canal: int, sample: PortSample | None) -> float:
        cfg = self.cfg
        c = self._canais[canal]
        if not cfg.ff_enable or sample is None or sample.v is None:
            return c.bias
        sinal = as_signal(sample)
        if not sinal.is_good or not math.isfinite(float(sinal.v)):
            return c.bias  # BAD: mantem o ultimo bom (ADR-039 D10)
        pct = unscale_pct(float(sinal.v), cfg.ff_scale_lo, cfg.ff_scale_hi)
        c.bias = cfg.ff_gain * pct
        return c.bias

    def _rate_limit(self, canal: int, u: float, dt: float) -> float:
        cfg = self.cfg
        delta = u - self._canais[canal].u_prev
        if cfg.out_rate_up is not None and delta > cfg.out_rate_up * dt:
            return self._canais[canal].u_prev + cfg.out_rate_up * dt
        if cfg.out_rate_dn is not None and -delta > cfg.out_rate_dn * dt:
            return self._canais[canal].u_prev - cfg.out_rate_dn * dt
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
                # Um LoopState por canal, no mesmo canal Redis: o consumidor demultiplexa
                # pelo campo `channel` (payload retrocompativel — SISO publica channel=0).
                for i in range(self.n_channels):
                    await self._publish_state(self._loop_state(i))
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
        if self._channel_ports:
            return {f"out_{i + 1}": self._sinal_out(i) for i in range(self.n_channels)}
        c = self._c0
        hi = c.u >= cfg.out_hi_lim
        lo = c.u <= cfg.out_lo_lim
        out = self._sinal_out(0)
        d = cfg.direct_acting
        valor_bkcal = c.pv if (cfg.use_pv_for_bkcal and c.pv is not None) else c.sp
        bkcal = make_signal(
            valor_bkcal,
            Quality.GOOD,
            substatus=Substatus.NON_SPECIFIC if m is Mode.CAS else Substatus.INIT_REQUEST,
            hi_limited=lo if d else hi,
            lo_limited=hi if d else lo,
        )
        return {"out": out, "bkcal_out": bkcal}

    def _sinal_out(self, canal: int) -> Any:
        cfg, m = self.cfg, self.mode.actual
        c = self._canais[canal]
        return make_signal(
            scale_pct(c.u, cfg.out_scale_lo, cfg.out_scale_hi),
            Quality.BAD if m is Mode.OOS else Quality.GOOD,
            substatus=Substatus.LOCAL_OVERRIDE if m is Mode.LO else Substatus.NON_SPECIFIC,
            hi_limited=c.u >= cfg.out_hi_lim,
            lo_limited=c.u <= cfg.out_lo_lim,
        )

    def _loop_state(self, canal: int = 0) -> LoopState:
        cfg = self.cfg
        c = self._canais[canal]
        return LoopState(
            ts=datetime.now(UTC),
            target=MODE_NAMES[self.mode.target],
            actual=MODE_NAMES[self.mode.actual],
            permitted=[MODE_NAMES[m] for m in Mode if m & cfg.permitted],
            pv=c.pv,
            pv_ok=c.pv_ok,
            sp=c.sp,
            out=scale_pct(c.u, cfg.out_scale_lo, cfg.out_scale_hi),
            u_pct=c.u,
            man_out=c.man_out,
            hi_limited=c.u >= cfg.out_hi_lim,
            lo_limited=c.u <= cfg.out_lo_lim,
            diag=dict(self.diag_channels[canal]),
            channel=canal,
        )

    def _defer_event(self, **kwargs: Any) -> None:
        self._pendentes.append(kwargs)

    async def _flush_events(self) -> None:
        pendentes, self._pendentes = self._pendentes, []
        if self._emit_event is None:
            return
        for evento in pendentes:
            await self._emit_event(origin=f"bloco:{self.block_id}", **evento)
