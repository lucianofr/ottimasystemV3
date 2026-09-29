"""Kernel fuzzy incremental multicanal (SPEC_FUZZY secao 3.3, v2 MIMO).

Estrutura fuzzy-PI generalizada para `n_loops` canais: o motor de inferencia opera SEMPRE
em universo normalizado `[-1,1]`, e toda adaptacao a faixa do processo vive nos ganhos
(`ke`, `kde`, `ku`). As entradas do motor sao POSICIONAIS (contrato da SPEC secao 3.2 v2):
entrada `2i` = `e_n` do canal `i`, entrada `2i+1` = `de_n` do canal `i`, saida `i` = `du_n`
do canal `i` — os nomes das variaveis no FLL sao livres, e as regras podem cruzar canais
(desacoplamento MIMO autoral). UM `process()` por varredura avalia todos os canais juntos.

Consequencia pratica: sintonia em campo mexe em tres numeros, nunca na base de regras com
planta rodando.

`direct_acting` e aplicado ao ERRO, nao a saida (ADR-039 secao 4.5): inverter a saida
exigiria simetria da superficie de controle, e base de regras autoral nao garante isso.

O kernel devolve `du/dt` em %span/s e NAO integra — a integracao, os limites e o
anti-windup sao do shell (ADR-039). Resultado nao-finito em qualquer canal volta como NaN
naquele canal: o shell segura as saidas e alarma `kernel_invalid_output` (SPEC secao 4.4).
Isso e rede de seguranca, nao modo de operacao — os portoes de superficie da fase K3
existem para que um bloco comissionado nunca chegue la.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import fuzzylite as fl
import numpy as np

from ottima_core.flowgraph.fll_contract import validate_fll_contract
from ottima_core.flowgraph.fuzzy_surface import sample_surface


def _sat(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


@dataclass(slots=True)
class FuzzyKernelCfg:
    ke: float  # 1/EU, > 0    -> normaliza o erro; 1/ke e a faixa coberta sem saturar
    kde: float = 0.0  # s/EU, >= 0   -> normaliza a derivada filtrada do erro
    ku: float = 1.0  # %span/s, > 0 -> ganho de saida (velocidade maxima de atuacao)
    tf_de: float = 1.0  # s, > 0       -> filtro da derivada do erro
    direct_acting: bool = False
    n_loops: int = 1  # canais de controle (v2 MIMO); 1 = comportamento SISO classico
    # LUT mora AQUI, nao na instancia: SPEC secao 6.3 classifica LUT_ENABLED/LUT_RESOLUTION
    # como classe de SINTONIA (hot-swap in-place), e `apply_tuning` do shell so troca o
    # `cfg` — LUT fora do cfg tornava o toggle silenciosamente inocuo.
    lut_enabled: bool = False
    lut_resolution: int = 65


@dataclass(slots=True)
class BrokenKernel:
    """Kernel de config invalida: o shell le `validate()` e prende o bloco em OOS.

    Existe para que FLL degradado entre save e deploy nao derrube o flow inteiro na
    construcao — o bloco nasce, recusa-se a calcular e aparece como CONFIG_ERROR (F1 na
    camada de deploy, SPEC secao 4.1-5).
    """

    errors: list[str]
    cfg: FuzzyKernelCfg
    diag: dict[str, float] = field(default_factory=dict)
    diag_channels: list[dict[str, float]] = field(default_factory=list)

    def compute(self, sp: float, pv: float, dt: float) -> float:  # noqa: ARG002
        return math.nan

    def compute_all(
        self,
        sps: Sequence[float],
        pvs: Sequence[float],
        dt: float,  # noqa: ARG002
    ) -> list[float]:
        return [math.nan] * len(sps)

    def align(self, u: float, sp: float, pv: float) -> None:  # noqa: ARG002
        return None

    def align_all(
        self,
        us: Sequence[float],
        sps: Sequence[float],
        pvs: Sequence[float],  # noqa: ARG002
    ) -> None:
        return None

    def reset(self) -> None:
        return None

    def validate(self) -> list[str]:
        return list(self.errors)


class FuzzyKernel:
    """Kernel fuzzy incremental multicanal. Contrato: ADR-039 secao 4.5 + SPEC_FUZZY v2."""

    def __init__(self, engine: fl.Engine, cfg: FuzzyKernelCfg, fll: str) -> None:
        self.eng = engine
        self._fll = fll  # texto de origem: insumo de `sample_surface` na regeracao da LUT
        # Posicionais (contrato v2): entrada 2i = e_n do canal i, 2i+1 = de_n; saida i = du_n.
        self._entradas = list(engine.input_variables)
        self._saidas = list(engine.output_variables)
        # LUT ativa SUBSTITUI a inferencia por scan (SPEC secao 5.2): o custo passa a ser
        # quatro leituras e tres multiplicacoes por canal, independente do defuzzificador.
        # O Engine fica carregado so para revalidacao/regeracao. Uma grade por canal.
        self.luts: list[np.ndarray | None] = [None] * cfg.n_loops
        self._cfg = cfg
        self._reconciliar_lut()
        self.diag: dict[str, float] = {}
        self.diag_channels: list[dict[str, float]] = [{} for _ in range(cfg.n_loops)]
        self.reset()

    @property
    def cfg(self) -> FuzzyKernelCfg:
        return self._cfg

    @cfg.setter
    def cfg(self, novo: FuzzyKernelCfg) -> None:
        """Aplicar sintonia nova reconcilia a LUT (SPEC secao 6.3).

        O shell chama exatamente isto em `apply_tuning`; deixar a reconciliacao aqui mantem
        o shell alheio a LUT e faz o toggle valer sem re-instanciar o bloco.
        """
        self._cfg = novo
        self._reconciliar_lut()

    @property
    def lut(self) -> np.ndarray | None:
        """Grade do canal 0 — vista SISO-compat; v2 tem uma grade por canal em `luts`."""
        return self.luts[0]

    def _reconciliar_lut(self) -> None:
        """Materializa, descarta ou reescala as grades conforme o cfg corrente.

        So reamostra quando (`lut_enabled`, `lut_resolution`) mudou de fato: trocar KE/KU
        nao toca a superficie, e reamostrar a cada sintonia gastaria alguns ms por bloco
        sem mudar um numero.
        """
        c = self._cfg
        if not c.lut_enabled:
            self.luts = [None] * c.n_loops
            return
        if (
            len(self.luts) == c.n_loops
            and all(lut is not None for lut in self.luts)
            and self.luts[0] is not None
            and self.luts[0].shape[0] == c.lut_resolution
        ):
            return
        self.luts = [
            sample_surface(self._fll, resolution=c.lut_resolution, n_loops=c.n_loops, channel=canal)
            for canal in range(c.n_loops)
        ]

    def reset(self) -> None:
        n = self._cfg.n_loops
        self.e_prev = [0.0] * n
        self.de_f = [0.0] * n
        # `restart()` zera entradas e limpa o estado interno do Engine — sem ele, um bloco
        # readotado por hot-swap herdaria valor de variavel da instancia anterior.
        self.eng.restart()

    def align(self, u: float, sp: float, pv: float) -> None:
        """Forma SISO (compatibilidade de protocolo): realinha o canal 0."""
        self.align_all([u], [sp], [pv])

    def align_all(
        self,
        us: Sequence[float],
        sps: Sequence[float],
        pvs: Sequence[float],  # noqa: ARG002
    ) -> None:
        """Realinha o erro anterior e ZERA a derivada filtrada de cada canal.

        Zerar `de_f` e deliberado: ao sair de Manual, a derivada carregada de antes da
        transicao nao descreve mais o processo, e preserva-la produz chute na primeira
        execucao (SPEC secao 3.3). `u` nao entra na conta — a forma incremental nao guarda
        posicao, e por isso que a troca de sintonia nao gera degrau (F10).
        """
        for i in range(min(len(sps), len(self.e_prev))):
            erro = self._error(sps[i], pvs[i])
            if not math.isfinite(erro):
                # Um align que nao pode ser calculado nao finge ter alinhado: gravar
                # `e_prev = nan` deixaria `de = (finito - nan)` NaN em TODO scan seguinte,
                # muito depois de a entrada ter voltado ao normal. O shell rechama align no
                # proximo scan.
                continue
            self.e_prev[i] = erro
            self.de_f[i] = 0.0

    def _error(self, sp: float, pv: float) -> float:
        return (pv - sp) if self.cfg.direct_acting else (sp - pv)

    def compute(self, sp: float, pv: float, dt: float) -> float:
        """Forma SISO (compatibilidade de protocolo): canal unico."""
        return self.compute_all([sp], [pv], dt)[0]

    def compute_all(self, sps: Sequence[float], pvs: Sequence[float], dt: float) -> list[float]:
        c = self.cfg
        n = c.n_loops
        if not all(
            math.isfinite(sp) and math.isfinite(pv) for sp, pv in zip(sps, pvs, strict=False)
        ):
            # Entrada nao-finita sai por NaN SEM tocar estado nem LUT. Duas razoes:
            # (1) `_interp_bilinear` faria `int(nan)` e levantaria ValueError, que sobe por
            #     `step()` ate `_handle_loop_failure` e derruba o FLOW INTEIRO — a inferencia
            #     devolveria NaN e o shell so seguraria o OUT; a mesma entrada nao pode ter
            #     dois destinos;
            # (2) gravar `e_prev = nan` deixaria `de` NaN para sempre, muito depois da
            #     entrada ter voltado ao normal.
            # O shell ja barra PV nao-finito (`_update_pv` -> shed), entao isto e a segunda
            # linha de defesa, no lugar onde a consequencia de errar e queda de flow.
            return [math.nan] * n

        e_ns: list[float] = []
        de_ns: list[float] = []
        for i in range(n):
            e = self._error(sps[i], pvs[i])
            de = (e - self.e_prev[i]) / dt
            a = dt / (c.tf_de + dt)  # filtro de 1a ordem, robusto a dt variavel
            self.de_f[i] += a * (de - self.de_f[i])
            self.e_prev[i] = e
            # `_sat` NAO sanitiza NaN (`v < lo` e `v > hi` sao ambos False), entao a
            # saturacao nao e barreira: e_n/de_n saem NaN se o estado do filtro estiver
            # contaminado (ex.: `e_prev` envenenado), ainda que sp/pv deste scan sejam
            # finitos. A guarda vai AQUI, depois dela.
            e_ns.append(_sat(e * c.ke, -1.0, 1.0))
            de_ns.append(_sat(self.de_f[i] * c.kde, -1.0, 1.0))
        if not all(math.isfinite(v) for v in e_ns) or not all(math.isfinite(v) for v in de_ns):
            # diag intocado (invariante do recorder: diag so tem valor finito); o shell
            # segura OUT, alarma e rechama align — que e o que repara o estado.
            return [math.nan] * n

        # INVARIANTE: todo valor de diag e finito. `LoopState.diag` e `dict[str, float]` e
        # o recorder REVALIDA o JSON (`_parse(LoopState, raw)`) — `model_dump_json` emite
        # NaN como `null`, mas `model_validate_json` rejeita null, e o quadro inteiro e
        # contado como malformado e descartado: a tendencia perde o ponto sem erro visivel.
        for i in range(n):
            self.diag_channels[i] = {"e_n": e_ns[i], "de_n": de_ns[i]}

        dus: list[float] = []
        if all(lut is not None for lut in self.luts):
            for i in range(n):
                lut = self.luts[i]
                assert lut is not None  # checado no all() acima
                dus.append(self._interp_bilinear(lut, e_ns[i], de_ns[i]))
            # `rule_fire_count` fica de fora: sem inferencia no scan nao existe grau de
            # ativacao. Ausente (nunca NaN), o faceplate cai no proprio fallback.
        else:
            for i in range(n):
                self._entradas[2 * i].value = e_ns[i]
                self._entradas[2 * i + 1].value = de_ns[i]
            self.eng.process()
            fire_count = self._rule_fire_count()
            for i in range(n):
                # `OutputVariable.value` pode vir float ou array numpy shape (1,) depois do
                # defuzzify — mesma normalizacao do bloco `fuzzy` (ADR-029).
                du_n = float(np.asarray(self._saidas[i].value).reshape(-1)[-1])
                if math.isfinite(du_n):
                    self.diag_channels[i]["rule_fire_count"] = fire_count
                dus.append(du_n)

        resultado: list[float] = []
        for i in range(n):
            du_n = dus[i]
            if not math.isfinite(du_n):
                resultado.append(math.nan)  # regiao sem regra: o shell segura OUT e alarma
                continue
            self.diag_channels[i]["du_n"] = du_n
            resultado.append(c.ku * du_n)
        self.diag = self.diag_channels[0]
        return resultado

    def _interp_bilinear(self, lut: np.ndarray, e_n: float, de_n: float) -> float:
        """`du_n` interpolado na LUT do canal; saturacao nas bordas (SPEC secao 5.2).

        NaN em qualquer um dos quatro vizinhos contamina o resultado de proposito: a LUT
        nao pode "consertar" regiao sem regra por interpolacao — o buraco tem de continuar
        visivel como `kernel_invalid_output` (F3).
        """
        if not (math.isfinite(e_n) and math.isfinite(de_n)):
            # Guarda no PROPRIO ponto do crash: `int(nan)` levanta ValueError, que sobe por
            # `step()` ate `_handle_loop_failure` e derruba o flow inteiro, enquanto a
            # inferencia devolveria NaN. Barrar aqui nao depende de provar que nenhum NaN
            # chega — a mesma entrada tem de ter o mesmo destino nos dois caminhos.
            return math.nan
        n = lut.shape[0]
        passo = 2.0 / (n - 1)
        # de_n -> eixo 0, e_n -> eixo 1 (mesma orientacao de `sample_surface`)
        fi = _sat((de_n + 1.0) / passo, 0.0, float(n - 1))
        fj = _sat((e_n + 1.0) / passo, 0.0, float(n - 1))
        i0, j0 = int(fi), int(fj)
        i1, j1 = min(i0 + 1, n - 1), min(j0 + 1, n - 1)
        ti, tj = fi - i0, fj - j0
        v00, v01 = float(lut[i0, j0]), float(lut[i0, j1])
        v10, v11 = float(lut[i1, j0]), float(lut[i1, j1])
        baixo = v00 + (v01 - v00) * tj
        alto = v10 + (v11 - v10) * tj
        return baixo + (alto - baixo) * ti

    def _rule_fire_count(self) -> float:
        """Regras com grau de ativacao > 0 no ultimo scan (SPEC secao 6.2).

        Diagnostico de sintonia, nao de falha: contagem presa em 1 denuncia `ke`/`kde` alto
        demais — o erro satura, a superficie opera nos cantos e o beneficio do fuzzy morre
        (SPEC secao 6.4). No multicanal a contagem e do motor inteiro (regras de todos os
        canais disparam no mesmo `process()`).
        """
        total = 0
        for rb in self.eng.rule_blocks:
            for regra in rb.rules:
                grau = float(np.asarray(regra.activation_degree).reshape(-1)[-1])
                if math.isfinite(grau) and grau > 0.0:
                    total += 1
        return float(total)

    def validate(self) -> list[str]:
        errs: list[str] = []
        if not self.eng.is_ready():
            errs.append("ENGINE_NOT_READY")
        errs += validate_fll_contract(self.eng, n_loops=self.cfg.n_loops)
        c = self.cfg
        if not math.isfinite(c.ke) or c.ke <= 0.0:
            errs.append("KE_MUST_BE_POSITIVE")
        if not math.isfinite(c.kde) or c.kde < 0.0:
            errs.append("KDE_MUST_BE_NON_NEGATIVE")  # 0 = derivada desligada
        if not math.isfinite(c.ku) or c.ku <= 0.0:
            errs.append("KU_MUST_BE_POSITIVE")  # sentido via direct_acting
        if not math.isfinite(c.tf_de) or c.tf_de <= 0.0:
            errs.append("TF_DE_MUST_BE_POSITIVE")
        return errs


def build_fuzzy_kernel(fll: str, cfg: FuzzyKernelCfg) -> FuzzyKernel | BrokenKernel:
    """Monta o kernel a partir do texto FLL, ou um `BrokenKernel` se a config nao presta.

    Uma `Engine` por chamada, nunca compartilhada nem com o mesmo texto (SPEC secao 4.2):
    a Engine guarda o valor corrente dentro das variaveis, e portanto nao e reentrante.

    Com `cfg.lut_enabled`, as superficies (uma por canal) sao amostradas na construcao e o
    scan passa a interpolar: tempo de execucao deixa de depender do defuzzificador.
    """
    try:
        engine = fl.FllImporter().from_string(fll)
    except Exception as erro:  # F1 na camada de deploy
        return BrokenKernel([f"FLL_PARSE_ERROR: {erro}"], cfg)
    erros = validate_fll_contract(engine, n_loops=cfg.n_loops)
    if erros or not engine.is_ready():
        return BrokenKernel(erros or ["ENGINE_NOT_READY"], cfg)
    # `FuzzyKernel` amostra de uma Engine PROPRIA (`sample_surface` monta a sua): a Engine
    # deste kernel nao pode ficar com array nas variaveis (SPEC secao 4.2, nao reentrante).
    return FuzzyKernel(engine, cfg, fll)
