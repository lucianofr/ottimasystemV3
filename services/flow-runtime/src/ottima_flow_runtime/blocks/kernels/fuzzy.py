"""Kernel fuzzy incremental (SPEC_FUZZY secao 3.3).

Estrutura fuzzy-PI: o motor de inferencia opera SEMPRE em universo normalizado `[-1,1]`, e
toda adaptacao a faixa do processo vive nos ganhos (`ke`, `kde`, `ku`). Consequencia
pratica: sintonia em campo mexe em tres numeros, nunca na base de regras com planta
rodando.

`direct_acting` e aplicado ao ERRO, nao a saida (ADR-039 secao 4.5): inverter a saida
exigiria simetria da superficie de controle, e base de regras autoral nao garante isso.

O kernel devolve `du/dt` em %span/s e NAO integra — a integracao, os limites e o
anti-windup sao do shell (ADR-039). Resultado nao-finito volta como NaN: o shell segura
`OUT` e alarma `kernel_invalid_output` (SPEC secao 4.4). Isso e rede de seguranca, nao modo
de operacao — os portoes de superficie da fase K3 existem para que um bloco comissionado
nunca chegue la.
"""

import math
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

    def compute(self, sp: float, pv: float, dt: float) -> float:  # noqa: ARG002
        return math.nan

    def align(self, u: float, sp: float, pv: float) -> None:  # noqa: ARG002
        return None

    def reset(self) -> None:
        return None

    def validate(self) -> list[str]:
        return list(self.errors)


class FuzzyKernel:
    """Kernel fuzzy incremental. Contrato: ADR-039 secao 4.5."""

    def __init__(self, engine: fl.Engine, cfg: FuzzyKernelCfg, fll: str) -> None:
        self.eng = engine
        self._fll = fll  # texto de origem: insumo de `sample_surface` na regeracao da LUT
        self._e_in = engine.input_variable("e")
        self._de_in = engine.input_variable("de")
        self._du_out = engine.output_variable("du")
        # LUT ativa SUBSTITUI a inferencia por scan (SPEC secao 5.2): o custo passa a ser
        # quatro leituras e tres multiplicacoes, independente do defuzzificador. O Engine
        # fica carregado so para revalidacao/regeracao.
        self.lut: np.ndarray | None = None
        self._cfg = cfg
        self._reconciliar_lut()
        self.diag: dict[str, float] = {}
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

    def _reconciliar_lut(self) -> None:
        """Materializa, descarta ou reescala a grade conforme o cfg corrente.

        So reamostra quando (`lut_enabled`, `lut_resolution`) mudou de fato: trocar KE/KU
        nao toca a superficie, e reamostrar a cada sintonia gastaria alguns ms por bloco
        sem mudar um numero.
        """
        c = self._cfg
        if not c.lut_enabled:
            self.lut = None
            return
        if self.lut is not None and self.lut.shape[0] == c.lut_resolution:
            return
        self.lut = sample_surface(self._fll, resolution=c.lut_resolution)

    def reset(self) -> None:
        self.e_prev = 0.0
        self.de_f = 0.0
        # `restart()` zera entradas e limpa o estado interno do Engine — sem ele, um bloco
        # readotado por hot-swap herdaria valor de variavel da instancia anterior.
        self.eng.restart()

    def align(self, u: float, sp: float, pv: float) -> None:  # noqa: ARG002
        """Realinha o erro anterior e ZERA a derivada filtrada.

        Zerar `de_f` e deliberado: ao sair de Manual, a derivada carregada de antes da
        transicao nao descreve mais o processo, e preserva-la produz chute na primeira
        execucao (SPEC secao 3.3). `u` nao entra na conta — a forma incremental nao guarda
        posicao, e por isso que a troca de sintonia nao gera degrau (F10).
        """
        self.e_prev = self._error(sp, pv)
        self.de_f = 0.0

    def _error(self, sp: float, pv: float) -> float:
        return (pv - sp) if self.cfg.direct_acting else (sp - pv)

    def compute(self, sp: float, pv: float, dt: float) -> float:
        c = self.cfg
        e = self._error(sp, pv)
        de = (e - self.e_prev) / dt

        a = dt / (c.tf_de + dt)  # filtro de 1a ordem, robusto a dt variavel
        self.de_f += a * (de - self.de_f)
        self.e_prev = e

        e_n = _sat(e * c.ke, -1.0, 1.0)
        de_n = _sat(self.de_f * c.kde, -1.0, 1.0)
        self.diag = {"e_n": e_n, "de_n": de_n}
        if self.lut is not None:
            du_n = self._interp_bilinear(e_n, de_n)
            # `rule_fire_count` FICA DE FORA: sem inferencia no scan nao existe grau de
            # ativacao, e NaN ali viajaria como `null` num campo tipado `float` no espelho
            # TS. Ausente, o faceplate cai no proprio fallback.
        else:
            self._e_in.value = e_n
            self._de_in.value = de_n
            self.eng.process()
            # `OutputVariable.value` pode vir float ou array numpy shape (1,) depois do
            # defuzzify — mesma normalizacao do bloco `fuzzy` (ADR-029).
            du_n = float(np.asarray(self._du_out.value).reshape(-1)[-1])
            self.diag["rule_fire_count"] = self._rule_fire_count()
        self.diag["du_n"] = du_n
        if not math.isfinite(du_n):
            return math.nan  # o shell trata: segura OUT e alarma
        return c.ku * du_n

    def _interp_bilinear(self, e_n: float, de_n: float) -> float:
        """`du_n` interpolado na LUT; saturacao nas bordas (SPEC secao 5.2).

        NaN em qualquer um dos quatro vizinhos contamina o resultado de proposito: a LUT nao
        pode "consertar" regiao sem regra por interpolacao — o buraco tem de continuar
        visivel como `kernel_invalid_output` (F3).
        """
        lut = self.lut
        assert lut is not None  # so chamado quando a LUT esta ativa
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
        (SPEC secao 6.4).
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
        errs += validate_fll_contract(self.eng)
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

    Com `cfg.lut_enabled`, a superficie e amostrada na construcao e o scan passa a
    interpolar: tempo de execucao deixa de depender do defuzzificador.
    """
    try:
        engine = fl.FllImporter().from_string(fll)
    except Exception as erro:  # F1 na camada de deploy
        return BrokenKernel([f"FLL_PARSE_ERROR: {erro}"], cfg)
    erros = validate_fll_contract(engine)
    if erros or not engine.is_ready():
        return BrokenKernel(erros or ["ENGINE_NOT_READY"], cfg)
    # `FuzzyKernel` amostra de uma Engine PROPRIA (`sample_surface` monta a sua): a Engine
    # deste kernel nao pode ficar com array nas variaveis (SPEC secao 4.2, nao reentrante).
    return FuzzyKernel(engine, cfg, fll)
