# ADR-033 — Tags calculadas

**Status:** Aceito · 2026-08-15

## Contexto
O usuário quer criar, na tela Tags, uma **tag calculada**: um script Python que lê outras tags já
cadastradas (`IN1..INn`, na ordem de seleção) e atribui o resultado à variável `OUT`, recalculada
periodicamente (1, 2, 5, 10, 30 ou 60 s) e publicada no barramento como qualquer leitura OPC.
Quatro decisões de arquitetura ficam fixadas aqui.

## Decisão

### Linha em `tags`, não tabela paralela
`samples.tag_id` é `BIGINT` **sem FK** (`models/timeseries.py`). Uma tabela `calculated_tags` com
sequence própria colidiria com ids de tags OPC dentro da mesma hypertable — dois valores
diferentes escrevendo na mesma série. Uma tag calculada é uma linha em `tags`, discriminada por
`connection_id IS NULL`, com `project_id` como dono alternativo (`connection_id`/`node_id` ficam
nulos e `project_id` passa a existir). Invariante `ck_tags_owner`: OPC xor calculada — nunca as
duas coisas, nunca nenhuma. Compartilhar o id space é o que faz histórico, `/api/history`, WS e
retenção funcionarem **sem nenhuma alteração** — todos operam por `tag_id`, cegos à origem.
Consequência verificada: o `opc-worker` carrega tags por `Tag.connection_id.in_(...)`
(`opc-worker/supervisor.py`) — tags calculadas ficam **naturalmente fora** dele, sem exclusão
explícita nem risco de subscription/escrita OPC sobre elas.

### Canal novo `calc.values`
Fixo, sem sufixo (ao contrário de `opc.values.<conn_id>`, que carrega o id da conexão). Produtor:
`calc-worker`. Consumidores: `api(WS)`, `recorder`. Payload = o `OpcValue` existente
(`{tag_id, ts, value, quality}`), sem modelo novo. Reusar `opc.values.<conn_id>` com um `conn_id`
sintético funcionaria sem tocar em consumidor nenhum — todos filtram por `tag_id` e ignoram o
sufixo — mas mentiria no contrato do PRD §7.1 (produtor = opc-worker, sufixo = id de conexão real)
e deixaria um `opc.values.999999` para alguém investigar às 3h. O canal próprio custa três
listeners de poucas linhas e paga honestidade de contrato.

### Isolamento: task asyncio por tag + processo de sandbox
Uma `asyncio.Task` por tag calculada (`calc-tag-<id>`), cadência própria, falha não propaga às
demais. **Isto substitui a proposta original de "uma thread por tag"**: o script roda em `exec()`
dentro de um processo do `ScriptPool` (ADR-018), com timeout de `0,7 × período` — a mesma política
de timeout do bloco Script. Processo é estritamente mais forte que thread como unidade de
isolamento: um `while True: pass` no script é matável com `proc.kill()`; a mesma trava numa thread
do processo do worker não é interrompível sem matar o worker inteiro. Decisão em linha com
ADR-004 (loops vivos em asyncio, nunca job queue) e ADR-018 (contrato de execução de script do
usuário já em processo separado).

Teto conhecido: `OTTIMA_CALC_POOL_SIZE` (default 4) menor que o número de tags calculadas
simultâneas faz uma tag lenta atrasar a espera de outra por um worker livre do pool — o tempo de
espera conta no orçamento de timeout dela. Marcado no código com comentário `ponytail:`.

### Serviço novo `calc-worker`
Porta 8004. Pool de scripts **próprio** (`ScriptPool` dedicado, ADR-006 — cada serviço asyncio
isola seus recursos). Justificativa: se o calc-worker reusasse o pool do flow-runtime, uma tag
calculada consumiria workers que deveriam estar reservados para o bloco Script de um flow em
execução — dois domínios competindo pelo mesmo recurso finito sem relação entre si.

### Fronteira do v1
Tag calculada **não** é entrada válida de bloco OPC-Read: `ottima_core/tags.py::project_tags` faz
INNER JOIN com `opc_connections` e `TagRef.conn_id` é campo obrigatório — incluir tag calculada
ali é outra fatia (validação de grafo, contrato de porta, canvas), não pedida, fora do escopo desta
decisão. O editor de flow recusa a referência com a mensagem de validação já existente.

Tag calculada **pode** ser entrada de outra tag calculada: o `calc-worker` assina `calc.values` via
`ValueSnapshot`, então uma tag calculada B que usa a tag calculada A como `IN1` lê o último valor
publicado de A, com defasagem de até 1 período de A. Sem deadlock — tudo é último-valor, nunca
espera síncrona por outro cálculo.

### Modelo de ameaça
Herdado do ADR-018: admin autenticado, sem sandboxing pesado. A superfície cresce — antes só quem
editava um flow executava código do usuário; agora quem cria uma tag calculada também. Mitigado
pelas mesmas proteções do bloco Script: `require_admin` na rota de CRUD, `ALLOWED_BUILTINS` sem
`__import__`, `os.environ.clear()` no processo filho do `ScriptPool`, recusa de nomes dunder por
AST no save, e execução sempre em processo separado do event loop do serviço.

**Limitação residual conhecida (revisão de segurança da entrega).** O worker do `ScriptPool` é
reaproveitado entre jobs, e `math`/`numpy` são injetados no escopo como os MESMOS objetos de módulo
importados na partida do processo. O save recusa **atribuição** a atributo desses módulos
(`math.pi = 3`), mas não impede uma **chamada** que muda estado global da lib (ex.: `numpy.seterr`,
`numpy.set_printoptions`): o efeito sobrevive para os jobs seguintes daquele worker, podendo
corromper o `OUT` de OUTRA tag calculada que caia no mesmo processo — e o valor sai publicado com a
qualidade da entrada, sem sinal de erro. Não é escalada de privilégio (o modelo de ameaça já é admin
autenticado); é integridade de dado entre tags. Aceito nesta entrega por proporcionalidade.
Caminho de upgrade, na ordem de custo: reciclar o worker a cada N jobs (limita a janela) ou um pool
de tamanho 1 por tag calculada (isolamento total, ao custo de um processo por tag).

### Reuso do contrato do ADR-018
O contrato de escopo do script (`math`, `numpy` disponíveis; dict `state` persistente entre
execuções; timeout ~70% do período) é **reusado verbatim** do bloco Python-Script. A única
diferença é o nome da variável de saída: `OUT` único (`ScriptPool.run(output_names=("OUT",),
n_outputs=1)`), em vez de `OUT1..OUTn` do bloco de flow — porque uma tag calculada tem exatamente
um valor, não um conjunto de portas de saída.

## Consequências
- (+) Histórico, `/api/history`, WS e retenção funcionam para tags calculadas sem nenhuma
  alteração de schema ou de rota — herdam tudo por compartilhar o id space de `tags`.
- (+) Processo (não thread) garante que um script preso não trava o `calc-worker` inteiro.
- (+) Pool de scripts próprio do `calc-worker` impede que tags calculadas disputem workers com o
  bloco Script de flows em execução.
- (+) Contrato de script reusado do ADR-018 — nada novo para o usuário aprender, só a variável de
  saída (`OUT` em vez de `OUT1..OUTn`).
- (−) `OTTIMA_CALC_POOL_SIZE` insuficiente para o número de tags calculadas simultâneas introduz
  espera de fila que consome o orçamento de timeout individual de cada tag — documentado, não
  corrigido automaticamente (v1 não tem alocação dinâmica de pool).
- Superfície de execução de código do usuário aumenta (quem cria tag, não só quem edita flow);
  mitigada pelas mesmas proteções do ADR-018, papel `require_admin` exigido.
- Tag calculada fica fora do bloco OPC-Read na v1 por decisão de escopo, não por limitação técnica
  — pode ser revisitada em ADR futuro se o pedido aparecer.
