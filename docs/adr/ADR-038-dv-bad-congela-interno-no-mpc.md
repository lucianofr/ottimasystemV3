# ADR-038 — DV com qualidade BAD congela internamente no MPC (default fixo, sem config)

**Status:** Aceito · 2026-08-18

## Contexto

O bloco MPC trata invalidez de entrada com um gate global: CV, Restrição e DV com `ok=false`
derrubavam a varredura inteira (`valid=False` ⇒ `input_valid=false`, solve pulado, MVs
congeladas, evento `mpc_input_invalid`). Para CV/Restrição isso é correto — são linhas do
solve e têm fail actions com simulação (RF-613). Para DV não: a DV entra no modelo como
`_tvp` constante no horizonte (spec F4 §3.2, "DV futura = último valor medido"), ou seja, é
feedforward medido. Uma leitura ruim de DV não corrompe o estado do algoritmo — congela o
feedforward, só isso.

Pedido direto do operador: DV BAD não pode derrubar o bloco. O MPC deve continuar rodando
com o último valor bom da DV.

## Decisão

### DV sai do gate global de validade; amostra ruim congela internamente

Em `MpcBlock.step()` (services/flow-runtime), a cláusula `all(samples[dv_id].ok for dv_id in
self._dv_ids)` sai do cálculo de `valid`. O loop de atualização de `_last_measured` já pulava
amostras não-ok (`if not sample.ok: continue`) — com a cláusula removida, uma DV BAD
simplesmente deixa `_last_measured[dv_id]` inalterado (freeze no último valor bom), e o
`SolveRequest.d` continua levando esse valor. CV/Restrição/MV seguem exatamente como antes.

### Ação default fixa — sem `fail_action`, sem campo novo em `DvVar`

Não é uma ação configurável: DV não ganha `fail_action`/`fail_timeout_s` em
`packages/ottima-core/src/ottima_core/flowgraph/mpc_config.py`, não há migration, não há
mudança de frontend/TS, e a DV continua fora de `_avaliar_fail_actions` (o mapa de fail
actions segue cobrindo só rows + MVs). Sem evento novo: DV ruim é dado cíclico degradado,
não invalidez.

### Cold input e DV nunca medida

`v=None` em DV continua passando pelo gate universal de cold start (`has_cold_input`):
saídas nulas, nada avaliado. DV BAD antes da primeira amostra boa: o `d` despachado ao
solver usa o default existente de `_last_measured` (`0.0`, o mesmo valor que `_build_state`
já reportava) — alinhamento do `_run_frontier` com o padrão `.get(var_id, 0.0)` já usado no
estado publicado, no lugar do acesso direto que levantaria `KeyError` nesse canto (o gate de
arme do supervisor já impede o caminho em produção, mas o bloco não deve quebrar a varredura
se um `command()` direto o alcançar).

## Consequências

- (+) DV BAD não invalida mais o bloco: `input_valid` segue true, o solve continua e as MVs
  não congelam por causa de distúrbio; o operador vê a DV reportada constante (último valor
  bom) até a qualidade voltar, e o valor novo volta a fluir na cura.
- (+) Nenhum campo novo, nenhum evento novo, nenhuma migration — diff cirúrgico no
  `step()` do bloco.
- (−) Uma DV ruim prolongada congela o feedforward indefinidamente (sem timeout): o modelo
  segue predizendo com um distúrbio desatualizado. Aceito por decisão do operador —
  feedforward parado não impacta a estabilidade do algoritmo (bias de realimentação
  continua corrigindo o modelo).
- (−) Operador não recebe nenhum alerta dedicado de "DV ruim" (sem evento novo, por
  decisão); a degradação fica visível só pela qualidade da tag nas telas/trends existentes.
