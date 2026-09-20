# ADR-044 — Blocos Lead-Lag e Tempo morto

**Status:** Aceito · 2026-09-20

## Contexto

Compensação dinâmica de feedforward — `G(s) = K·(τ_lead·s + 1)/(τ_lag·s + 1)` e atraso puro de
transporte — só era possível pelo bloco Python-Script: uma instância de código livre por caso,
sem validação no save, sem resumo legível no canvas e sem garantia de que dois flows usam a
mesma discretização. É a mesma motivação que o ADR-026 registrou para os filtros.

O lado do PID já estava resolvido antes desta entrega. O ADR-039 **D10** garante que `bias_in`
(porta genérica, disponível em todo bloco malha) soma posição — não taxa — **depois** do
integrador, de forma bumpless: `OUT = u_int + bias`, com rebase de `u_int` no mesmo scan quando
o bias muda. Logo, nenhuma porta de feedforward nova, nenhum bloco de soma, nenhuma alteração em
`shell/block.py`: a saída do `lead_lag` (tipicamente precedida de `dead_time`) entra em
`bias_in` e o shell já a trata.

## Decisão

Dois blocos utilitários novos na paleta, irmãos de `scaler`/`integrator`, cada um com **uma
entrada (`in`) e uma saída (`out`)**, numéricas, entrada obrigatória:

- **`lead_lag`** — config `gain` (qualquer sinal), `tau_lead ≥ 0`, `tau_lag > 0`, ambos finitos.
  Realizado por **decomposição** sobre o estágio ZOH compartilhado de `lag.py`
  (`out = gain·(r·u + (1−r)·lag.step(u))`, `r = tau_lead/tau_lag`) — nenhuma equação de
  diferenças nova, mesmo pacto de denominador que TFS e Filtro 1ª ordem já têm entre si.
- **`dead_time`** — config `theta ≥ 0`, finito (segundos). `d = round(theta/Ts)`, arredondamento
  half-even (mesma convenção de `validate.py`, TFS e modelo interno do MPC), teto
  `d ≤ MAX_DELAY_SAMPLES` (7200, validado em `validate.py` porque depende de `Ts`). Fila
  `deque[Signal]` — não `float` — primada com a primeira amostra válida; `d = 0` é passagem
  direta.

Os dois seguem as regras gerais de bloco vigentes: `exec_order` (ADR-024), estado preservado no
hot-swap enquanto a config não muda (ADR-011), cold start ⇒ saída nula e inválida, partida sem
salto (primeira saída de `lead_lag` é `gain*u`; a fila do `dead_time` nasce cheia — nunca
zero-fill, que injetaria um degrau em EU absoluta na partida). O resto — degradação sub-Ts,
tratamento de não-finito por bloco, propagação de qualidade — mora nos docstrings dos módulos
(`blocks/lead_lag.py`, `blocks/dead_time.py`), no molde do `scaler`.

## Teto de razão `tau_lead/tau_lag ≤ 10`

A razão `r` **é** o ganho de alta frequência do bloco (pico `K·r` com `gain` incluído), e a
saída do `lead_lag` tipicamente alimenta `bias_in`, somada **depois** do integrador (ADR-039
D10): ruído no distúrbio medido chega à válvula multiplicado por `K·r`, sem nenhuma atenuação
integral. O rate limit de OUT apara o pico, mas ao aparar distorce justamente o transiente de
feedforward que o bloco existia para entregar — e o engenheiro não vê resposta em frequência
nenhuma no canvas, só digita dois números.

`MAX_LEAD_LAG_RATIO = 10.0` (a ordem de grandeza que o DeltaV pratica), validado no parse
(`model_validator` cruzado, `LeadLagConfig`), erro de save acima disso. `gain` fica **fora** do
teto — `K = −3` é legítimo e não diz nada sobre ruído.

Por que aqui o teto existe e no `scaler` não: o `scaler` decidiu não saturar porque over-range é
evidência que o operador precisa ver — errar para o lado de mostrar. Razão lead/lag alta não é
evidência de nada; é amplificador de ruído apontado para uma válvula, e o custo do engano é
mecânico. Quando 10 for genuinamente insuficiente, a saída é cascatear dois blocos — a mesma
resposta que o ADR-026 já deu para filtro de ordem superior.

## Relógio nominal sob overrun

Os dois blocos embutem `Ts` constante, como TFS, `lag.py` e o termo D do `pid.py`; nenhum mede
`dt` de parede. O `integrator.py` é a exceção documentada, porque o erro dele é **permanente** e
visível na conciliação de massa ("integrar o Ts nominal subcontaria em silêncio"). Aqui o desvio
é **transitório**: passado o overrun, o atraso volta ao nominal e nada fica acumulado. Uma
segunda autoridade de tempo justo no bloco que vai em série com os outros quatro seria pior que
todos errarem igual — o `pid.py` já registra que o scheduler é a ÚNICA autoridade de tempo do
laço.

Direção do desvio, registrada porque é a que machuca: `_settle_grid` pula fronteiras perdidas, e
`step()` não é chamado nelas. A fila do `dead_time` anda um slot por chamada ⇒ sob overrun o
tempo morto efetivo **dilata** em tempo de parede. Feedforward atrasado age como um **segundo
distúrbio**, em vez de cancelar o primeiro.

## Hot-swap dá degrau na válvula — sem suavização

Reconfigurar um `lead_lag`/`dead_time` que alimenta `bias_in` de uma malha em AUTO **dá degrau**
na válvula, e a garantia do ADR-039 D10 ("a saída total nunca dá degrau") **não cobre este
caso**.

O mecanismo: `_rebase_bias = True` é escrito num único lugar, `apply_tuning()`
(`shell/block.py:193`) — o hot-swap de sintonia do **próprio** shell. Quando quem é
re-instanciado é o bloco a montante (ADR-011: troca de config descarta estado do bloco alterado,
preserva o dos demais), `bias` muda em `shell/block.py:239` com `_rebase_bias` ainda `False`; o
rebase de `u_int` nas linhas 240-242 não roda; e o salto vai direto para `OUT` por
`u_int + du_dt*dt + bias`, atenuado só pelo rate limit de OUT. O `prime`/preenchimento de fila
que tornam os dois blocos novos bumpless (partida sem salto) só valem **em regime permanente**;
no meio de um transiente há salto de módulo `u[n] − u[n−d]` no `dead_time` e até
`gain·(1−r)·(u − x_velho)` no `lead_lag`.

É consequência **aceita e documentada** desta entrega, não nota de rodapé: reconfigurar um
`lead_lag`/`dead_time` a montante de `bias_in` com a malha em AUTO é ato de engenharia sob malha
fechada. Sem sedação (diferente do `mpc_mode_changed {reason: hot_swap}`, que o ADR-011/A-11
resolve sedando para LOCAL) e sem evento novo: o degrau passa, e fica escrito aqui e nos
docstrings dos dois blocos.

## Consequências

- A paleta cresce de 16 para 18 blocos. Duas linhas novas na tabela de propagação de qualidade
  por bloco do ADR-043 §5 (`lead_lag`, `dead_time`) e dois verbetes novos no GLOSSARY
  (Lead-Lag, Tempo morto) — emendas normativas pendentes de aprovação explícita, fora do escopo
  deste commit.
- O `Literal` de `flow_add_block` (espelho manual de `NODE_TYPES`, ADR-036) vira
  `TipoBlocoLiteral` com teste que o compara a `NODE_TYPES`, para que a próxima deriva apareça
  sozinha em vez de silenciosa.
- `first_order` segue sem guarda de não-finito — um `nan` envenena a recorrência dele para
  sempre. Dívida pré-existente, declarada e deliberadamente fora de escopo aqui; o `lead_lag`
  nasce com a guarda (retenção `min(UNCERTAIN, q_in)`, BAD sem saída boa anterior) porque é
  bloco novo, não porque o débito do `first_order` foi pago.
