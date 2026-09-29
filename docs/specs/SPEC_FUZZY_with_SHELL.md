# SPEC — Bloco Fuzzy Malha (`fuzzy_loop`)

- **Versão:** 2.0 · 2026-08-31 (revisão pós-verificação de código; a v1.0 era rascunho com premissas em aberto)
- **Depende de:** ADR-039 (shell de bloco), ADR-024 (exec_order), ADR-029 (bloco fuzzy)
- **Componentes afetados:** `flow-runtime`, `ottima-core` (parse/validate/contracts_export), API FastAPI, recorder, frontend React Flow, migrations

---

## 1. Objetivo e escopo

Disponibilizar controle fuzzy em malhas de produção do OttimaSystem com a mesma semântica de modo, tracking e cascata de um bloco PID de DCS.

O bloco `fuzzy` existente (ADR-029) **não é alterado**. Esta spec adiciona `fuzzy_loop` ("Fuzzy Malha"), que reutiliza o mesmo motor de inferência dentro do shell do ADR-039.

### 1.1 Os dois blocos

| | `fuzzy` (existente) | `fuzzy_loop` (novo) |
|---|---|---|
| Portas | `(valor, ok)` | `Signal` (ADR-039 §4.1) |
| Modos | nenhum | `MODE_BLK` completo |
| Estado entre scans | engine apenas | integrador, filtros, modo |
| Forma | posicional (`entradas → saída`) | incremental (`e, Δe → du/dt`, shell integra) |
| Uso pretendido | prototipagem, estudo, composição | malha de produção |
| Base de regras | `.fll` livre (IN1..INn/OUT1..OUTn posicionais) | `.fll` sujeito ao contrato da §3.2 |
| Alterações previstas | **nenhuma** | — |

O `fuzzy` continua sendo o caminho para desenhar um teste rápido no canvas. O `fuzzy_loop` é o caminho para colocar uma malha em automático em planta.

### 1.2 Fora de escopo

- Aprendizado/adaptação online da base de regras — o `.fll` é configuração, não estado.
- Sintonia automática dos ganhos por agente externo (ADR-039 §9).
- Bloco seletor para controle override (ADR-039 §9).
- Cascata entre flows (multirate) — v1 valida cascata só dentro do mesmo flow (ADR-039 §9).

---

## 2. Premissas — verificadas contra o código

| # | Premissa da v1.0 | Veredito | Efeito aplicado nesta versão |
|---|---|---|---|
| P1 | `fuzzy` usa pyfuzzylite 8.x | **Verdadeira** — `pyfuzzylite==8.0.6`, API snake_case (`fuzzy.py`) | Nomenclatura 8.x mantida |
| P2 | `.fll` armazenado como texto na config | **Verdadeira** — `FuzzyConfig.fll: str` no `graph_json` (`parse.py`) | §8 usa o mesmo mecanismo |
| P3 | flow-runtime passa `dt` medido | **Falsa** — blocos recebem `ts` da fronteira; `dt` nominal é congelado na construção | Resolvida pelo ADR-039 D7: o shell deriva `dt` de `ts` consecutivos; scheduler intocado |
| P4 | Existe tabela de config versionada | **Falsa** — config vive em `graph_json`, sem revisões (ADR-011) | §8 redesenhada: sem `block_revision`; auditoria por eventos; LUT content-addressed |

---

## 3. Kernel fuzzy incremental

### 3.1 Estrutura

Estrutura fuzzy-PI clássica com escalonamento normalizado. O motor de inferência opera sempre em universo normalizado; toda adaptação à faixa do processo acontece nos ganhos do kernel.

```
        Ke                        motor fuzzylite              Ku
e ────────────► sat[-1,1] ──►┐                            ┌──────────► du/dt
                             ├──► e_n, de_n ──► du_n ─────┤
Δe ──► filtro ──► sat[-1,1] ─┘                            │
       TF_DE     Kde                                       (%span/s)
```

Consequência prática: sintonia em campo acontece em `KE`, `KDE` e `KU`. Ninguém edita base de regras com planta rodando.

### 3.2 Contrato do arquivo `.fll`

O `.fll` de um `fuzzy_loop` **deve** satisfazer:

| Requisito | Valor |
|---|---|
| Variáveis de entrada | exatamente duas, nomeadas `e` e `de` |
| Faixa das entradas | `-1.000 1.000` |
| `lock-range` das entradas | `true` |
| Variável de saída | exatamente uma, nomeada `du` |
| Faixa da saída | `-1.000 1.000` |
| `lock-range` da saída | `true` |
| `lock-previous` da saída | `false` |
| `default` da saída | `nan` |
| Blocos de regras | exatamente um |

`lock-previous: false` e `default: nan` são obrigatórios. Com `lock-previous` ativo, o fuzzylite substitui resultado inválido pelo último válido, mascarando buracos na base: a malha parece funcionar por semanas e um dia congela numa região não coberta. O contrato faz o buraco aparecer como alarme no comissionamento (§4.4).

Um `.fll` que não satisfaça o contrato pode ser usado no bloco `fuzzy`, nunca no `fuzzy_loop`. A validação roda nas **mesmas duas camadas do ADR-029**: save (`validate_graph`, erro 422 em pt-BR) e deploy. O template pré-preenchido do bloco novo é a constante `FUZZY_LOOP_DEFAULT_FLL` em `contracts_export.py` (espelho do padrão `FUZZY_DEFAULT_FLL` do ADR-029), exportada ao espelho TS (ADR-034).

### 3.3 Implementação

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/kernels/fuzzy.py

@dataclass(slots=True)
class FuzzyKernelCfg:
    ke: float             # 1/unidade de PV      -> normaliza o erro
    kde: float            # s/unidade de PV      -> normaliza a derivada do erro
    ku: float             # %span/s              -> ganho de saida
    tf_de: float = 1.0    # s, filtro da derivada do erro
    direct_acting: bool = False


class FuzzyKernel:
    """Kernel fuzzy incremental. Contrato: ADR-039 secao 4.5."""

    def __init__(self, engine: fl.Engine, cfg: FuzzyKernelCfg):
        self.eng, self.cfg = engine, cfg
        self._e_in   = engine.input_variable("e")
        self._de_in  = engine.input_variable("de")
        self._du_out = engine.output_variable("du")
        self.reset()

    def reset(self) -> None:
        self.e_prev = 0.0
        self.de_f   = 0.0
        self.eng.restart()

    def align(self, u: float, sp: float, pv: float) -> None:
        self.e_prev = self._error(sp, pv)
        self.de_f   = 0.0

    def _error(self, sp: float, pv: float) -> float:
        return (pv - sp) if self.cfg.direct_acting else (sp - pv)

    def compute(self, sp: float, pv: float, dt: float) -> float:
        c = self.cfg
        e  = self._error(sp, pv)
        de = (e - self.e_prev) / dt

        a = dt / (c.tf_de + dt)             # filtro de 1a ordem, robusto a dt variavel
        self.de_f += a * (de - self.de_f)
        self.e_prev = e

        self._e_in.value  = _sat(e * c.ke, -1.0, 1.0)
        self._de_in.value = _sat(self.de_f * c.kde, -1.0, 1.0)
        self.eng.process()

        du_n = float(np.asarray(self._du_out.value).reshape(-1)[-1])
        if not math.isfinite(du_n):
            return math.nan                  # o shell trata: segura OUT e alarma
        return c.ku * du_n

    def validate(self) -> list[str]:
        errs: list[str] = []
        if not self.eng.is_ready():
            errs.append("ENGINE_NOT_READY")
        errs += _validate_fll_contract(self.eng)     # secao 3.2
        if self.cfg.ku <= 0:
            errs.append("KU_MUST_BE_POSITIVE")
        if self.cfg.tf_de <= 0:
            errs.append("TF_DE_MUST_BE_POSITIVE")
        return errs
```

**Sobre `align()`.** Zerar `de_f` é deliberado: ao sair de Manual, a derivada filtrada carregada de antes da transição não descreve mais o processo — preservá-la produz chute na primeira execução. O erro anterior é realinhado para que a primeira derivada calculada seja próxima de zero.

**Sobre `direct_acting`.** Fica no kernel (ADR-039 §4.5) e é aplicado ao **erro**, não à saída: inverter só a saída exigiria simetria da superfície de controle, o que base de regras autoral não garante.

**Extração do escalar.** `OutputVariable.value` pode ser `float` ou array numpy shape `(1,)` — normalizado antes da checagem de finitude, mesma técnica do ADR-029.

---

## 4. Motor fuzzylite

### 4.1 Ciclo de vida

`Engine` construída **uma vez, na instanciação do bloco** (padrão do ADR-029), nunca por scan:

1. `fl.FllImporter().from_string(fll_source)`.
2. `_validate_fll_contract()` (§3.2) + `engine.is_ready()`.
3. `ENGINE_TYPE` derivado de `engine.infer_type()`.
4. `FLL_HASH = sha256(fll_source)` calculado no save — chave da LUT (§5).
5. Falha em qualquer passo ⇒ bloco nasce em `OOS` com alarme `CONFIG_ERROR` e não sai de lá até config válida.

**Troca do `.fll` é classe estrutural** (ADR-039 D11): o hot-swap re-instancia o bloco; se `ACTUAL` era calculante, o bloco novo **aterrissa em `MAN` com `u` mantido** + evento. Isso substitui o "409 na API" da v1.0 — o hot-swap de flow é atômico e o runtime é a autoridade; trocar a superfície de controle sob uma malha em automático termina, sempre, com a malha segura em Manual.

### 4.2 Concorrência

A `Engine` guarda valor corrente dentro das variáveis: mutável, não reentrante. Regra: **uma instância de `Engine` por instância de bloco** — nunca compartilhada, nem com o mesmo `.fll`. A partição por processo do flow-runtime (`flow_id % N`) mantém todos os blocos de um flow no mesmo processo; a regra vale por construção.

### 4.3 Defuzzificador

| | Mamdani + `Centroid` | Sugeno ordem zero + `WeightedAverage` |
|---|---|---|
| Custo por scan | O(resolução) | O(número de regras) |
| Determinismo | depende da resolução | exato |
| Superfície | suavizada pela agregação | interpolação direta entre consequentes |
| Auditoria | requer amostragem | consequentes são constantes legíveis |

**Recomendação:** Sugeno ordem zero (`fl.Constant` + `fl.WeightedAverage()`) como padrão de produção. Mamdani permanece permitido — com `Centroid(resolution=100)` (teto FUZZY-SEC de 10.000 continua valendo) e cobertura pelo teste de carga F9.

### 4.4 Tratamento de resultado inválido

`du` retorna NaN quando nenhuma regra dispara ou a agregação é indefinida. O kernel propaga NaN; o shell segura `OUT` e emite `KERNEL_INVALID_OUTPUT` com `reason = no_rule_fired | aggregation` (ADR-039 §4.7). Rede de segurança, não modo de operação: a validação de superfície da §5.3 existe para tornar isso impossível em bloco comissionado.

---

## 5. Compilação da superfície de controle (LUT)

**Status: fase K3 (§10).** O bloco funciona sem isso.

### 5.1 Motivação

A 8.x aceita `numpy.ndarray` nas variáveis: um único `process()` avalia a grade inteira no save. Ganhos: tempo de execução determinístico (interpolação bilinear, independente do defuzzificador); superfície inspecionável (heatmap no frontend); validação automática viável (propriedades sobre grade densa são triviais; sobre motor de inferência, não).

### 5.2 Especificação

- Grade padrão 65×65 em `[-1,1]²`; configurável 33..257 por eixo.
- Geração vetorizada, uma chamada a `process()`.
- ~~Armazenamento **content-addressed**: tabela `fuzzy_surface_lut`~~ — **removido na implementação da fase K3, por medição.** A grade é gerada na instanciação do bloco e vive só em memória. Custo medido de `sample_surface` (pyfuzzylite 8.0.6, base de regras padrão): **3,5 ms** por bloco em 65×65 (payload 16,5 KB), 6,5 ms em 129, 21,4 ms em 257 (258 KB) — uma vez por bloco, no deploy. Uma tabela, uma migration, um modelo e um hook de save para poupar 3,5 ms de CPU não se pagam; e o save já amostra a grade para rodar os portões da §5.3, então não há trabalho duplicado a evitar. Se a auditoria da superfície exata que rodou vier a ser requisito (ADR-039 D11 previa isso), a persistência volta como content-addressed por `sha256(FLL_SOURCE)`, que é a forma correta — a decisão aqui é só de custo/benefício, não de desenho.
- Runtime: interpolação bilinear com saturação nas bordas; a LUT **substitui** a inferência, o motor fica carregado só para revalidação/regeração. Entrada não-finita devolve NaN em vez de indexar a grade — mesma saída que a inferência dá, para que a mesma entrada nunca tenha dois destinos (um deles seria `ValueError` derrubando o flow).

### 5.3 Portões de validação sobre a LUT

Executados na geração; falha bloqueia o save da config.

| Portão | Critério | Justificativa |
|---|---|---|
| `NO_NAN` | nenhum NaN na grade | buraco na base de regras |
| `SIGN_CONSISTENCY` | na linha `de_n = 0`: `du_n ≥ −tol` para `e_n > tol` e `≤ tol` para `e_n < −tol` (ação reversa) | superfície que empurra na direção errada é malha instável esperando a região certa |
| `MONOTONIC_E` | `∂du_n/∂e_n ≥ −tol` em toda a grade | ganho negativo local causa oscilação |
| `BOUNDED_GAIN` | `max ∂du_n/∂e_n ≤ GAIN_MAX` | limita o ganho equivalente em malha fechada |
| `NO_DEAD_ZONE` | nenhuma região contígua com `\|∂du_n/∂e_n\| < tol` maior que `DEAD_ZONE_MAX` fora da origem | zona morta larga produz offset permanente |
| `CONTINUITY` | `\|du_n(i+1,j) − du_n(i,j)\| ≤ STEP_MAX` | descontinuidade vira degrau na saída |
| `ORIGIN_ZERO` | `\|du_n(0,0)\| ≤ tol` | superfície que não zera no erro nulo não converge |

É o equivalente fuzzy de conferir a sanidade dos ganhos de um PID antes de ligar a malha. Antes da fase K3, a rede de segurança é §4.4 + o heatmap de comissionamento (§8).

**Por que `SIGN_CONSISTENCY` só na linha `de_n = 0`** (corrigido na implementação da fase K3; a v2.0 pedia a grade inteira). Fora dessa linha a antecipação derivativa **legitimamente** inverte `du`: com o erro subindo rápido (`de_n > 0`), a base manda recuar antes de `e_n` chegar a zero, e o cruzamento de zero de `du_n` desloca proporcionalmente a `de_n` — no `FUZZY_LOOP_DEFAULT_FLL`, medido, `de_n = 0.25` cruza em `e_n = −0.125` e `de_n = 1` em `−0.28`. O critério da grade inteira reprovaria qualquer base com regra de `de`, inclusive a default; e qualquer banda fixa em volta de `de_n = 0` é arbitrária e insuficiente, porque o deslocamento é proporcional, não limitado. A linha `de_n = 0` é onde a lei tem de ser de erro puro e onde "empurrar para o lado errado" é inequívoco — e uma regra de sinal invertido não depende de `de` para existir, então continua sendo pega ali (F4).

---

## 6. Parâmetros

### 6.1 Herdados do shell (ADR-039)

`MODE_BLK`, `in`, `PV`, `SP`, `out`, `MAN_OUT`, `cas_in`, `rcas_in`, `rout_in`, `bkcal_in`, `bkcal_out`, `bias_in` (+ `FF_SCALE`, `FF_GAIN`, `FF_ENABLE`), `trk_in_d`, `TRK_VAL`, `lo_in_d`, `LO_VAL`, `CONTROL_OPTS`, `SHED_OPT`, `SHED_NO_RETURN`, `SP_HI_LIM`, `SP_LO_LIM`, `SP_RATE_UP`, `SP_RATE_DN`, `OUT_HI_LIM`, `OUT_LO_LIM`, `OUT_RATE_UP`, `OUT_RATE_DN`, `OUT_SCALE`, `OUT_STARTUP`, `PV_FTIME`, `MAX_DT`.

### 6.2 Específicos do kernel fuzzy

| Parâmetro | Tipo | Unidade | Padrão | Descrição |
|---|---|---|---|---|
| `KE` | float | 1/EU | — | Escalonamento do erro; `1/KE` é a faixa de erro que satura `e_n` |
| `KDE` | float | s/EU | — | Escalonamento da derivada filtrada do erro |
| `KU` | float | %span/s | — | Ganho de saída; define a velocidade máxima de atuação |
| `TF_DE` | float | s | 1.0 | Constante do filtro da derivada do erro |
| `FLL_SOURCE` | text | — | `FUZZY_LOOP_DEFAULT_FLL` | Base de regras, texto FLL |
| `FLL_HASH` | text | — | derivado | `sha256(FLL_SOURCE)`, somente leitura |
| `ENGINE_TYPE` | enum | — | derivado | `Mamdani`/`TakagiSugeno`, de `infer_type()`, somente leitura |
| `LUT_ENABLED` | bool | — | `false` | Superfície compilada em vez de inferência (fase K3) |
| `LUT_RESOLUTION` | int | — | 65 | Pontos por eixo |
| `RULE_FIRE_COUNT` | int | — | derivado | Regras disparadas no último scan, diagnóstico |

### 6.3 Classes de hot-swap (ADR-039 D11)

- **Sintonia** (in-place, preserva modo/`u`/kernel): `KE`, `KDE`, `KU`, `TF_DE`, limites e rates de SP/OUT, `PV_FTIME`, `SHED_OPT`, `SHED_NO_RETURN`, `CONTROL_OPTS`, `PERMITTED`, `NORMAL`, `FF_GAIN`, `FF_SCALE`, `FF_ENABLE` (com rebase de `u_int`), `TRK_VAL`, `LO_VAL`, `MAX_DT`, `LUT_ENABLED`, `LUT_RESOLUTION`.
- **Estrutural** (re-instancia; aterrissa em `MAN` se calculante): `FLL_SOURCE`, `OUT_SCALE`.

### 6.4 Orientação de sintonia

Ordem recomendada em campo, com a malha em Manual e depois em Auto:

1. `KE = 1 / (erro máximo esperado em EU)` — a faixa de erro coberta sem saturar.
2. `KU` pequeno (1–5 %span/s). Ligar em Auto e observar; `KU` é o análogo do ganho integral — subir até antes da oscilação, recuar 30 %.
3. `KDE` por último, começando em zero; é o análogo da ação derivativa e amplifica ruído.
4. `TF_DE` a partir de 1 s; aumentar se `de_n` estiver ruidoso no diagnóstico.

`RULE_FIRE_COUNT` constante em 1 indica `KE`/`KDE` alto demais: o erro satura e a superfície opera nos cantos, anulando o benefício do fuzzy.

---

## 7. Faixa de erro e unidades

`e` chega ao kernel em unidades de engenharia de PV; `KE` converte para o universo normalizado. Intencional: `1/KE` tem significado físico direto (faixa de erro coberta) e não exige retuning quando a escala de PV muda.

A saída interna é em % do span de OUT; a porta `out` emite EU via `OUT_SCALE` (ADR-039 §4.6).

---

## 8. Persistência, API e frontend

Nada aqui é infraestrutura nova — tudo é a aplicação do ADR-039 §4.10:

- **Config**: `FuzzyLoopConfig` em `parse.py`, dentro do `graph_json` (ADR-011; sem tabela de bloco, sem revisões). Auditoria de mudança: diff de config no evento de update de flow (ADR-020).
- **Migrations**: hypertable `loop_samples` + CAgg 1 min e upsert `loop_setpoints` — ambas entregues pelo plano `pid_loop` (migration `0015_loop_tables`). O `fuzzy_loop` **não acrescenta migration nenhuma**: a superfície não é persistida (§5.2, decidido por medição).
- **Comandos**: `POST /api/operate/{flow_id}/{block_id}/mode|sp|out` — 202-async, `require_operator`, auditados pelo runtime.
- **Introspecção**: `GET /api/operate/loop` (discovery) e `GET /api/operate/loop/{flow_id}/{block_id}` (estado + diagnóstico: `e_n`, `de_n`, `du_n`, `RULE_FIRE_COUNT`, superfície amostrada server-side p/ heatmap — resolução constante de servidor, FUZZY-SEC). Trend: `GET /api/history/loop`. Espelho do ADR-030.
- **Sintonia**: edição de flow (admin), classe de sintonia da §6.3 — sem endpoint dedicado.
- **Nó React Flow**: portas por classe — entradas de processo à esquerda; `bkcal_in` à direita alinhado a `out`; discretos na base; `bkcal_out` à esquerda alinhado a `cas_in` (cascata desenha como par de linhas paralelas). Arestas de retorno tracejadas (ADR-039 D6). Badge de modo com `ACTUAL` + indicador quando `ACTUAL ≠ TARGET`.
- **Faceplate**: layout DCS — barras PV/SP/OUT, botoeira de modo com modos fora de `PERMITTED` desabilitados, `TARGET` e `ACTUAL` separados. Aba de diagnóstico fuzzy: heatmap da superfície com o ponto de operação `(e_n, de_n)` ao vivo — a principal ferramenta de comissionamento.
- **Contratos** novos (`PORT_CONTRACTS`, `LoopState`, `FUZZY_LOOP_DEFAULT_FLL`) exportados ao espelho TS (ADR-034).

---

## 9. Testes de aceitação

Todos os S1–S17 do ADR-039 §7 devem passar com o `FuzzyKernel` injetado. Adicionalmente:

| ID | Cenário | Critério |
|---|---|---|
| F1 | `.fll` viola o contrato da §3.2 | 422 no save; se chegar ao deploy, bloco em `OOS` + `CONFIG_ERROR` |
| F2 | `.fll` com `lock-previous: true` | Rejeitado com código `FLL_LOCK_PREVIOUS_FORBIDDEN` |
| F3 | Ponto de operação em região sem regra | `du = NaN`, `OUT` mantido, `KERNEL_INVALID_OUTPUT(reason=no_rule_fired)` |
| F4 | *(fase K3)* Superfície com sinal invertido em alguma região | Portão `SIGN_CONSISTENCY` bloqueia o save |
| F5 | Degrau de SP de 10 % com `KDE = 0` | Sem sobressinal; erro em regime < 1 % (a ação integral vem do shell) |
| F6 | Mesma malha, `KU` dobrado | Velocidade ~2×, mesmo valor de regime |
| F7 | Duas instâncias com o mesmo `.fll`, entradas divergentes, mesmo scan | Saídas independentes e corretas (isolamento de `Engine`, §4.2) |
| F8 | *(fase K3)* LUT ativa vs inferência direta, 10 000 pontos | Diferença máxima ≤ 0.5 % do span |
| F9 | 50 blocos Mamdani/`Centroid(100)` a **Ts = 0.5 s** | Soma dos steps < 30 % do período; senão, Sugeno obrigatório |
| F10 | `KE`/`KDE`/`KU` alterados via hot-swap com a malha em Auto e erro ≠ 0 | Sem degrau em `OUT` (classe de sintonia + forma incremental) |
| F11 | `.fll` trocado com `ACTUAL == AUTO` | Hot-swap aterrissa em `MAN`, `u` mantido, evento emitido, sem degrau |

F10 é o teste que justifica o D2 do ADR-039: se falhar, o kernel virou posicional em algum ponto. (A v1.0 tinha 100 ms em F9 — inexistente na casa; o menor Ts é 0.5 s, ADR-007.)

---

## 10. Plano de implementação

Pré-requisito: fases 1–3 do shell, entregues sob o ADR-039 — (1) contratos `Signal`/`Mode`/`ControlKernel`; (2) `BlockShell` + kernel stub determinístico + S1–S17; (3) infra compartilhada (canais, recorder, rotas, faceplate base, `loop_setpoints`/`loop_samples`). O `PidKernel` (`SPEC_PID_with_SHELL.md`) vem **antes** do fuzzy por decisão de sequência: P1/P2 ancoram a validação do shell contra o `pid` existente.

| Fase | Entrega | Depende de |
|---|---|---|
| K1 | `FuzzyKernel` + contrato FLL + `FUZZY_LOOP_DEFAULT_FLL`; testes F1–F3, F5–F7, F10, F11 | shell fases 1–3; PidKernel entregue |
| K2 | Nó React Flow + faceplate + heatmap (amostragem server-side) | K1 |
| K3 | LUT content-addressed + portões §5.3; testes F4, F8, F9 | K2 |

---

## 11. Migração `fuzzy` → `fuzzy_loop`

Não há migração forçada; o `fuzzy` permanece disponível e inalterado.

1. Adaptar o `.fll` ao contrato da §3.2. Base posicional (consequentes = posição de saída) precisa ser **reinterpretada como taxa** — os rótulos linguísticos costumam sobreviver; a escala, não.
2. Calcular `KE`, `KDE`, `KU` a partir das faixas da versão posicional.
3. (Fase K3) Rodar os portões da §5.3 sobre a superfície convertida.
4. Comissionar em Manual, verificar a superfície no heatmap com o processo em movimento, e só então passar para Auto.

A conversão posicional → incremental **não é mecânica**: `(e, Δe) → u` e `(e, Δe) → Δu` são leis de controle diferentes. Tratar cada migração como resintonia, com o `fuzzy` original em paralelo para comparação.
