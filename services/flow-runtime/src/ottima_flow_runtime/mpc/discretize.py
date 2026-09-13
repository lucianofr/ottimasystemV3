"""Discretização ZOH-exata por par SOPDT/IOPDT no `Ts_mpc` (spec F4 §3.1; TDD estrito).

Cada par (linha×coluna da matriz `models`, spec F4 §2.1-2) vira um `PairSS`: `(a, b, c)`
descrevem o modelo em `x[k+1] = a @ x[k] + b * u[k]`, `y[k] = (c @ x[k])[0]` no `Ts_mpc` —
**sem** o atraso, que a montagem (tarefa 2.2) materializa como shift register de `delay`
amostras na entrada do par. Este módulo é numpy/stdlib puro: do-mpc só entra na montagem.

Convenção idêntica à do bloco TFS de simulação (`ottima_flow_runtime.blocks.tfs`, o par
numérico deste módulo): mesmo ganho `K` aplicado só na saída da cascata (nunca por
estágio), mesmo limiar `Ts/DIRECT_PASS_RATIO` para um estágio degradar a passagem direta, e
mesma convenção `round()` (banker's) do tempo morto — ver `_delay_samples`.

**Prova de equivalência com a recorrência "atualiza-e-emite" do TFS:** `_FirstOrder.step`
(TFS) atualiza o estado e devolve, na mesma chamada, o estado JÁ atualizado. Aqui a
recorrência é a forma padrão `x[k+1] = a @ x[k] + b * u[k]`, `y[k] = c @ x[k]` (saída lida do
estado ANTES do próximo avanço). Com `x[0] = 0`, `y[k]` depende só de `x[k]`, que é o
resultado de `k` propagações — exatamente o estado "pós-atualização" que o TFS devolve na
k-ésima chamada. As duas sequências coincidem termo a termo (índice k = número da chamada):
para reproduzir a série do TFS a partir de um `PairSS`, avance o estado (`x <- a@x + b*u`) e
só depois leia `c @ x`, nessa ordem — nunca leia `c @ x` antes do primeiro avanço.
"""

from dataclasses import dataclass

import numpy as np

from ottima_core.flowgraph import RowKind

DIRECT_PASS_RATIO = 10.0
"""`tau < Ts/DIRECT_PASS_RATIO` degrada o estágio para passagem direta — mesmo limiar do
TFS (`ottima_flow_runtime.blocks.tfs.DIRECT_PASS_RATIO`): a simulação e o modelo interno do
MPC têm de concordar no mesmo ponto de corte, senão o número de estados do par diverge entre
os dois códigos para o mesmo `tau`."""


@dataclass(frozen=True, slots=True, eq=False)
class PairSS:
    """Modelo discreto de um par da matriz MPC, no `Ts_mpc`, sem o atraso.

    `a`: matriz de estados, shape `(n, n)`. `b`: coluna de entrada, shape `(n, 1)`. `c`:
    linha de saída, shape `(1, n)`. `n` é 0 (par inteiro em passagem direta — os dois
    estágios do SOPDT abaixo do limiar; ver nota em `discretize_sopdt`), 1 (SOPDT de 1a
    ordem ou IOPDT) ou 2 (SOPDT completo). Sempre 2-D, mesmo nos casos degenerados: a
    montagem da 2.2 concatena vários pares num bloco-diagonal, e shapes uniformes dispensam
    caso especial por dimensão.

    Convenção: `x[k+1] = a @ x[k] + b * u[k]`, `y[k] = (c @ x[k])[0]` — sem termo direto
    (`D`); ver docstring do módulo para a prova de equivalência com o TFS.

    `delay`: atraso de `theta` em amostras de `Ts_mpc` (banker's — `_delay_samples`).

    `eq=False`: a igualdade default dos dataclasses compara os campos com `==`, e `==`
    entre `np.ndarray` devolve um array (não um `bool`) — comparar duas instâncias com `==`
    levantaria `ValueError` em runtime. Comparação de conteúdo é responsabilidade de quem
    lê os campos (ex.: `np.allclose`), não da identidade da instância.
    """

    a: np.ndarray
    b: np.ndarray
    c: np.ndarray
    delay: int


def _delay_samples(theta: float, ts: float) -> int:
    """`round(theta/ts)`: convenção banker's (half-even) do `round()` do Python.

    NOTA NORMATIVA (spec F4 §3.1; fecha débito m2, spec F4 §8): mesma convenção do TFS
    (`ottima_flow_runtime.blocks.tfs._Element.__init__`) e da validação
    (`ottima_core.flowgraph.validate`) — simulação e modelo interno do MPC têm de
    concordar no mesmo número de amostras para o mesmo `theta`, senão o tempo morto do
    modelo interno diverge silenciosamente do da malha real. `round(2.5) == 2`, não 3:
    half-even arredonda para o inteiro par mais próximo, não para cima.
    """
    return round(theta / ts)


def _stage(tau: float, ts: float) -> tuple[float, float] | None:
    """`(a, b)` de um estágio de 1a ordem exato no ZOH (`a = e^(-Ts/tau)`, `b = 1-a`), ou
    `None` se `tau` está abaixo do limiar (passagem direta — evita `tau=0` dividir por
    zero, igual ao TFS)."""
    if tau < ts / DIRECT_PASS_RATIO:
        return None
    a = float(np.exp(-ts / tau))
    return a, 1.0 - a


def discretize_sopdt(K: float, tau1: float, tau2: float, theta: float, ts: float) -> PairSS:
    """SOPDT (dois estágios de 1a ordem em série, ganho `K` aplicado na saída) no `Ts_mpc`.

    UNIDADES (contrato do config, RF-602): `K` chega aqui já em EU (Δy_EU/Δu_EU, convertido
    de %/% por `eu_gain_params`); `tau1`/`tau2`/`theta`/`ts` TODOS em segundos — o config do
    usuário informa tempos em segundos e nada neste módulo converte base de tempo.

    **Dois estágios ativos:** 2 estados, forma companion triangular inferior — pólos
    `e^(-Ts/tau1)` e `e^(-Ts/tau2)` (autovalores de `a`, a própria diagonal por
    triangularidade). Derivação: o estágio 2 consome a saída JÁ ATUALIZADA do estágio 1 na
    mesma amostra (mesma ordem do TFS — `_Sopdt.step` encadeia as chamadas em sequência),
    logo `x2[k+1] = a2*x2[k] + b2*x1[k+1] = a2*x2[k] + a1*b2*x1[k] + b1*b2*u[k]`.

    **Um estágio em passagem direta** (`tau < Ts/DIRECT_PASS_RATIO`, o que inclui
    `tau2=0`): degrada para 1a ordem exata — o estágio restante carrega toda a dinâmica,
    com o ganho `K` na saída (independe de qual dos dois, `tau1` ou `tau2`, é o que some).

    **Os dois em passagem direta** (`n=0`, par de ganho puro `K`, sem estado): fora do
    escopo dos testes desta tarefa — combinação improvável em configs reais (a validação da
    matriz de horizontes não a impede, mas o par perde toda dinâmica em relação ao `Ts_mpc`)
    e a forma `x[k+1]=a@x[k]+b*u[k]`, `y[k]=c@x[k]` **sem termo direto `D`** não consegue
    representar um ganho puro sem atraso: com `n=0`, `y[k] = c@x[k] = 0` sempre, nunca
    `K*u[k]`. A montagem (2.2) precisa tratar esse caso à parte se ele aparecer (ver
    relatório da tarefa 2.1).
    """
    delay = _delay_samples(theta, ts)
    stage1 = _stage(tau1, ts)
    stage2 = _stage(tau2, ts)

    if stage1 is not None and stage2 is not None:
        a1, b1 = stage1
        a2, b2 = stage2
        a = np.array([[a1, 0.0], [a1 * b2, a2]])
        b = np.array([[b1], [b1 * b2]])
        c = np.array([[0.0, K]])
    elif stage1 is not None or stage2 is not None:
        a_active, b_active = stage1 if stage1 is not None else stage2
        a = np.array([[a_active]])
        b = np.array([[b_active]])
        c = np.array([[K]])
    else:
        a = np.zeros((0, 0))
        b = np.zeros((0, 1))
        c = np.zeros((1, 0))

    return PairSS(a=a, b=b, c=c, delay=delay)


def discretize_iopdt(Ki: float, theta: float, ts: float, *, tau1: float = 0.0) -> PairSS:
    """IOPDT/IFOPDT: integrador retangular `acc += Ki*Ts*u`, opcionalmente alimentado por um
    estágio de 1a ordem (`tau1 > 0`) — `Ki·e^(-θs)/(s·(τ1·s+1))`.

    `tau1 = 0` (ou abaixo de `Ts/DIRECT_PASS_RATIO`, o mesmo limiar do SOPDT) devolve o
    integrador puro de 1 estado — forma idêntica à de antes do campo existir, então todo
    config gravado sem `tau1` carrega bit a bit igual. Com o lag ativo são 2 estados
    `[x_lag, acumulador]`, na MESMA composição "atualiza-e-emite" do SOPDT: o acumulador
    consome a saída JÁ atualizada do estágio (`acc[k+1] = acc[k] + Ki·Ts·x1[k+1]`), o que dá
    `a = [[a1, 0], [Ki·Ts·a1, 1]]`, `b = [[b1], [Ki·Ts·b1]]`, `c = [[0, 1]]` — pólos `a1` e
    `1`. A saída é SEMPRE o acumulador (último estado): `bumpless` e o SSTO dependem disso.

    O lag não altera a taxa de regime — `y` converge para `Ki·u` por segundo, só deslocado
    no tempo pelo transiente do estágio; quem lê a taxa de rampa do `PairSS` tem de resolver
    o estágio assentado, não `(c·b)/Ts` (ver `target_calculation.model`).

    UNIDADES (contrato do config, RF-602): `Ki` chega aqui já em EU/s por EU — convertido em
    `eu_gain_params` do ganho NORMALIZADO **%/%/s** informado pelo usuário (taxa da linha em
    % do span DELA por segundo, por **1% do span da coluna**): `Ki_EU = Ki ×
    span_linha/span_coluna`, a MESMA razão de spans do SOPDT. `b = Ki_EU*ts` com `ts` em
    segundos entrega o incremento por amostra; `tau1`/`theta`/`ts` também em segundos. Ki em
    %/min produziria modelo 60× lento: a UI rotula o campo com a base completa
    (`Ki (%/(%·s))`, TabModels)."""
    delay = _delay_samples(theta, ts)
    stage = _stage(tau1, ts)
    if stage is None:
        a = np.array([[1.0]])
        b = np.array([[Ki * ts]])
        c = np.array([[1.0]])
        return PairSS(a=a, b=b, c=c, delay=delay)

    a1, b1 = stage
    ki_ts = Ki * ts
    a = np.array([[a1, 0.0], [ki_ts * a1, 1.0]])
    b = np.array([[b1], [ki_ts * b1]])
    c = np.array([[0.0, 1.0]])
    return PairSS(a=a, b=b, c=c, delay=delay)


def eu_gain_params(
    params: dict[str, float], *, kind: RowKind, row_span: float, col_span: float
) -> dict[str, float]:
    """Converte os ganhos NORMALIZADOS do config para a forma em EU que `discretize_*`
    espera, ANTES de qualquer montagem/worker (RF-602/609).

    BASE DAS UNIDADES (RF-602/609 — o texto normativo do PRD manda converter os DOIS ganhos
    por `span_linha/span_coluna`, e é o que esta função faz):

    - `K` (SOPDT): adimensional %/% — `ΔCV%/ΔMV%` sobre as faixas de instrumento (zero/span,
      RF-609). Conversão: `K_EU = K × span_linha/span_coluna`.
    - `Ki` (IOPDT): **%/%/s** — taxa da linha em % do span DELA por segundo, por **1% do
      span da coluna**. Conversão: `Ki_EU = Ki × span_linha/span_coluna`, em EU/s por EU (a
      base de tempo do ganho integral já é o segundo). A ÚNICA diferença entre as duas formas
      é a dimensão de TEMPO, nunca a normalização por span.

    Ponto ÚNICO de conversão: builder dinâmico e SSTO (`target_calculation/model.py`)
    consomem esta função, então nunca divergem.

    Defaults 0/100 de zero/span dão razão de span 1, então config sem faixa explícita
    reproduz a normalização pura. Cópia rasa: `params` do chamador nunca é mutado.

    HISTÓRICO (2026-09-11 → 2026-09-12): por um dia esta função aplicou um ÷100 EXTRA no
    integrador ("coluna sustentada em 100% do span"). Removido por ordem do dono do produto —
    o número do campo é `%/%/s` e nada mais é dividido. Config NOVO não tem nada a converter:
    digite o `Ki` em %/%/s e pronto. Só o modelo cujo `Ki` foi ESCOLHIDO naquela janela (para
    compensar o ÷100) fica 100× grande e tem de ser DIVIDIDO por 100 ao migrar — flow 987,
    linha de nível: 0,2191 gravado ⇒ 0,002191 nesta base (o Ki_EU dos dois é o mesmo).
    REVALIDAR `economics.integrating_tolerance` e o `sp_range_pct` das linhas integradoras: a
    faixa de taxa do SSTO traduzida em movimento de MV é `ε/Ki_EU` e encolhe 100× nesta base."""
    chave = "K" if kind == "selfreg" else "Ki"
    convertido = dict(params)
    convertido[chave] = params[chave] * (row_span / col_span)
    return convertido
