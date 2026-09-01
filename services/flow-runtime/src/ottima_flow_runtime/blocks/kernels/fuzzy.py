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


def _sat(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


@dataclass(slots=True)
class FuzzyKernelCfg:
    ke: float  # 1/EU, > 0    -> normaliza o erro; 1/ke e a faixa coberta sem saturar
    kde: float = 0.0  # s/EU, >= 0   -> normaliza a derivada filtrada do erro
    ku: float = 1.0  # %span/s, > 0 -> ganho de saida (velocidade maxima de atuacao)
    tf_de: float = 1.0  # s, > 0       -> filtro da derivada do erro
    direct_acting: bool = False


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

    def __init__(self, engine: fl.Engine, cfg: FuzzyKernelCfg) -> None:
        self.eng, self.cfg = engine, cfg
        self._e_in = engine.input_variable("e")
        self._de_in = engine.input_variable("de")
        self._du_out = engine.output_variable("du")
        self.diag: dict[str, float] = {}
        self.reset()

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
        self._e_in.value = e_n
        self._de_in.value = de_n
        self.eng.process()

        # `OutputVariable.value` pode vir float ou array numpy shape (1,) depois do
        # defuzzify — mesma normalizacao do bloco `fuzzy` (ADR-029).
        du_n = float(np.asarray(self._du_out.value).reshape(-1)[-1])
        self.diag = {
            "e_n": e_n,
            "de_n": de_n,
            "du_n": du_n,
            "rule_fire_count": self._rule_fire_count(),
        }
        if not math.isfinite(du_n):
            return math.nan  # o shell trata: segura OUT e alarma
        return c.ku * du_n

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
    """
    try:
        engine = fl.FllImporter().from_string(fll)
    except Exception as erro:  # F1 na camada de deploy
        return BrokenKernel([f"FLL_PARSE_ERROR: {erro}"], cfg)
    erros = validate_fll_contract(engine)
    if erros or not engine.is_ready():
        return BrokenKernel(erros or ["ENGINE_NOT_READY"], cfg)
    return FuzzyKernel(engine, cfg)
