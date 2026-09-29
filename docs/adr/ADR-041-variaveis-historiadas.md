# ADR-041 — Variáveis historiadas

**Status:** Aceito · 2026-09-14

## Contexto

Hoje só duas origens alimentam a hypertable `samples`: leitura OPC-UA (`opc.values.<conn_id>`,
opc-worker) e tag calculada (`calc.values`, calc-worker, ADR-033). Nenhuma delas cobre o valor
**interno** de uma porta de bloco do flow — a saída de um Filtro Kalman, o `OUT` de um Script, a
entrada `pv` de um PID — que hoje só existe ao vivo, no canal `flow.status.<flow_id>` (`ports`,
RF-404), sem persistência nenhuma. O usuário quer marcar, no editor de flow, portas de entrada ou
de saída de blocos para serem gravadas ciclicamente e aparecerem na lista de séries da página
TREND, do mesmo jeito que qualquer tag OPC ou tag calculada. Sete decisões de arquitetura ficam
fixadas aqui.

## Decisão

### D1 — Linha em `tags` + tabela `historized_vars`, não hypertable própria

Uma **variável historiada** é uma linha em `tags` com `connection_id IS NULL` e `project_id`
preenchido — a mesma forma da tag calculada (`ck_tags_owner`, ADR-033 D1, já aceita essa forma sem
alteração de constraint) — mais uma linha em `historized_vars(tag_id PK → tags.id ON DELETE
CASCADE, flow_id → flows.id ON DELETE CASCADE, block_id, port)`, com `UNIQUE(flow_id, block_id,
port)`: uma porta é historiada no máximo uma vez.

Compartilhar o id space de `tags` é o que faz `samples`, `/api/history`, retenção e a lista do
TREND funcionarem **sem nenhuma alteração de código** — todos operam por `tag_id`, cegos à origem
do valor. Exatamente o mesmo argumento do ADR-033 D1, reaplicado.

**Alternativa rejeitada 1 — hypertable própria no padrão `loop_samples`/`fuzzy_samples`.** Rejeitada
por custo estrutural, não por preferência estética: exigiria (a) um key space próprio para não
colidir com `tags.id` dentro da mesma família de séries, (b) uma rota de histórico própria
(`/api/history` opera por `tag_id` contra `samples`, não sabe ler uma segunda tabela), (c) entrada
nova na tupla `_HYPERTABLES` que hoje governa a retenção (RF-801) — mais uma política, mais um
`drop_chunks`, mais uma superfície para a página Configurações — e (d) uma segunda fonte de dados
para popular a lista do seletor do TREND, que hoje é só `SELECT ... FROM tags`. Compartilhar
`tags`/`samples` herda as quatro coisas de graça.

**Alternativa rejeitada 2 — flag dentro do `graph_json`.** Marcar a porta historiada como um campo a
mais na config do nó (`FlowNode`) foi descartada porque `FlowNode`/os schemas de config de bloco são
`extra="forbid"` (rejeitam campo desconhecido no save) e, mais grave, um `tag_id` gerado pelo banco
**não sobrevive** a export/import — o bundle é JSON portável entre instalações (ADR-012), sem ids
internos, e reconstruir a variável historiada a partir do `graph_json` puro reabriria o problema que
D5/D6 resolvem (nome estável, cascata de remoção) num lugar sem constraint de banco nenhuma para
impor unicidade ou integridade referencial.

### D2 — Produtor é o flow-runtime, canal novo `flow.values`

Quem calcula o valor publica; quem grava, grava cego. O `flow-runtime`, ao terminar de resolver os
valores de porta de uma varredura, publica no canal fixo (sem sufixo) `flow.values` um `OpcValue`
verbatim (`{tag_id, ts, value, quality}`, mesmo schema de `opc.values`/`calc.values`) para cada
porta historiada daquele flow. O `recorder` consome com o MESMO `ingest_sample` que já atende
`opc.values.*`/`calc.values` — nenhuma rota nova no pipeline, nenhuma interpretação de payload
diferente.

**Alternativa rejeitada — recorder assinando `flow.status.*` e resolvendo `(flow_id, block_id,
porta) → tag_id` com cache.** Rejeitada porque quebraria a invariante de "escritor cego" do
recorder (o próprio docstring de `pipeline.py` documenta o pipeline como dumb pipe, ADR-037):
o recorder passaria a conhecer a estrutura de `ports` de `flow.status` e a decidir SE grava, não só
COMO grava. Pior, `flow.status.<flow_id>` carrega `ports` de **toda** porta de **todo** bloco do
flow a cada varredura — Ts pode ser 0,5 s (RF-303) —, então o recorder teria de parsear o payload
inteiro de cada flow a cada scan só para achar as poucas portas historiadas, e invalidar/reconstruir
o cache a cada CRUD de variável historiada e a cada hot-swap (ADR-011) do flow. Produzir o valor já
resolvido no canal certo — como a tag calculada já faz — é mais barato e mais simples do que fazer o
consumidor final rederivar a mesma informação.

### D3 — Cadência `max(Ts_flow, 1 s)`, throttle na origem; "1 Hz" é teto, não taxa

O flow-runtime publica a porta historiada, no máximo, uma vez por varredura (`Ts_flow`), e nunca
mais rápido que 1 Hz — `Ts ∈ {0,5; 1; 2; 5; 10; 30; 60}` s (RF-303): um flow com `Ts = 0,5 s` grava a
1 Hz (throttle na origem reduz a cadência ao teto), um flow com `Ts = 60 s` grava 1 linha a cada
60 s, e isso é o comportamento CORRETO, não uma degradação — a variável historiada segue a
granularidade real do scan cycle do flow que a produz, com um teto que impede um flow rápido de
inundar `samples` a uma taxa acima da que qualquer outra série do sistema sustenta.

### D4 — `PortValue` inválida vira `value=0.0, quality=2`; booleano vira `1.0`/`0.0`

`PortValue.v` é `float | bool | None`; `OpcValue.value` é `float` **estrito** — contrato
compartilhado com `opc.values`/`calc.values`, usado por todo consumidor do barramento e pela rota
de histórico. Alargar `OpcValue.value` para aceitar `None` só para este produtor mudaria um
contrato que três outras origens dependem de manter estreito. Em vez disso, o flow-runtime traduz na
borda: `PortValue(ok=False)` ou `PortValue(v=None)` publica `value=0.0, quality=2` (BAD); `v: bool`
vira `1.0`/`0.0` explícito antes de sair no `OpcValue`.

O `recorder` já sabe o que fazer com `quality=2`: `ingest_sample` grava `value = NULL` nesse caso
(ADR-037), preservando `ts`/`tag_id`/`quality` na mesma cadência — sem essa troca, uma porta que
passa por um trecho `ok=False` do scan (cold start, exceção de script, `nan`/`inf` de filtro)
gravaria `0.0` como se fosse um dado real, e o trend desenharia uma reta chapada em zero em vez de
abrir o gap que hoje representa "sem dado válido" (o cliente só abre buraco quando lê `q===2` ou
valor ausente, `useHistory.ts`, ADR-037).

### D5 — Ciclo de vida: a cascata só corre `tags.id → historized_vars.tag_id`

`historized_vars.tag_id` é FK `ON DELETE CASCADE` para `tags.id` — nunca o inverso. Logo, TODA
remoção de variável historiada — rota `DELETE /api/historized-vars/{tag_id}`, poda automática no
save de um flow (porta historiada que deixou de existir no grafo), remoção do flow inteiro — apaga a
**linha de `tags`**, que cascateia e leva `historized_vars` junto. Apagar só a linha de
`historized_vars` e deixar a de `tags` para trás produziria uma tag órfã: eterna no seletor de
séries do TREND (que lista por `tags`, não por `historized_vars`), invisível como variável historiada
na tela de engenharia, e fatal no export — nenhuma forma de `BundleTag` casaria com uma tag
`connection_id IS NULL` sem registro de origem (nem calculada, nem historiada).

### D6 — Nome congela no cadastro; namespace compartilhado com a tag calculada

O nome grava no momento do cadastro como `f"{flow.name}.{label or block_id}.{port}"`; colisão com o
índice único parcial `uq_tags_project_name` (`project_id, name`) tenta o fallback
`f"{flow.name}.{block_id}.{port}"`; colisão de novo ⇒ HTTP 409 (o cadastro não inventa um terceiro
sufixo automático). O mesmo índice que hoje protege o nome da tag calculada (ADR-033 D6/`ck_tags_
owner`) protege a variável historiada — as duas naturezas de tag sem `connection_id` dividem o
mesmo namespace de nome por projeto.

Renomear o flow ou o label do bloco **depois** do cadastro **não** renomeia a série: o nome já está
gravado em `tags.name` e é isso que aparece no histórico e no CSV exportado. Rastrear o nome ao vivo
do flow/bloco quebraria a rastreabilidade de uma série no meio do seu histórico — o mesmo motivo
pelo qual a tag calculada e a tag OPC também não são renomeadas por trás quando a conexão ou o
projeto mudam de nome.

### D7 — Porta de entrada sem aresta é recusada no cadastro (422)

O cadastro de variável historiada valida a existência da porta contra `ottima_core.flowgraph.
graph_ports(graph)` — a mesma fonte de verdade de "esta porta existe" usada pelo editor, que cobre
portas dinâmicas de blocos como MPC/Script/Fuzzy — e recusa com HTTP 422 uma porta de **entrada**
que não tem aresta ligada nela no grafo do flow no momento do cadastro. Uma entrada desconectada
fica **COLD para sempre** no runtime (nunca recebe valor, `has_cold_input`/ausência de produtor) —
sem essa recusa, a variável historiada gravaria ~86 mil linhas `NULL` por dia (1 Hz × 86400 s) sem
jamais carregar um dado, pura carga morta em `samples` e no seletor do TREND. Porta de **saída**
não tem essa restrição — todo bloco produz sua saída, ligada ou não a jusante.

## Fronteira da entrega

Fora desta decisão, deliberadamente:

- **Ponta viva no `/ws` para variável de flow.** O TREND adensa a exibição só pelo poll do
  histórico (`/api/history`), como qualquer tag OPC sem assinatura ativa — sem canal ao vivo
  dedicado. O canal `flow.values` já existe e já carrega o valor a cada publicação; expor uma
  assinatura filtrada por `tag_id` no `/ws` (no padrão que `opc.values` já tem, decisão F6 A-1) é
  **aditivo** depois, sem mudança de schema nem de produtor.
- **EU digitada no cadastro.** A unidade não é campo de formulário: o cliente envia a EU que o
  canvas já deriva da porta (saída declarada do bloco ou herança pela aresta) e ela congela junto
  com o nome. Não há rota de edição da variável historiada — mudar nome, porta, EU ou flow depois
  do cadastro não é suportado (D6 já congela o nome; reabrir só a EU sem reabrir o resto é fatia
  separada, não pedida).
- **Porta de bloco `mpc` pela UI.** O backend aceita (as portas dinâmicas do `mpc` saem do mesmo
  `graph_ports`), mas o bloco MPC tem modal próprio e a seção "Historiar portas" vive no modal
  genérico — então não há entrada na interface para CV/MV/Restrição/DV nem para as portas fixas
  `local`/`auto`. Justificativa de proporcionalidade: as variáveis do MPC já têm histórico
  dedicado (`mpc_samples`/`mpc_samples_1m` e a tendência da tela de operação, RF-703), então o
  furo é de conveniência, não de capacidade. Fechar exige só repetir a seção no modal do MPC.
- **Historiar estado interno de bloco que não seja porta.** Só entrada/saída tipadas do grafo
  (`graph_ports`) são elegíveis — variável interna de um kernel (ex.: termo integral do PID, estado
  do Kalman) não é porta e fica fora do escopo desta decisão.

## Consequências

- (+) `samples`, `/api/history`, retenção (RF-801) e a lista de séries do TREND funcionam para
  variável historiada sem nenhuma alteração de schema ou de rota — herdam tudo por compartilhar o id
  space de `tags`, exatamente como a tag calculada (ADR-033).
- (+) O recorder segue "dumb pipe": grava cego por `tag_id`, sem saber se a origem é OPC, cálculo ou
  porta de flow (ADR-037 preservado).
- (+) Reaproveita `graph_ports` como única fonte de verdade de "porta existe", sem uma segunda
  validação de grafo divergente da do editor.
- (+) A recusa de porta de entrada fria (D7) evita uma classe inteira de série 100% `NULL` sem
  precisar de limpeza posterior.
- (−) Nome congelado no cadastro (D6): renomear flow/bloco não propaga ao histórico — o operador
  precisa saber que a série "velha" continua com o nome antigo; aceito porque a alternativa
  (rastrear nome) quebra rastreabilidade de série no meio do histórico.
- (−) Cadência "1 Hz teto" (D3) significa que um flow de `Ts = 60 s` grava uma variável historiada
  bem mais devagar que o costume visual de "trend em tempo real"; documentado como comportamento
  esperado, não bug.
- (−) `PortValue` inválida vira `quality=2` em vez de um terceiro estado próprio de "porta nunca
  calculada" — indistinguível, em `samples`, de qualquer outra leitura ruim; aceito pelo mesmo
  raciocínio do ADR-037 (NULL/BAD é a convenção única do repo para "sem valor confiável").
- Sem ponta viva dedicada no `/ws` (Fronteira da entrega): o TREND de variável de flow atualiza no
  ritmo do poll de histórico, não a cada varredura — aceitável para v1, extensível sem quebra depois.
