"""Bloco Fuzzy: motor de inferência definido pelo usuário via FLL (RF-541..543, ADR-029).

`fll` (FuzzyLite Language) chega já validado por conteúdo em `validate_graph` — o mesmo
texto que passou lá é o que `FllImporter().from_string` monta aqui (§4.1-3: a instância
nasce e reprocessa a mesma verificação de forma isolada do ciclo de vida do deploy). IN1..INn
e OUT1..OUTn são numéricas e mapeiam POSICIONALMENTE para `engine.input_variables`/
`engine.output_variables`, na ordem de declaração do FLL — não pelo nome da variável fuzzy.

**Saída não-finita não é erro do bloco.** Um `OutputVariable` com `default: nan` e termos sem
cobertura total do domínio de entrada produz `nan` de propósito fora da cobertura das funções
de pertinência — a semântica (RF-542) é reter, POR PORTA, o último valor finito computado
(`ok=False`), nunca deixar `nan` escapar com `ok=True`. Falha em `engine.process()` (exceção
da biblioteca) é tratada à parte: mantém TODAS as saídas do passo anterior, `ok=False` nas
duas.

`lock-previous: true`/`default: nan` do FLL são resolvidos pela própria `fuzzylite` (estado
interno do `Engine`, não deste bloco) — `reset()` chama `engine.restart()`, que limpa esse
estado junto com as entradas, então a mesma sequência de varreduras depois de um reset nunca
enxerga o valor travado antes dele (RF-543).

`publish` (opcional) publica um `FuzzyState` em `fuzzy.state.<flow_id>.<block_id>` (ADR-030)
após CADA `process()` bem-sucedido — cold input e exceção nunca publicam. Throttle na origem
(`FUZZY_STATE_MIN_INTERVAL_S`) via `time.monotonic()`: a primeira publicação depois da
construção ou de `reset()` sempre passa, as seguintes só depois do intervalo mínimo. Sem
`publish`, o bloco se comporta exatamente como antes desta feature.
"""

import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime

import fuzzylite as fl
import numpy as np

from ottima_core.bus import FuzzyState, FuzzyTermDegree, FuzzyVarState
from ottima_core.signal import Quality

from .base import Block, Signal, has_cold_input, null_outputs

logger = logging.getLogger(__name__)

FUZZY_STATE_MIN_INTERVAL_S = 0.25
"""Throttle mínimo entre publicações de `FuzzyState` por bloco (ADR-030) — a varredura roda
em ms, a UI/recorder não precisam de mais que 4 quadros/s."""


def _grau(x: object) -> float:
    """Sanitiza um grau (μ de termo, ativação de regra, grau agregado de saída): shape
    escalar ou array (1,) da `fuzzylite`/numpy vira float Python; não-finito vira 0.0 —
    nunca nan/inf num canal publicado (RF-542)."""
    valor = float(np.asarray(x).reshape(-1)[-1])
    return valor if math.isfinite(valor) else 0.0


def _valor_crisp(valor: float) -> float | None:
    """Sanitiza um valor crisp: não-finito vira `None` (RF-542, nan/inf nunca trafegam como
    `NaN` no JSON do canal)."""
    return valor if math.isfinite(valor) else None


class FuzzyBlock(Block):
    """IN1..INn / OUT1..OUTn numéricas, contagem fixada na construção (spec do bloco Fuzzy).

    A instância é dona do `Engine` da `fuzzylite`: sem pool, sem processo separado — o
    cômputo de um FLL típico é sub-milissegundo, então roda inline no laço de varredura
    (mesma classe de decisão do TFS/Filtro, ao contrário do Script, que paga IPC de
    propósito pelo isolamento de sandbox, ADR-018).
    """

    def __init__(
        self,
        block_id: str,
        *,
        fll: str,
        n_inputs: int,
        n_outputs: int,
        setpoint: float | None = None,
        sp_da_entrada: bool = False,
        publish: Callable[[FuzzyState], Awaitable[None]] | None = None,
        state_min_interval_s: float = FUZZY_STATE_MIN_INTERVAL_S,
    ) -> None:
        super().__init__(block_id)
        self._publish = publish
        self._state_min_interval_s = state_min_interval_s
        self._last_publish_mono: float | None = None
        #: SP do operador (RF-541 revisado). Não-nulo: o FLL declara uma variável de entrada a
        #: MAIS, a última, alimentada com este valor — e ele é o único estado que o comando
        #: `fuzzy_sp` muda em runtime (o resto da config é do grafo).
        self.setpoint = setpoint
        #: Fonte do SP pela porta `sp` (fio do flow, ex.: `opc_read`): a última variável do FLL
        #: passa a ser alimentada pelo valor da porta, e o comando do operador não vale.
        self._sp_da_entrada = sp_da_entrada
        where = f"bloco '{block_id}' (fuzzy)"
        self._input_ports = tuple(f"IN{i}" for i in range(1, n_inputs + 1)) + (
            ("sp",) if sp_da_entrada else ()
        )
        self._output_ports = tuple(f"OUT{i}" for i in range(1, n_outputs + 1))

        try:
            engine = fl.FllImporter().from_string(fll)
        except Exception as erro:
            raise ValueError(f"{where}: FLL inválido — {erro}") from erro

        n_esperado = n_inputs + (1 if (setpoint is not None or sp_da_entrada) else 0)
        if len(engine.input_variables) != n_esperado:
            raise ValueError(
                f"{where}: FLL declara {len(engine.input_variables)} variável(is) de "
                f"entrada; a config espera n_inputs={n_esperado}"
            )
        if len(engine.output_variables) != n_outputs:
            raise ValueError(
                f"{where}: FLL declara {len(engine.output_variables)} variável(is) de "
                f"saída; a config espera n_outputs={n_outputs}"
            )

        engine_errors: list[str] = []
        if not engine.is_ready(engine_errors):
            detalhe = "; ".join(str(item) for item in engine_errors)
            raise ValueError(f"{where}: motor fuzzy não está pronto — {detalhe}")

        # Aquecimento com um valor de meio de faixa por entrada: só prova que o FLL
        # PROCESSA sem levantar — nunca se exige finitude aqui, um FLL legítimo (`default:
        # nan` sem cobertura total das funções de pertinência) pode dar nan de propósito.
        for variable in engine.input_variables:
            variable.value = (variable.minimum + variable.maximum) / 2.0
        try:
            engine.process()
        except Exception as erro:
            raise ValueError(
                f"{where}: FLL passou nas checagens estáticas mas falhou ao processar um "
                f"valor de aquecimento — {erro}"
            ) from erro

        self._engine = engine
        # O aquecimento acima roda um `process()` com valores arbitrários: sem este
        # `reset()` o `previous_value` de `lock-previous: true` nasceria contaminado, e
        # o caminho de hot-swap-add (scheduler._adopt_staged) não chama `reset()` —
        # espelha o `self.reset()` final do MpcBlock (§4.1-3: bloco novo nasce zerado).
        self.reset()

    @property
    def input_ports(self) -> tuple[str, ...]:
        return self._input_ports

    @property
    def sp_da_entrada(self) -> bool:
        return self._sp_da_entrada

    @property
    def output_ports(self) -> tuple[str, ...]:
        return self._output_ports

    async def step(
        self, inputs: Mapping[str, Signal], *, ts: datetime | None = None
    ) -> dict[str, Signal]:
        if has_cold_input(inputs):
            return null_outputs(self._output_ports)

        # RF-542: a entrada só é "ok" para o motor se TODA amostra tiver a flag boa E for
        # finita — diferente de decisão A-6 (flag isolada), porque aqui um nan de entrada
        # contaminaria o resultado da inferência em silêncio, não só a flag. `q_entradas`
        # rebaixa a BAD por valor não-finito (usado no caminho de sucesso e em
        # `FuzzyState.ok`, fora do escopo desta migração — Task 4). `q_entradas_crua` NÃO
        # rebaixa: é o que permite aos ramos de retenção abaixo diferenciar entrada GOOD
        # retida (-> UNCERTAIN) de entrada já BAD (permanece BAD) -- ADR-043 D7.
        q_entradas_crua = min((s.quality for s in inputs.values()), default=Quality.GOOD)
        q_entradas = q_entradas_crua
        if any(not math.isfinite(float(s.v)) for s in inputs.values()):
            q_entradas = Quality.BAD
        # A ausência de porta em `inputs` não ocorre enquanto `validate_graph` exigir
        # conexão de toda IN (invariante cross-package); o guard abaixo transforma a
        # quebra do invariante em retenção graciosa em vez do KeyError que derrubaria o
        # flow inteiro pelo `_handle_loop_failure` do scheduler.
        try:
            for port, variable in zip(
                self._input_ports,
                self._engine.input_variables[: len(self._input_ports)],
                strict=True,
            ):
                variable.value = float(inputs[port].v)
            if self.setpoint is not None:
                # Última variável declarada = SP do operador (RF-541 revisado; mesma regra de
                # contagem que `validate_graph` aplica no save).
                self._engine.input_variables[-1].value = self.setpoint
            # `process()` roda INLINE, e isso foi medido, não suposto (ARCH-11, 2026-08-16):
            # 2in/1out/3 termos/centroid 200 = 0,49 ms de mediana; 4/2/5/500 = 1,43 ms;
            # 6/3/9/1000 = 3,80 ms; e um config patológico de 8in/4out/15 termos/centroid 1000
            # = 8,04 ms (p95 9,14). Contra o menor `Ts` que a planta usa hoje (2 s) isso é
            # 0,4% do ciclo, e mesmo contra um `Ts` de 100 ms sobra uma ordem de grandeza.
            # Mover para executor custaria um salto de thread por varredura e uma fonte de
            # falha nova (starvation do pool) para economizar isso — não compensa.
            # O gatilho para revisitar não é opinião: é o `block_overrun` que o scheduler
            # emite quando UM bloco sozinho estoura o `Ts` do flow.
            self._engine.process()
        except Exception:
            logger.exception(
                "Bloco fuzzy '%s': falha na inferência — retendo as últimas saídas (ok=False)",
                self.block_id,
            )
            # Retenção de falha (exceção): teto `min(UNCERTAIN, q_entradas_crua)`
            # (ADR-043 D7) -- entrada boa retida vira UNCERTAIN (UncertainLastUsable);
            # entrada BAD permanece BAD, nunca eleva. Porta sem saída boa anterior
            # (`v is None`) não tem o que reter -- ausência de dado, não retenção: BAD.
            self._last_outputs = {
                port: Signal(
                    sample.v,
                    quality=Quality.BAD
                    if sample.v is None
                    else min(Quality.UNCERTAIN, q_entradas_crua),
                )
                for port, sample in self._last_outputs.items()
            }
            return dict(self._last_outputs)

        # O gate do throttle vem ANTES de montar qualquer estado: nas varreduras descartadas
        # não se paga `activation_degree`/`membership` por termo (ADR-030, custo sub-ms).
        publicar = self._deve_publicar()
        outputs: dict[str, Signal] = {}
        output_states: list[FuzzyVarState] = []
        for port, variable in zip(self._output_ports, self._engine.output_variables, strict=True):
            # `OutputVariable.value` pode vir como float ou array numpy shape (1,) depois do
            # defuzzify — normaliza para escalar Python nos dois casos.
            value = float(np.asarray(variable.value).reshape(-1)[-1])
            if math.isfinite(value):
                outputs[port] = Signal(value, quality=q_entradas)
            else:
                # RF-542: nunca nan/inf com ok=True — retém o último valor finito DAQUELA
                # porta (None antes do primeiro bom). Teto `min(UNCERTAIN, q_entradas_crua)`
                # (ADR-043 D7): entrada boa retida vira UNCERTAIN, entrada BAD permanece
                # BAD. Sem saída boa anterior (`v is None`) não há o que reter: fica BAD.
                ultimo = self._last_outputs[port]
                quality = (
                    Quality.BAD if ultimo.v is None else min(Quality.UNCERTAIN, q_entradas_crua)
                )
                outputs[port] = Signal(ultimo.v, quality=quality)
            if publicar:
                output_states.append(
                    FuzzyVarState(
                        port=port,
                        name=variable.name,
                        v=_valor_crisp(value),
                        terms=[
                            FuzzyTermDegree(
                                term=term.name,
                                degree=_grau(variable.fuzzy.activation_degree(term)),
                            )
                            for term in variable.terms
                        ],
                    )
                )
        self._last_outputs = outputs

        if publicar:
            assert self._publish is not None  # `_deve_publicar` já garantiu
            # `FuzzyState.ok` (ADR-030) é bool cru, fora do escopo desta migração (Task 4).
            await self._publicar_estado(
                self._publish, ts, q_entradas is Quality.GOOD, output_states
            )

        return dict(outputs)

    def _deve_publicar(self) -> bool:
        """Throttle na origem (ADR-030): a primeira publicação depois da construção ou de
        `reset()` sempre passa, as seguintes só depois de `_state_min_interval_s` desde a
        última (dedupe local, sem estado no Redis). Marca o instante ao liberar."""
        if self._publish is None:
            return False
        agora = time.monotonic()
        if (
            self._last_publish_mono is not None
            and agora - self._last_publish_mono < self._state_min_interval_s
        ):
            return False
        self._last_publish_mono = agora
        return True

    async def _publicar_estado(
        self,
        publish: Callable[[FuzzyState], Awaitable[None]],
        ts: datetime | None,
        ok_entradas: bool,
        output_states: list[FuzzyVarState],
    ) -> None:
        """Monta e publica o quadro em `fuzzy.state.<flow_id>.<block_id>` (ADR-030)."""
        portas_do_fll = self._engine.input_variables
        # No modo entrada a porta `sp` é fio como qualquer IN; no quadro publicado ela vira a
        # entrada sintética `SP` (mesmo rótulo nas duas fontes: página e histórico não
        # distinguem de onde o SP veio, só o valor vigente).
        n_fios = len(self._input_ports) - (1 if self._sp_da_entrada else 0)
        inputs = [
            FuzzyVarState(
                port=port,
                name=variable.name,
                v=_valor_crisp(float(variable.value)),
                terms=[
                    FuzzyTermDegree(term=term.name, degree=_grau(term.membership(variable.value)))
                    for term in variable.terms
                ],
            )
            for port, variable in zip(
                self._input_ports[:n_fios], portas_do_fll[:n_fios], strict=True
            )
        ]
        estado_sp = None
        if self._sp_da_entrada or self.setpoint is not None:
            variavel_sp = portas_do_fll[-1]
            estado_sp = float(variavel_sp.value) if self._sp_da_entrada else self.setpoint
            inputs.append(
                FuzzyVarState(
                    port="SP",
                    name=variavel_sp.name,
                    v=_valor_crisp(estado_sp),
                    terms=[
                        FuzzyTermDegree(term=term.name, degree=_grau(term.membership(estado_sp)))
                        for term in variavel_sp.terms
                    ],
                )
            )
        rules = [
            _grau(rule.activation_degree) for rb in self._engine.rule_blocks for rule in rb.rules
        ]
        state = FuzzyState(
            ts=ts or datetime.now(UTC),
            ok=ok_entradas,
            sp=estado_sp,
            inputs=inputs,
            rules=rules,
            outputs=output_states,
        )
        try:
            await publish(state)
        except Exception:
            # Telemetria não derruba laço de controle: uma falha do Redis aqui subiria por
            # `step()` → `_scan()` → `_handle_loop_failure` e levaria o flow inteiro a
            # `failed` (mesma postura do `flow.status` em `scheduler.py`).
            logger.exception(
                "Bloco fuzzy '%s': falha ao publicar o estado do motor (varredura segue)",
                self.block_id,
            )

    def reset(self) -> None:
        # `Engine.restart()` zera entradas, recarrega as regras e limpa `previous_value` de
        # todo `OutputVariable` — RF-543: `lock-previous` nunca enxerga estado de antes do
        # reset.
        self._engine.restart()
        self._last_outputs = null_outputs(self._output_ports)
        self._last_publish_mono = None
