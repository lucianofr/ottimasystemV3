# SPEC — Blocos `lead_lag` e `dead_time`

**Data:** 2026-09-20 · **Status:** desenho aprovado, aguardando plano de implementação
**Baseline:** `main` @ `9b9ca56`

## 1. Objetivo

Dois blocos utilitários novos na paleta, irmãos de `scaler`/`integrator`:

- **`lead_lag`** — compensação dinâmica `G(s) = K·(τ_lead·s + 1)/(τ_lag·s + 1)`, equivalente
  ao bloco LDLG do DeltaV.
- **`dead_time`** — atraso puro de transporte, `θ` segundos.

Uso principal: cadeia de feedforward `opc_read → dead_time → lead_lag → bias_in` de um
`pid_loop`/`fuzzy_loop`. Uso genérico: condicionamento de qualquer sinal no canvas.

Hoje isso só é possível com o bloco Python-Script, uma instância de código livre por caso —
sem validação no save, sem resumo legível no canvas e sem garantia de que dois flows usem a
mesma discretização. É a mesma motivação que o ADR-026 registrou para os filtros.

### Por que o lado do PID não muda

O ADR-039 **D10** já resolve a soma do feedforward:

> Feedforward soma **posição**, não taxa (...). O integrador guarda `u_int` (parcela de
> realimentação); `OUT = u_int + bias`. Modos forçados retrocalculam `u_int = clamp(forced) −
> bias`; mudança de config que altera o bias rebaseia `u_int = u − bias_novo` no mesmo scan —
> a saída total nunca dá degrau. **Porta genérica (feedforward, bias de operador, termo de
> outro bloco), disponível em todo bloco malha.**

Logo: nenhuma porta `ff` nova, nenhum bloco de soma, nenhuma alteração em `shell/block.py`.
A saída do `lead_lag` entra em `bias_in` e o shell já a trata de forma bumpless, escalada por
`ff_gain`.

**Alcance exato dessa garantia:** ela vale para a operação normal e para o hot-swap de
sintonia do próprio shell. Ela **não** cobre a re-instanciação de um bloco a montante —
ver D10, que é o preço a pagar por este desenho.

### Não-escopo

Porta de feedforward dedicada no `pid`/`pid_loop`; bloco de soma; filtro de ordem
configurável (a casa já decidiu, no ADR-026, que ordem superior é um bloco por estágio em
série); conserto do `first_order` (ver §9).

## 2. Decisões

### D1 — `lead_lag` é realizado por decomposição, reusando `FirstOrderLag`

$$G(s)=K\,\frac{\tau_l s+1}{\tau_g s+1}=K\Big[\,r+(1-r)\cdot\frac{1}{\tau_g s+1}\,\Big],
\qquad r=\frac{\tau_l}{\tau_g}$$

Implementação: `out = gain * (r*u + (1 - r) * lag.step(u))`, com
`lag = FirstOrderLag(tau_lag, Ts)` de `blocks/lag.py`.

Nenhuma equação de diferenças nova, nenhum estado `u[n-1]`. É a regra que o próprio
`lag.py` documenta — TFS e Filtro 1ª ordem compartilham o estágio "para que a simulação e o
filtro tenham, por construção, a mesma resposta ao degrau". `lead_lag` entra no mesmo pacto:
o denominador dele é bit a bit o denominador dos outros dois.

Consequência de graça: `FirstOrderLag.prime()` dá partida sem salto sem código novo.

### D2 — Partida sem salto, nunca partida em zero

A primeira amostra válida depois de deploy/reset faz `lag.prime(u)`; a saída daquela
varredura é `gain*u`. Motivo idêntico ao escrito no ADR-026: o sinal está em EU absoluta da
planta, e arrancar de zero reportaria "uma temperatura subindo de 0 a 150 °C que ninguém viu
acontecer". Ligado a `bias_in`, isso seria um degrau na válvula.

### D3 — `tau_lag` é estritamente positivo; `tau_lead = 0` é legítimo

`tau_lag` é divisor em `r` e na exponencial da discretização. `tau_lag = 0` com
`tau_lead > 0` é função de transferência imprópria (derivador puro), não passagem direta — a
convenção "`tau = 0` é passagem direta" do ADR-026 **não** migra para cá.

`tau_lead = 0` é lag puro (legítimo). `tau_lead = tau_lag` é ganho puro (legítimo).

Como `tau_lead ≥ 0` e `tau_lag > 0`, `r ≥ 0` sempre — o teto de D4 dispensa valor absoluto.

### D4 — Teto de razão `r ≤ 10`, validado no parse

O ganho de alta frequência do bloco é exatamente `r`, e com `gain` incluído o pico é `K·r`.
Pelo D10 do ADR-039 a saída cai em `bias_in`, somada **depois** do integrador: ruído no
distúrbio medido chega à válvula multiplicado por `K·r`, sem nenhuma atenuação integral. O
rate limit de OUT (`shell/block.py`) apara o pico, mas ao aparar distorce justamente o
transiente de feedforward que o bloco existia para entregar.

O engenheiro não vê resposta em frequência nenhuma no canvas; ele digita dois números.

`R_MAX = 10` (a ordem de grandeza que o DeltaV pratica), erro de save acima disso.

Por que aqui o teto existe e no `scaler` não: o `scaler` decidiu **não** saturar porque
over-range é evidência que o operador precisa ver — errar para o lado de mostrar. Razão
lead/lag alta não é evidência de nada; é amplificador de ruído apontado para uma válvula, e o
custo do engano é mecânico. Quando 10 for genuinamente insuficiente, a saída é cascatear dois
blocos — que é o que o ADR-026 já decidiu para filtro de ordem superior.

**`gain` fica fora do teto.** `K = -3` é legítimo e não diz nada sobre ruído.

### D5 — `gain` aceita qualquer sinal; config via modelo Pydantic

Ganho de feedforward é rotineiramente negativo: distúrbio que empurra a CV para cima pede
correção para baixo na válvula. O `_FILTER_KEYS`/`_parse_filter_config` dos filtros **não
serve**: o dicionário é `dict[str, bool]` com dois ramos (estritamente positivo × não
negativo) e ambos rejeitam negativo.

Os dois blocos usam o padrão vigente de bloco utilitário — modelo Pydantic com
`ConfigDict(extra="forbid", strict=True)`, `Field(allow_inf_nan=False)` e `model_validator`
para a regra cruzada — despachado por `_parse_loop_config`. É exatamente como `ScalerConfig`
resolve `in_max > in_min` e a finitude do ganho derivado.

### D6 — Relógio nominal, não medido

`dead_time` conta **amostras nominais**: `d = round(θ/Ts)`, arredondamento half-even, a mesma
convenção já travada entre `validate.py`, o TFS e o modelo interno do MPC ("o mesmo theta
precisa virar o mesmo número de amostras nos dois códigos de propósito").

Alternativa rejeitada: `dt` medido de `fired_ts`, como o `integrator.py`. A justificativa do
integrador não transfere — lá o erro é **permanente e visível na conciliação de massa**
("integrar o Ts nominal subcontaria em silêncio"). Aqui o desvio é transitório: passado o
overrun, o atraso volta ao nominal e nada fica acumulado. Todo bloco de dinâmica da casa
embute Ts constante, o `pid.py` inclusive, que registra "o scheduler é a ÚNICA autoridade de
tempo do laço". Uma segunda autoridade de tempo justo no bloco que vai em série com os outros
quatro é pior que todos errarem igual.

**Direção do desvio, para o docstring:** `_settle_grid` pula as fronteiras perdidas, então
`step()` não é chamado nelas. A fila anda um slot por chamada ⇒ sob overrun o tempo morto
**dilata**. Feedforward atrasado age como um segundo distúrbio em vez de cancelar o primeiro;
é a direção que machuca, e por isso fica escrita.

### D7 — A fila do `dead_time` nasce cheia da primeira amostra válida

Nunca `deque([0.0] * d)`. O zero-fill do `_Element` do TFS é correto **lá** porque TFS simula
variável-desvio; num bloco autônomo sobre EU absoluta é o mesmo defeito do D2, por `d`
varreduras. O próprio TFS já escreve a regra no `prime()`: "a fila de atraso nasce cheia da
entrada equivalente — senão o atraso injetaria zeros e derrubaria a saída na partida".

`d = 0` é passagem direta pelo par append/popleft, sem desvio no caminho quente (precedente
`_Element`).

### D8 — A fila transporta `Signal`, não `float`

A saída do `dead_time` é a amostra de `d` varreduras atrás; ela carrega a qualidade **daquela**
amostra, não a da entrada corrente. Isso obriga a fila a guardar `Signal` — diferença
estrutural em relação à fila do TFS, que só guarda o valor porque a qualidade da linha é
resolvida por `min()` fora dela.

### D9 — Não-finito nunca entra na recorrência do `lead_lag`

Entrada `inf`/`nan` retém a última saída boa com `min(UNCERTAIN, q_in)`, e **BAD quando nunca
houve saída boa** (`v is None`) — o `_retido` do `pid.py`, verbatim.

Um `nan` na recorrência do lag envenena o estado para sempre: a saída continuaria `nan`
depois do sinal se recuperar. É o argumento que a casa já escreveu duas vezes (`pid.py`
sobre `_integral`, `integrator.py` sobre o total).

No `dead_time` não há recorrência; o valor atravessa a fila e, na emissão, não-finito vira
nulo + BAD (convenção do `scaler`: "nunca `nan`/`inf` com `ok=True` contaminando o consumidor
a jusante").

### D10 — Hot-swap destes blocos DÁ degrau na válvula; a garantia do ADR-039 D10 não cobre

Alterar `tau_lead`/`tau_lag`/`gain`/`theta` com o flow rodando descarta o estado do bloco
(ADR-011 preserva estado só enquanto a config não muda). O `prime` do D2 e o preenchimento
do D7 fazem a instância nova partir da amostra corrente — o que é bumpless **em regime
permanente e só lá**. No meio de um transiente há salto, de módulo `u[n] − u[n−d]` no
`dead_time` e até `gain·(1−r)·(u − x_velho)` no `lead_lag`.

**E a válvula sente.** A §1 cita o D10 do ADR-039 ("a saída total nunca dá degrau") como
razão para não mexer no lado do PID; essa garantia **não se estende a este caso**.
`_rebase_bias = True` é escrito num único lugar, `apply_tuning()` (`shell/block.py:193`) —
ou seja, só no hot-swap de sintonia do **próprio shell**. Quando quem re-instancia é o bloco
a montante, `bias` muda na linha 239 com `_rebase_bias` ainda `False`, o rebase das linhas
240-242 não roda, e o degrau vai direto para OUT por `u_int + du_dt*dt + bias`, atenuado
apenas pelo rate limit de OUT.

Consequência aceita nesta entrega: reconfigurar um `lead_lag`/`dead_time` que alimenta
`bias_in` com a malha em AUTO é ato de engenharia sob malha fechada, da mesma classe do
`mpc_mode_changed {reason: hot_swap}` — que o ADR-011/A-11 resolveu **sedando para LOCAL**,
não fingindo que é bumpless. Aqui não há sedação: o degrau passa.

**Pendência para o plano:** decidir se isso basta documentado, ou se merece evento
(`block_reconfigured` warning quando o consumidor a jusante é porta `bias_in`) ou aviso no
save. Sem decisão, fica documentado e passa.

## 3. Contrato — `lead_lag`

| | |
|---|---|
| Portas de entrada | `in` (num, **obrigatória**) |
| Portas de saída | `out` (num) |
| Config | `gain: float` (qualquer sinal, finito) · `tau_lead: float ≥ 0`, finito · `tau_lag: float > 0`, finito |
| Regra cruzada | `tau_lead / tau_lag ≤ 10` |
| Estado | um `FirstOrderLag` + flag de partida |
| Cold start | `in` sem valor ⇒ saída nula e inválida (`null_outputs`) |
| Degradação | `tau_lag < Ts/10` ⇒ `out = gain*u` (o `FirstOrderLag` já devolve `u`; com `r ≤ 10`, `tau_lead` também é sub-Ts ali — nenhuma das duas dinâmicas é resolvível na amostragem, e `K·u` é a resposta honesta, não ganho ilimitado) |

## 4. Contrato — `dead_time`

| | |
|---|---|
| Portas de entrada | `in` (num, **obrigatória**) |
| Portas de saída | `out` (num) |
| Config | `theta: float ≥ 0`, finito (segundos) |
| Amostras | `d = round(theta / Ts)`, half-even |
| Teto | `d ≤ MAX_DELAY_SAMPLES` (7200), em `validate.py` |
| Estado | `deque[Signal]` de tamanho `d` |
| Cold start | `in` sem valor ⇒ saída nula e inválida; fila intocada, não primada |
| `d = 0` | passagem direta |

## 5. Emendas propostas a documento normativo

Editar `docs/adr/` e `docs/GLOSSARY.md` é item 4 do CLAUDE.md: **tudo desta seção é
proposta**, não alteração aplicada.

### 5.1 — ADR-043 §5 (tabela de qualidade por bloco)

| bloco | regra |
|---|---|
| `lead_lag` | caminho normal: default D6 (pior das entradas consumidas), emissão D9 (substatus/limites zerados). Entrada não-finita ⇒ retém a última saída boa com `min(UNCERTAIN, q_in)`; **BAD quando nunca houve saída boa** (`v is None`, D7) |
| `dead_time` | emite a qualidade **histórica** da amostra desenfileirada, não a da entrada corrente. Valor não-finito na emissão ⇒ nulo + BAD. Fila primada (D7), logo não há janela de `d` nulos |

A linha existente `scaler, lag, first_order, kalman, filtros` **não** cobre o `lead_lag`: o
caminho normal sim, mas o de não-finito é o mecanismo do `_retido`, que tem linha própria na
tabela.

### 5.2 — GLOSSARY (duas linhas novas)

Todo bloco da paleta tem verbete: **TFS** (:48), **Filtro 1ª ordem** (:51), **Filtro
Kalman** (:52), **Scaler** (:53), **Integrator** (:54). Os dois últimos entraram em commit
separado do `b527651` — é por isso que o GLOSSARY não aparece nos 18 arquivos daquele
precedente, e é a razão de ele quase escapar deste checklist.

| termo | verbete proposto |
|---|---|
| **Lead-Lag** | Bloco de uma entrada (`in`) e uma saída (`out`) de compensação dinâmica: `G(s) = gain·(tau_lead·s + 1)/(tau_lag·s + 1)`, discretizado no Ts do flow. `gain` aceita qualquer sinal (feedforward negativo é rotineiro); `tau_lag > 0` (é divisor); razão `tau_lead/tau_lag` limitada a 10 no save, porque ela é o ganho de alta frequência do bloco. Uso típico: compensação de feedforward ligada à porta `bias_in` de um bloco malha. |
| **Tempo morto (bloco)** | Bloco de uma entrada (`in`) e uma saída (`out`) que atrasa o sinal em `theta` segundos, contados em amostras nominais do flow (`d = round(theta/Ts)`, mesmo arredondamento do θ do TFS/MPC). A fila nasce cheia da primeira amostra válida — não injeta zeros na partida — e transporta a qualidade junto do valor: a saída carrega a qualidade da amostra de `d` varreduras atrás. Não confundir com o **θ** dos modelos SOPDT/IOPDT/IFOPDT, que é parâmetro de modelo, não bloco. |

## 6. Validação — divisão parse × validate

| regra | onde | por quê |
|---|---|---|
| tipos, finitude, sinal, `tau_lag > 0`, `theta ≥ 0` | `parse.py` (modelo Pydantic) | independe de Ts |
| `tau_lead/tau_lag ≤ 10` | `parse.py` (`model_validator`) | independe de Ts |
| `round(theta/Ts) ≤ 7200` | `validate.py`, junto ao teto do TFS | **depende de Ts**, que o parse não vê — `validate_graph` até levanta `ValueError` se `ts_seconds <= 0` "para validar o teto de atraso do TFS" |

Reusar `MAX_DELAY_SAMPLES` e o `round` half-even já existentes; não inventar segundo número
nem segunda convenção de arredondamento.

## 7. Sítios de registro

Checklist derivado de `b527651` ("feat(flow): adiciona blocos Scaler e Integrator", 18
arquivos), **mais o GLOSSARY**, que aquele commit deixou para depois (os verbetes de Scaler
e Integrator entraram separados) e que por isso quase escapa de um checklist derivado só
dele.

**Backend**
1. `flowgraph/parse.py` — `NodeType`, `NODE_TYPES`, `_CONFIG_KEYS`, `LeadLagConfig`,
   `DeadTimeConfig`, união `NodeConfig`, despacho para `_parse_loop_config`
2. `flowgraph/__init__.py` — reexport dos dois modelos
3. `flowgraph/validate.py` — portas fixas `in`/`out`, entrada obrigatória, teto de fila
4. `contracts_export.py` — `PORT_CONTRACTS` dos dois tipos
5. `flow-runtime/definition.py` — instanciação (recebe `ts_seconds`, como `first_order`)
6. `blocks/lead_lag.py`, `blocks/dead_time.py`

**Frontend**
7. `features/flows/graph.ts` — `TIPOS_BLOCO`, tipos dos nós, defaults, tipo de porta
8. `features/flows/registro.ts` — paleta (rótulo pt-BR, descrição, defaults)
9. `features/flows/nodes/index.tsx` — componentes e mapa de tipos
10. `features/flows/config/CamposUtilitarios.tsx` + `ModalConfigBloco.tsx` — formulário
11. `lib/contracts.gen.ts` — **gerado**, via `npm run generate:contracts`

**MCP**
12. `ottima_mcp/server.py` — `Literal` de `flow_add_block` e `tests/test_server.py`

**Documento normativo — proposta, não escrita direta (§5)**
13. `docs/GLOSSARY.md` — verbetes **Lead-Lag** e **Tempo morto (bloco)**
14. `docs/adr/ADR-043-qualidade-fim-a-fim.md` §5 — duas linhas na tabela de propagação

O `Literal` do MCP **já está defasado**: 9 tipos contra os 16 do `parse.py` (ADR-036 o torna
sítio de registro real). Ressincronizar os 16 + 2 na mesma passada — sem isso os blocos novos
nascem invisíveis para agente, e a deriva continua sem dono. É conserto de deriva alheia,
declarado aqui para não passar de contrabando.

**Rótulos pt-BR** (GLOSSARY é o cânone): `lead_lag` → "Lead-Lag"; `dead_time` → "Tempo
morto". A chave de config do atraso é **`theta`**, não `dead_time`: o GLOSSARY já fixa θ como
o tempo morto (SOPDT, IOPDT, IFOPDT) e o código o usa em `SopdtParams.theta`/`IopdtParams.theta`
— `{"type": "dead_time", "data": {"dead_time": 30.0}}` inventaria sinônimo para termo já
fixado, o que o CLAUDE.md proíbe explicitamente.

## 8. Testes

**Unitário, `lead_lag`** — resposta ao degrau contra a analítica, por igualdade e não
aproximação (é o que o TFS já assevera para o estágio compartilhado); `tau_lead = 0` reproduz
o `first_order`; `tau_lead = tau_lag` é ganho puro; partida sem salto (primeira saída =
`gain*u`); degradação sub-Ts; retenção em não-finito com `min(UNCERTAIN, q_in)` e BAD sem
saída boa anterior; `reset()` volta ao não-primado.

**Unitário, `dead_time`** — atraso de exatamente `d` varreduras; `d = 0` é passagem direta;
fila primada não emite nulo nem zero na partida; qualidade histórica acompanha a amostra, não
a entrada corrente; não-finito na emissão vira nulo + BAD.

**Parse** — sinal do ganho aceito nos dois sentidos; `tau_lag ≤ 0` reprovado; `r > 10`
reprovado; não-finito reprovado em todo campo; chave desconhecida reprovada.

**Validate** — `round(θ/Ts) > 7200` reprovado, com a mensagem nomeando θ, Ts e o teto.

**Frontend** — `utilitarios.check.ts` no molde existente: presença na paleta, rótulos, uma
entrada e uma saída, defaults que passam no save, round-trip da config.

**Gate** — `npm run generate:contracts` + `git diff --exit-code` (o contrato gerado é parte do
CI hermético, ADR-035).

## 9. Dívidas observadas, deliberadamente não consertadas aqui

- **`first_order` não guarda não-finito.** Faz `float(sample.v)` e entra na recorrência; um
  `nan` envenena o estado para sempre. O `lead_lag` nasce com a guarda (D9); o `first_order`
  fica como está — é deriva alheia ao pedido.
- **`Literal` do MCP defasado** (§7) — este sim entra, porque o bloco novo não funciona sem.

## 10. Artefato de decisão

Recomendação: **ADR-044** curto cobrindo os dois blocos. Não pelo bloco em si — `b527651`
provou que a casa não escreve mais um ADR por bloco (`constant`, `scaler`, `integrator`,
`bus_publish` e `bus_subscribe` não têm) — mas porque três decisões aqui sobrevivem ao código
e duas delas emendam documento normativo: o teto de razão (D4), o relógio nominal sob
overrun (D6) e as emendas da §5 (ADR-043 §5 e GLOSSARY). O resto vai em docstring de módulo,
como o `scaler`.

Próximo número livre verificado em **todas** as refs (`git log --all --diff-filter=A` sobre
`docs/adr/ADR-*`): o máximo é ADR-043, logo **ADR-044**.
