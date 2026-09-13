# SPEC — Bloco PID Malha (`pid_loop`)

- **Versão:** 2.0 · 2026-08-31 (revisão pós-verificação de código; a v1.0 era rascunho com premissas em aberto)
- **Depende de:** ADR-039 (shell de bloco), ADR-024 (exec_order), ADR-031 (bloco pid)
- **Componentes afetados:** `flow-runtime`, `ottima-core` (parse/validate/contracts_export), API FastAPI, recorder, frontend React Flow, migrations

---

## 1. Objetivo e escopo

Levar o PID do canvas à mesma semântica industrial do `fuzzy_loop`: modos, tracking, override, cascata bumpless e anti-windup encadeado, com o shell do ADR-039.

O bloco `pid` existente (ADR-031) **não é alterado**. Esta spec adiciona `pid_loop` ("PID Malha").

Além da paridade com o fuzzy, esta spec tem um objetivo próprio: **sintonia online sem degrau** (§7). A forma incremental exigida pelo ADR-039 D2 torna a alteração de ganhos com a malha em automático segura por construção, e o hot-swap em classe de sintonia (ADR-039 D11) é o caminho concreto de escrita.

### 1.1 Os dois blocos

| | `pid` (existente) | `pid_loop` (novo) |
|---|---|---|
| Portas | `(valor, ok)`: `pv`, `sp` opcional → `out` | `Signal` (ADR-039 §4.1) |
| Modos | nenhum (ADR-031: "não tem máquina de modos") | `MODE_BLK` completo |
| Forma do algoritmo | posicional (`simple-pid`, paralela interna, config ISA) | incremental |
| Anti-windup | clamp de `output_limits` da lib | saturação do integrador do shell |
| Feedforward | não | sim (`bias_in`, ADR-039 D10) |
| Sintonia online | re-instancia o bloco (integral zera ⇒ degrau) | bumpless in-place (classe de sintonia) |
| Uso pretendido | prototipagem, simulação, composição | malha de produção |

### 1.2 Fora de escopo

- Autotuning por relé ou identificação de modelo.
- Bloco seletor para controle override (ADR-039 §9).
- Formas PID não-ISA (ex.: PIDE Rockwell com ganho dependente).
- Agente externo de sintonia adaptativa e seus guardrails (ADR-039 §9).

---

## 2. Premissas — verificadas contra o código

| # | Premissa da v1.0 | Veredito | Efeito aplicado nesta versão |
|---|---|---|---|
| P1 | O `pid` atual é posicional | **Verdadeira** — `simple_pid.PID` devolve saída absoluta (`pid.py:141`) | §3 é conversão, como planejado |
| P2 | Forma ideal/ISA | **Verdadeira na config** — `kc/ti_seconds/td_seconds` ISA, convertidos uma vez para a forma paralela interna (`pid.py:88-91`); equivalentes | §10.2 da v1.0 (conversão série→ideal) removida: não há forma série |
| P3 | Derivada sobre PV | **Verdadeira por default** — `differential_on_measurement=True` (`parse.py`); configurável | Mapeia direto para `GAMMA` (§10) |
| P4 | Sem feedforward | **Verdadeira** — 10 campos, nenhum de bias | §4 vale integral |
| P5 | flow-runtime passa `dt` medido | **Falsa** — `dt` nominal congelado na construção (ADR-031, deliberado) | Resolvida pelo ADR-039 D7: o shell deriva `dt` de `ts`; scheduler e ADR-031 intocados |

---

## 3. Kernel PID incremental

### 3.1 Formulação

Forma ideal (não-interativa) ISA, com ponderação de setpoint, derivada sobre PV, filtro derivativo de 1ª ordem, ganho de gap por **transformação contínua do erro** e derivada robusta a `dt` variável.

Sentido de ação: `s = −1` (direta) ou `+1` (reversa). Transformação de gap, contínua por partes (`GAP_BAND = 0` ⇒ identidade):

```
g(x) = GAP_GAIN·x                                    se |x| ≤ GAP_BAND
     = sign(x)·(GAP_GAIN·GAP_BAND + |x| − GAP_BAND)  senão
```

Erros por termo:

```
d_k   = s·(SP_k − PV_k)                 desvio verdadeiro
dg_k  = g(d_k)                          desvio com gap
e_k   = dg_k                            erro integral
ep_k  = dg_k − s·(1−BETA)·SP_k          erro proporcional (BETA=1 ⇒ ep=dg)
ed_k  = s·(GAMMA·SP_k − PV_k)           erro derivativo, sem gap (GAMMA=0 ⇒ sobre PV)
```

Filtro derivativo (`Tf = TD/N`) e memória de taxa:

```
α      = dt / (Tf + dt)
edf_k  = edf_{k−1} + α·(ed_k − edf_{k−1})
r_k    = (edf_k − edf_{k−1}) / dt
```

Saída do kernel, em % do span de OUT por segundo:

```
du/dt = KC · [ (ep_k − ep_{k−1})/dt  +  e_k/TI  +  TD·(r_k − r_{k−1})/dt ]
```

Três notas de projeto:

1. **Gap por transformação do erro, não por chavear `KC`.** Chavear o ganho na fronteira da banda torna o termo P dependente do caminho (entrar/sair da banda acumula offset). Com `g(·)` estática e contínua, o termo P integra para `KC·(g-parte)` — path-independent. Aplicada só a P e I; aplicá-la ao D reintroduziria chute derivativo residual em degrau de SP dentro da banda (e D é tipicamente zero nas malhas de gap — nível em tanque pulmão).
2. **Memória de taxa no termo D.** A segunda diferença `(edf_k − 2edf_{k−1} + edf_{k−2})/dt²` assume `dt` constante em 3 amostras — com jitter de ±30 % (S11/P14), erra. Guardar `r_{k−1}` em vez da terceira amostra é exato sob `dt` variável.
3. O shell reintegra `u_int += (du/dt)·dt`; anti-windup é a saturação do integrador (ADR-039 §4.7); ganhos multiplicam só incrementos futuros ⇒ alteração bumpless; escrita direta em `u` deixa o controlador alinhado.

Defaults: `BETA = 1.0`, `GAMMA = 0.0` (derivada sobre PV — sem chute em degrau de SP), `N = 8`.

### 3.2 Implementação

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/kernels/pid.py

@dataclass(slots=True)
class PidKernelCfg:
    kc: float                      # %span/EU, > 0; sentido SO via direct_acting
    ti: float = 0.0                # s; 0 desliga a acao integral (convencao ADR-031)
    td: float = 0.0                # s; 0 desliga a acao derivativa
    n:  float = 8.0                # razao do filtro derivativo, Tf = td/n
    beta:  float = 1.0             # ponderacao de SP no termo proporcional
    gamma: float = 0.0             # ponderacao de SP no termo derivativo
    gap_band: float = 0.0          # EU; 0 desabilita
    gap_gain: float = 1.0          # inclinacao de g() dentro da banda
    direct_acting: bool = False


class PidKernel:
    """PID ISA em forma incremental. Contrato: ADR-039 secao 4.5."""

    def __init__(self, cfg: PidKernelCfg):
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self.ep_prev = 0.0
        self.edf     = 0.0
        self.r_prev  = 0.0

    def _gap(self, d: float) -> float:
        b, k = self.cfg.gap_band, self.cfg.gap_gain
        if b <= 0.0:
            return d
        if abs(d) <= b:
            return k * d
        return math.copysign(k * b + (abs(d) - b), d)

    def align(self, u: float, sp: float, pv: float) -> None:
        c = self.cfg
        s = -1.0 if c.direct_acting else 1.0
        dg = self._gap(s * (sp - pv))
        self.ep_prev = dg - s * (1.0 - c.beta) * sp
        self.edf     = s * (c.gamma * sp - pv)
        self.r_prev  = 0.0                 # termo D nulo no proximo scan

    def compute(self, sp: float, pv: float, dt: float) -> float:
        c = self.cfg
        s = -1.0 if c.direct_acting else 1.0

        dg = self._gap(s * (sp - pv))
        e  = dg
        ep = dg - s * (1.0 - c.beta) * sp
        ed = s * (c.gamma * sp - pv)

        p_term = (ep - self.ep_prev) / dt
        self.ep_prev = ep

        i_term = (e / c.ti) if c.ti > 0.0 else 0.0

        d_term = 0.0
        if c.td > 0.0:
            tf = c.td / c.n
            a  = dt / (tf + dt)
            edf_prev = self.edf
            self.edf += a * (ed - self.edf)
            r = (self.edf - edf_prev) / dt
            d_term = c.td * (r - self.r_prev) / dt
            self.r_prev = r

        return c.kc * (p_term + i_term + d_term)

    def validate(self) -> list[str]:
        c, errs = self.cfg, []
        if not math.isfinite(c.kc) or c.kc <= 0.0:
            errs.append("KC_MUST_BE_POSITIVE")   # sentido via DIRECT_ACTING
        if c.ti < 0.0:
            errs.append("TI_MUST_BE_NON_NEGATIVE")  # 0 = integral desligada
        if c.td < 0.0:
            errs.append("TD_MUST_BE_NON_NEGATIVE")
        if c.td > 0.0 and c.n <= 0.0:
            errs.append("N_MUST_BE_POSITIVE")
        if not (0.0 <= c.beta <= 1.0):
            errs.append("BETA_OUT_OF_RANGE")
        if not (0.0 <= c.gamma <= 1.0):
            errs.append("GAMMA_OUT_OF_RANGE")
        if c.gap_band < 0.0 or not (0.0 <= c.gap_gain <= 1.0):
            errs.append("GAP_CONFIG_INVALID")
        return errs
```

**Sobre `align()`.** Igualar `edf` ao valor corrente e zerar `r_prev` faz o termo D ser zero no primeiro scan após a retomada. Sem isso, sair de Manual durante um transitório produz pico derivativo proporcional ao movimento ocorrido no Manual — o defeito mais comum em PIDs feitos do zero.

**Sobre convenções de config.** Duas divergências deliberadas em relação à v1.0, para alinhar com a casa: `TI = 0` desliga a integral (mesma convenção do `pid`/ADR-031 e do `tau = 0` do ADR-026 — internamente equivale a `TI = ∞`); e `KC > 0` obrigatório, com o sentido **exclusivamente** via `DIRECT_ACTING` — dois jeitos de inverter (sinal de ganho + flag) é receita de malha invertida em campo.

**Sobre `direct_acting`.** Aplicado ao erro, conforme ADR-039 §4.5. Para o PID as formas são algebricamente equivalentes; a escolha mantém o contrato uniforme com o `FuzzyKernel`, onde não são.

**Sobre o ganho de gap.** Com `GAP_GAIN` próximo de zero, produz controle de nível por média em tanque pulmão: a malha ignora desvios pequenos e absorve o distúrbio no volume em vez de propagá-lo a jusante.

### 3.3 Unidades

`KC` em **% do span de OUT por EU de PV** — significado físico direto, imune a mudança de escala de PV (coerente com `SPEC_FUZZY_with_SHELL.md` §7). Atenção na migração: o `kc` do bloco `pid` legado é EU de saída por EU de PV — a conversão está na §10. `TI` e `TD` em segundos.

---

## 4. Feedforward (`bias_in`)

A soma pós-integrador é normativa no ADR-039 D10 (o integrador guarda `u_int`; `OUT = u_int + bias`; modos forçados e mudanças de config rebaseiam `u_int`). Aqui ficam os parâmetros:

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `bias_in` | porta `Signal` | Sinal de feedforward/bias, unidades de engenharia |
| `FF_SCALE` | (lo, hi) | Escala do sinal para conversão a % do span de OUT |
| `FF_GAIN` | float | Ganho aplicado ao valor escalado |
| `FF_ENABLE` | bool | Desliga a contribuição sem desconectar a porta |

`bias = FF_GAIN · scale(bias_in.value, FF_SCALE)` quando `FF_ENABLE` e `bias_in.quality == GOOD`. Com qualidade BAD, o bias **mantém o último valor bom** — cair a zero produziria degrau exatamente quando o instrumento falha.

`bkcal_out` não muda: o feedforward é invisível ao bloco a montante — não altera o que a malha pede, altera como ela entrega.

---

## 5. Parâmetros

### 5.1 Herdados do shell (ADR-039)

Mesma lista de `SPEC_FUZZY_with_SHELL.md` §6.1.

### 5.2 Específicos do kernel PID

| Parâmetro | Tipo | Unidade | Padrão | Descrição |
|---|---|---|---|---|
| `KC` | float | %span/EU | — | Ganho proporcional, `> 0` |
| `TI` | float | s | 0.0 | Tempo integral; `0` desliga |
| `TD` | float | s | 0.0 | Tempo derivativo; `0` desliga |
| `N` | float | — | 8.0 | Razão do filtro derivativo, `Tf = TD/N` |
| `BETA` | float | — | 1.0 | Ponderação de SP no termo proporcional |
| `GAMMA` | float | — | 0.0 | Ponderação de SP no termo derivativo |
| `GAP_BAND` | float | EU | 0.0 | Meia-banda da transformação de gap; `0` desliga |
| `GAP_GAIN` | float | — | 1.0 | Inclinação de `g()` dentro da banda |
| `FF_SCALE`, `FF_GAIN`, `FF_ENABLE` | — | — | — | Feedforward (§4) |

### 5.3 Classes de hot-swap (ADR-039 D11)

- **Sintonia** (in-place, preserva modo/`u`/kernel): todos os campos da §5.2 (mudança de `FF_*` rebaseia `u_int` — D10), mais limites/rates/opções da lista compartilhada (`SPEC_FUZZY` §6.3).
- **Estrutural** (re-instancia; aterrissa em `MAN` se calculante): `OUT_SCALE`.

---

## 6. Semântica de cascata

Sem configuração além das ligações. Cascata nível sobre vazão (`OUT_SCALE` do LIC = faixa de SP do FIC, ADR-039 §4.6):

```
LIC.out       ──►  FIC.cas_in
FIC.bkcal_out ──►  LIC.bkcal_in
FIC.out       ──►  opc_write (valvula)
```

Comportamento emergente do protocolo (ADR-039 §4.3/§4.7):

| Situação | Resultado |
|---|---|
| FIC em Man | LIC vai a `IMAN`; `LIC.out` acompanha o SP de trabalho do FIC |
| FIC volta a Cas | LIC volta a `CAS`, sem degrau no SP do FIC |
| FIC saturado no limite alto | `FIC.bkcal_out.hi_limited`; LIC para de integrar naquele sentido |
| PV do FIC em BAD | FIC vai a `MAN`, emite IR; LIC vai a `IMAN` |
| LIC de ação direta saturado | Bits de limitação invertidos no `bkcal_out` (teste P11) |

A inversão dos bits sob ação direta é o único ponto onde o sentido de ação atravessa a fronteira kernel/shell.

---

## 7. Sintonia online sem degrau

No PID posicional, `u_k = KC·ep_k + I_k + D_k`: alterar `KC` produz degrau imediato de `ΔKC·ep_k` na saída — com erro de 5 % e mudança de 20 %, é 1 % do span aplicado ao atuador sem evento de processo por trás. No bloco `pid` atual é ainda mais abrupto: qualquer edição re-instancia o bloco e zera a integral.

Na forma incremental, `KC`, `TI` e `TD` multiplicam apenas o incremento do scan corrente; os incrementos passados já estão acumulados em `u_int` e não são reescritos. A alteração é **bumpless por construção**, não por tratamento especial.

O caminho de escrita é o hot-swap em classe de sintonia (ADR-039 D11): engenharia edita os ganhos no editor de flow, o runtime aplica in-place na próxima varredura, o diff fica auditado no log de eventos. P3/P4 travam a propriedade por teste. Um futuro agente externo de sintonia adaptativa (e seus guardrails: enable, limites, rate-limit, monitor de oscilação, rollback) está registrado no ADR-039 §9 e nasce com spec própria.

---

## 8. Persistência, API e frontend

Reutiliza integralmente `SPEC_FUZZY_with_SHELL.md` §8. Diferenças:

- Config: `PidLoopConfig` em `parse.py`; sem LUT e sem tabela de superfície.
- Faceplate: no lugar do heatmap, aba de sintonia — `KC`, `TI`, `TD`, `BETA`, `GAMMA`, `GAP_*` vigentes (somente leitura; edição é engenharia, no editor de flow).
- Histórico de sintonia: log de eventos (diff de config, ADR-020) — sem endpoint dedicado.

---

## 9. Testes de aceitação

Todos os S1–S17 do ADR-039 §7 devem passar com o `PidKernel` injetado. Adicionalmente:

| ID | Cenário | Critério |
|---|---|---|
| P1 | Degrau de SP, `pid_loop` vs `pid` com sintonia equivalente (§10.1) e mesmo modelo (TFS) | Trajetórias de OUT coincidem dentro de 0.5 % do span ao longo de 300 s |
| P2 | Distúrbio de carga em regime, ambos os blocos | Mesmo critério de P1 |
| P3 | `KC` +30 % via hot-swap com a malha em Auto e erro de 5 % | `\|ΔOUT\| ≤ 0.01 %` no scan da troca |
| P4 | `TI` e `TD` alterados nas mesmas condições | Mesmo critério de P3 |
| P5 | Degrau de SP com `BETA = 1` e `BETA = 0` | `BETA = 0` reduz sobressinal sem alterar rejeição de distúrbio |
| P6 | Degrau de SP com `GAMMA = 0` (gap desligado) | Nenhum pico derivativo no primeiro scan |
| P7 | Auto → Man por 120 s durante rampa de processo → Auto | Nenhum pico derivativo na retomada (valida `align()` + memória de taxa) |
| P8 | Erro sustentado até saturar, depois invertido | OUT deixa o limite em ≤ 1 scan |
| P9 | Feedforward degrada para BAD com FF ativo | Bias mantém o último valor bom; sem degrau em OUT |
| P10 | Man → Auto com feedforward não nulo | Sem degrau (valida o retrocálculo de `u_int`, D10) |
| P11 | Bloco de ação direta saturado em `OUT_HI_LIM` | `bkcal_out.lo_limited == True`, `hi_limited == False` |
| P12 | `GAP_BAND` de 5 % com `GAP_GAIN = 0.1`, ruído de ±2 % | OUT praticamente imóvel dentro da banda; resposta normal fora |
| P13 | `FF_GAIN` alterado via hot-swap com a malha em Auto | Sem degrau em OUT (rebase de `u_int`, D10) |
| P14 | Jitter de `dt` de ±30 % por 300 s | Regime idêntico ao caso sem jitter dentro de 0.5 % |

P1/P2 são a regressão que autoriza a migração: se as trajetórias não coincidirem, a conversão para forma incremental introduziu erro. P3/P4 travam a propriedade da §7.

---

## 10. Migração `pid` → `pid_loop`

Não há migração forçada; o `pid` permanece disponível e inalterado.

### 10.1 Mapeamento de config

| `pid` (ADR-031) | `pid_loop` | Observação |
|---|---|---|
| `kc` (sinal carrega o sentido: negativo = ação direta) | `KC = \|kc\| · 100 / (output_max − output_min)`; `DIRECT_ACTING` = (`kc < 0`) | Conversão de unidades EU/EU → %span/EU; `kc > 0` na simple-pid age em sentido reverso (`e = sp − pv`) — P1 valida o mapeamento de imediato |
| `ti_seconds` (`0` = sem integral) | `TI` (mesma convenção) | — |
| `td_seconds` (`0` = sem derivada) | `TD` | — |
| `proportional_on_measurement` (default `False`) | `BETA = 0` se `True`, `1` se `False` | — |
| `differential_on_measurement` (default `True`) | `GAMMA = 0` se `True`, `1` se `False` | — |
| `setpoint` / porta `sp` | SP de operação (`loop_setpoints`) / `cas_in` | — |
| `output_min`/`output_max` (EU) | `OUT_SCALE = (output_min, output_max)`; `OUT_LO/HI_LIM = 0/100 %` | `u` interno vira % |
| `starting_output` | `OUT_STARTUP` convertido a % via `OUT_SCALE` | — |
| `auto_mode` | — | `TARGET` nasce sempre `MAN` (ADR-039 §4.10); engajar é ato do operador |

### 10.2 Procedimento

1. Transferir a config pela tabela da §10.1.
2. Rodar P1 e P2 contra o bloco original, mesma sintonia convertida, mesmo modelo de processo (TFS).
3. Comissionar em Manual, transferir para Auto, verificar S1/S2 em planta.
4. Só então ligar cascata e, se aplicável, feedforward.

### 10.3 Ordem sugerida de adoção

1. Uma malha simples, não crítica, sem cascata, em Auto.
2. A mesma malha com tracking e override exercitados.
3. Uma cascata de dois níveis.
4. Uma malha com feedforward.
5. Sintonia online via hot-swap como rotina — somente depois de 1 e 2 acumularem operação estável: problema de transferência de modo e problema de sintonia se manifestam parecido no histórico, e diagnosticar os dois juntos custa muito mais que separá-los.
