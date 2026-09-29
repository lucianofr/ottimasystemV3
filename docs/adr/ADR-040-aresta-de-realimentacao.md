# ADR-040 — Aresta de realimentação explícita (quebra de ciclo por opt-in)

**Status:** Aceito · 2026-09-14 · **Emenda estreita ao ADR-024** (habilita o laço de realimentação que o ADR-024 §Consequências deixou como "decisão futura"; a proibição de ciclo passa a valer só para aresta **não** marcada) · Relacionado: ADR-007, ADR-011, ADR-022, ADR-026, ADR-031, ADR-039 · RF-302 (texto inalterado)

## 1. Contexto

O ADR-022 criou o bloco TFS para "fechar a malha sem PLC nem servidor OPC real", e o ADR-031 nomeia como caso de uso do bloco PID as "malhas inteiramente computadas (TFS, script)". Nenhum dos dois é construtível no canvas: ligar `TFS.y1` em `PID.pv` fecha ciclo no dígrafo e o editor recusa a ligação (`validate.py::_check_cycles`, espelhado em `graph.ts::motivoRecusa`).

A única malha fechada que existe hoje — a suíte de aceite MPC↔TFS do RNF-09 — só escapa porque fecha **pelo OPC**: a MV vai à tag, o espelho volta por um `opc_read` e alimenta a TFS (`tests/e2e/conftest.py::grafo_mpc_tfs`, que documenta a recusa em comentário). Isso exige servidor OPC com tag escrevível para simular algo que é 100% interno ao canvas.

O ADR-024 já previu o destravamento e o adiou: *"com ordem explícita, laços de realimentação com atraso de 1 scan tornam-se tecnicamente executáveis; habilitá-los é decisão futura"*. O RF-302 nunca proibiu ciclo — proíbe "ciclos **sem quebra explícita**". Faltava definir o que é a quebra. O ADR-039 D6 já abriu a primeira: aresta com destino `bkcal_in` sai da detecção de ciclo, porque "sem isso o protocolo é inconstruível no canvas" — mesmo argumento, resolvido caso a caso.

## 2. Decisão

**D1 — A quebra explícita é um atraso unitário com condição inicial, declarado na aresta.**
A aresta do `graph_json` ganha o campo opcional **`feedback_init: number | null`**. Não-nulo (finito) ⇒ a aresta é de **realimentação**; ausente ou `null` ⇒ aresta comum, e a proibição de ciclo do ADR-024 continua valendo para ela integralmente.

Um único campo, e não par `flag` + `valor`: aresta de realimentação sem condição inicial não é representável — o estado inválido deixa de existir.

**D2 — Efeito na validação:** aresta de realimentação é excluída da detecção de ciclo **e** do aviso de inversão de `exec_order`, exatamente como a aresta de retorno `bkcal_in` do ADR-039 D6. Toda a demais validação continua: tipo de porta, handle existente, no máximo uma aresta por porta de entrada, entrada obrigatória conectada.

E uma regra própria: **`feedback_init` só é legal em aresta que de fato fecha ciclo** — o destino tem de alcançar a origem pelas outras arestas, a mesma aferição que o espelho do editor faz antes de pedir a confirmação. Sem ela a chave seria um injetor de valor sintético, porque a semente é entregue com `ok = True`: numa aresta comum a caminho de um `opc_write` mandaria ao PLC um número que planta nenhuma produziu (contra o "falha sempre para o lado seguro"), e numa entrada de MPC faria a partida bumpless calcular contra uma posição fabricada — o furo que o ADR-028 fechou. O gesto do editor nunca produz isso; `POST /api/projects/import` (ADR-012) e PUT de `graph_json` cru produzem, e é lá que a barreira importa. Num laço em que duas arestas foram marcadas, cada uma é justificada pela outra — as duas são realimentação de fato.

**D3 — Efeito na execução:** nenhum. O motor continua executando estritamente por `exec_order` (ADR-024), sem topologia. O atraso de 1 varredura da aresta que vai "contra" a ordem é o que o ADR-024 §Consequências já definiu — este ADR não cria semântica de execução nova.

**D4 — `feedback_init` é a condição inicial do atraso, não enfeite.**
A **leitura** da entrada alimentada por uma aresta de realimentação entrega `v = feedback_init, ok = True` **enquanto a porta de origem nunca tiver produzido valor**. A semente é desarmada na primeira amostra com valor e nunca mais volta.

Sem isto o laço é inexecutável, não apenas frio: `has_cold_input` (`blocks/base.py`) faz todo bloco devolver saída nula enquanto alguma entrada conectada for `v = None`, e num ciclo essa invalidez se auto-alimenta — a malha ficaria inválida **para sempre**, não por uma varredura. Como todo ciclo aceito contém ao menos uma aresta marcada (senão a detecção de ciclo o recusa), todo ciclo aceito parte de um estado definido. É a condição inicial que qualquer bloco de atraso unitário de FBD/Simulink exige.

Três detalhes que **não** são de implementação, e sim parte da decisão:

1. **Na leitura, não na tabela de portas.** Semear a porta de origem não sobrevive: a varredura grava toda saída de `step()`, e bloco de entrada fria devolve `null_outputs` — a origem apagaria a própria semente antes de alguém lê-la, e o laço partiria ou não dependendo de qual aresta do ciclo o usuário desenhou por último.
2. **Chaveada pela porta de DESTINO.** É única por construção (uma aresta por porta de entrada), então não existe empate entre sementes; a porta de origem pode alimentar várias arestas.
3. **Semente de partida, não fallback de invalidez.** Depois da primeira amostra válida, sinal ruim propaga como em qualquer outra aresta. Manter a semente como rede permanente faria um laço com sinal degradado exibir a condição inicial como se fosse dado bom — invalidez mascarada é o oposto do que o ADR-037/ADR-028 fixaram para o resto do sistema.

**D5 — Editor: opt-in no gesto, nunca automático.**
A ligação que fecharia ciclo deixa de ser recusada em silêncio: o editor pede confirmação com o valor inicial (default `0`) e só então cria a aresta, já marcada. Aresta de realimentação é renderizada **tracejada** (mesma classe `aresta-retorno` do `bkcal_in`), inclusive em modo de edição. Ligação que viola qualquer outra regra continua recusada como antes — a confirmação só aparece quando o ciclo é o **único** impedimento.

**D6 — Sem migração e sem canal novo.** Campo aditivo e opcional: `schema_version` do JSON de projeto permanece 1 e todo `graph_json` já gravado continua válido (mesma regra do `exec_order` no ADR-024). Nenhum canal do barramento muda.

## 3. Alternativas descartadas

- **Derrubar a detecção de ciclo** (aresta invertida por `exec_order` já seria a quebra): diff menor — só deleção — mas perde a rede contra ciclo acidental num flow grande, e não resolve o D4: o laço continuaria travado em `COLD`. Descartada no gate de decisão.
- **Isentar arestas cuja origem é bloco TFS:** resolveria só a simulação, por tipo de bloco, deixando de fora a malha computada legítima (PID sobre Script, filtro em cascata) que o ADR-031 nomeia. Critério arbitrário.
- **Manter o round-trip por OPC como caminho oficial:** exige servidor OPC com tag de rascunho para simular o que é interno ao canvas; mantém o ADR-022 e o ADR-031 parcialmente inconstruíveis.
- **Tratar entrada `COLD` como zero no TFS:** mascararia dado ruim em todo uso normal do bloco (ADR-022 distingue "ganho zero" de "invalidez" de propósito) para resolver um problema que é da aresta, não do bloco.

## 4. Consequências

- (+) Simulação de processo com PID/filtros/Script fecha dentro do canvas, sem PLC, sem servidor OPC e sem tag de rascunho — o que o ADR-022 prometeu e o ADR-031 pressupõe.
- (+) A quebra é visível em três camadas: tracejado no canvas, campo no `graph_json`, confirmação no gesto. Ciclo acidental continua recusado.
- (+) O aceite MPC↔TFS (RNF-09) não muda: fechar pelo OPC continua válido e continua sendo o caminho que exercita o `opc-worker`.
- (−) Um laço mal sintonizado agora é construtível inteiramente no canvas e pode divergir numericamente (saída → ±inf) sem nenhum PLC no caminho. É simulação: não há escrita OPC envolvida a menos que o engenheiro ligue um `opc_write`, e aí valem todas as travas do ADR-009/010/017, inalteradas.
- (−) O valor de `feedback_init` é responsabilidade do engenheiro: um valor absurdo (PV inicial fora da faixa) produz um transiente de partida absurdo. Preço aceito — é a mesma natureza do `y0` do TFS.
