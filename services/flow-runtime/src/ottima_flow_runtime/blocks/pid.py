"""Bloco PID: controle proporcional-integral-derivativo via `simple-pid` (RF-551..553, ADR-031).

A config do bloco é na forma ISA (a que o instrumentista lê num controlador de painel):

    saida = Kc * [ e + (1/Ti) * integral(e dt) + Td * de/dt ]

`simple-pid` trabalha na forma paralela (Kp, Ki, Kd independentes). A conversão acontece
UMA VEZ, na construção:

    Kp = Kc
    Ki = Kc / Ti  (Ti > 0), senão 0.0 -- Ti=0 é a convenção documentada para integral
                                          DESLIGADA (evita divisão por zero e permite
                                          controle P/PD puro)
    Kd = Kc * Td

`dt` é SEMPRE o Ts nominal do flow, passado explicitamente em `self._pid(pv, dt=ts)`, com
`sample_time=None` na construção. Não é o relógio de parede, por três motivos:
  - em overrun o scheduler PULA fronteiras de grade sem compensação (`scheduler.py:240-286`)
    -- nenhum bloco de dinâmica mede o tempo decorrido de verdade, TFS/`first_order`/`lag.py`
    embutem um Ts constante;
  - um `dt` de relógio de parede deixaria o termo D ruidoso a cada varredura;
  - o scheduler é a ÚNICA autoridade de tempo do laço (ADR-031).

`sample_time`, `error_map` e `time_fn` do `simple-pid` NÃO são expostos, por decisão do gate:
o primeiro porque o próprio scheduler já governa o cadenciamento (um valor acima de Ts faria
o PID devolver silenciosamente uma saída velha); os outros dois são callables Python, não
serializáveis em JSON de config.

**Entrada não-finita nunca alcança o controlador.** `_integral += Ki*nan*dt` envenenaria a
integral para sempre -- a saída ficaria `nan` mesmo depois do sinal se recuperar. Por isso
uma amostra de PV ou SP não-finita nunca chega a `self._pid(...)`: o passo retém a última
saída boa com `ok=False` (mesma disciplina do bloco Fuzzy, ADR-029).
"""

import logging
import math
from collections.abc import Mapping
from datetime import datetime

from simple_pid import PID

from .base import Block, PortSample, has_cold_input, null_outputs

logger = logging.getLogger(__name__)

INPUT_PORTS = ("pv", "sp")
OUTPUT_PORTS = ("out",)


class PidBlock(Block):
    """PID ISA sobre `simple_pid.PID`, uma instância própria por bloco.

    `pv` é obrigatória; `sp` é opcional (RF-552) -- quando conectada, sobrepõe
    `config.setpoint` a cada varredura, ausente usa o valor fixo da config.
    """

    def __init__(
        self,
        block_id: str,
        *,
        kc: float,
        ti_seconds: float,
        td_seconds: float,
        setpoint: float,
        output_min: float | None,
        output_max: float | None,
        auto_mode: bool,
        proportional_on_measurement: bool,
        differential_on_measurement: bool,
        starting_output: float,
        ts_seconds: float,
    ) -> None:
        super().__init__(block_id)
        self._kc = float(kc)
        self._ti_seconds = float(ti_seconds)
        self._td_seconds = float(td_seconds)
        self._setpoint = float(setpoint)
        self._output_min = None if output_min is None else float(output_min)
        self._output_max = None if output_max is None else float(output_max)
        self._auto_mode = bool(auto_mode)
        self._proportional_on_measurement = bool(proportional_on_measurement)
        self._differential_on_measurement = bool(differential_on_measurement)
        self._starting_output = float(starting_output)
        # `Flow.ts_seconds` é Numeric(4,1) e chega como Decimal do SQLAlchemy: converte
        # uma vez na fronteira, mesmo cuidado do TfsBlock/FirstOrderBlock.
        self._ts_seconds = float(ts_seconds)

        # Conversão ISA -> paralela, uma vez só (ver docstring do módulo).
        self._kp = self._kc
        self._ki = self._kc / self._ti_seconds if self._ti_seconds > 0 else 0.0
        self._kd = self._kc * self._td_seconds

        self._pid = self._build()
        self._last: float | None = None

    def _build(self) -> PID:
        return PID(
            Kp=self._kp,
            Ki=self._ki,
            Kd=self._kd,
            setpoint=self._setpoint,
            sample_time=None,
            output_limits=(self._output_min, self._output_max),
            auto_mode=self._auto_mode,
            proportional_on_measurement=self._proportional_on_measurement,
            differential_on_measurement=self._differential_on_measurement,
            starting_output=self._starting_output,
        )

    @property
    def input_ports(self) -> tuple[str, ...]:
        return INPUT_PORTS

    @property
    def output_ports(self) -> tuple[str, ...]:
        return OUTPUT_PORTS

    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        if has_cold_input(inputs):
            return null_outputs(OUTPUT_PORTS)

        # Amostra inválida executa e propaga a flag (decisão A-6) -- mas só depois do
        # guard de finitude abaixo, que decide se o passo sequer chama o controlador.
        ok_entradas = all(
            sample.ok and math.isfinite(float(sample.v)) for sample in inputs.values()
        )

        pv = float(inputs["pv"].v)
        setpoint = float(inputs["sp"].v) if "sp" in inputs else self._setpoint

        # Entrada não-finita nunca chega ao controlador: `_integral += Ki*nan*dt`
        # envenenaria a integral para sempre, e a saída ficaria `nan` mesmo depois do
        # sinal se recuperar (ver docstring do módulo).
        if not (math.isfinite(pv) and math.isfinite(setpoint)):
            return self._retido()

        self._pid.setpoint = setpoint
        try:
            resultado = self._pid(pv, dt=self._ts_seconds)
        except Exception:
            # Uma exceção do simple-pid nunca sobe: propagar por `step()` derrubaria o
            # flow inteiro pelo handler externo do scheduler (mesma postura do Fuzzy).
            logger.exception(
                "Bloco PID '%s': falha no controlador -- retendo a última saída (ok=False)",
                self.block_id,
            )
            return self._retido()

        # `auto_mode=False` sem cômputo anterior devolve `None` (`_last_output` do
        # simple-pid ainda não setado) -- trata como qualquer outra saída ruim.
        if resultado is None or not math.isfinite(resultado):
            return self._retido()

        self._last = resultado
        return {"out": PortSample(resultado, ok_entradas)}

    def _retido(self) -> dict[str, PortSample]:
        """Saída retida (RF-553): última boa conhecida, sempre `ok=False`."""
        return {"out": PortSample(self._last, False)}

    def reset(self) -> None:
        # Reconstrói em vez de `self._pid.reset()`: `PID.reset()` zera `_integral` mas
        # NÃO restaura `starting_output` -- a biblioteca só aplica esse valor depois do
        # próprio `reset()` interno, dentro de `__init__`. Chamar `reset()` direto
        # descartaria em silêncio a semente bumpless a cada deploy/stop.
        self._pid = self._build()
        self._last = None
