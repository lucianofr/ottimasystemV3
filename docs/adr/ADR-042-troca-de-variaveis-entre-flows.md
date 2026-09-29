# ADR-042 — Troca de variáveis entre flows (blocos de barramento)

**Status:** Aceito · 2026-09-14

## Contexto

Um flow é uma ilha: o grafo é o único caminho de dado entre blocos (RF-401), e nada do
`graph_json` de um flow alcança outro. Hoje, para usar em `B` um valor calculado em `A`, o
engenheiro só tem dois desvios, ambos ruins:

1. **Ir e voltar pelo PLC** — `opc_write` em `A`, `opc_read` em `B`. Exige um nó OPC-UA
   gravável só para trafegar um número interno, e faz o dado atravessar a rede industrial
   duas vezes (com o atraso de polling do `opc-worker` nas duas pontas, ADR-032). Pior, é
   uma escrita em planta para um dado que nunca deveria sair do servidor.
2. **Fundir os dois flows num só** — perde o isolamento de falha por flow (RF-402), amarra
   dois processos ao mesmo Ts e ao mesmo `exec_order`, e torna o desenho ilegível.

O que falta é o que o barramento interno (ADR-002) já é: um caminho de dado desacoplado
entre processos, que o `flow-runtime` já lê e escreve a cada varredura. Esta decisão cria os
dois blocos de canvas que expõem esse caminho — **um publica** o valor de uma porta no
barramento, **outro assina** esse valor em qualquer outro flow — e o canal fixo que eles
usam. Nove decisões ficam fixadas aqui.

## Decisão

### D1 — Um canal fixo `flow.exchange`, com a `key` DENTRO do payload

Canal fixo, sem sufixo, exatamente na forma de `calc.values` (ADR-033) e `flow.values`
(ADR-041): uma linha nova em PRD §7.1, produtor e consumidor `flow-runtime`. O payload é o
modelo novo `ExchangeValue`:

```json
{"key": "nivel_tanque", "ts": "2026-09-14T12:00:00Z", "v": 42.5, "ok": true, "period_s": 1.0}
```

`key` é a identidade da variável trocada (D8); `v`/`ok` são o `PortSample` da porta de origem
(`float | bool`); `period_s` é o Ts do flow publicador, que é o que dá validade automática ao
assinante (D4). O assinante filtra por `key` em memória, num `SUBSCRIBE` único por processo.

**Alternativa rejeitada 1 — família `flow.exchange.<key>`.** Espelharia
`opc.values.<conn_id>` e permitiria assinatura seletiva no `/ws` depois, mas faria o **canvas
criar nome de canal em runtime**: o conjunto de canais do barramento deixaria de ser a lista
fechada de §7.1 (ADR-002) e passaria a depender do que um usuário digitou num bloco. Uma
linha de §7.1 com a chave no payload entrega a mesma função sem abrir esse precedente — e é
o que `calc.values`/`flow.values` já fazem com `tag_id`.

**Alternativa rejeitada 2 — Redis como key-value (`SET` com TTL + `GET` por varredura).**
O TTL daria expiração de graça, mas tornaria a leitura de porta um round-trip de rede dentro
do `step()` de cada varredura. O espelho em memória existe precisamente para isso não
acontecer (`snapshot.py`: "a leitura é síncrona e O(1) porque roda de dentro de laços que não
podem bloquear o event loop", ADR-004). Além disso, usar o Redis como banco de estado é uma
segunda natureza de uso do mesmo componente — o ADR-002 o define como barramento pub/sub, e o
ADR-003 dá a persistência ao Postgres.

**Alternativa rejeitada 3 — reusar `flow.values` + uma linha em `tags`.** A variável
historiada (ADR-041) já publica valor de porta no barramento; um bloco "ler tag" fecharia a
troca sem canal novo. Rejeitada por três motivos: (a) acoplaria troca de variável a
**persistência** — cada variável trocada gravaria em `samples` para sempre, com retenção e
carga de recorder que ninguém pediu; (b) a cadência de `flow.values` é limitada a 1 Hz por
decisão (ADR-041 D3), então um flow de `Ts = 0,5 s` trocaria dado na metade da sua taxa de
varredura; (c) exigiria CRUD de `tags` (rota, nome congelado, cascata, 422 de porta fria)
para cada variável trocada — muito mais superfície do que uma string no config do bloco.

### D2 — Publica a cada varredura do flow publicador; não persiste nada

O `bus_publish` publica dentro do próprio `step()` (mesma forma do `opc_write`, que publica em
`opc.writes`), uma vez por varredura, no Ts do flow que o contém — sem throttle. Não há teto
de 1 Hz como em `flow.values` (ADR-041 D3) porque **nada disso vai para o banco**: o custo é
uma mensagem Redis local, não uma linha de hypertable. Quem quiser histórico da variável
trocada marca a porta como variável historiada (ADR-041) — as duas features compõem e
nenhuma das duas absorve a outra.

### D3 — Cold não publica; inválido publica com `ok=false`

Entrada em cold start (`v is None`, nunca houve valor) **não publica**: não há valor a
anunciar, e o assinante fica COLD (D4). Entrada com valor conhecido e `ok=False` **publica**
com `ok=false` — a decisão A-6 do motor ("executa com o valor e propaga a flag") atravessa o
barramento em vez de parar nele. O assinante entrega `PortSample(v, ok=False)` e o bloco a
jusante aplica a sua própria regra (o MPC marca `input_invalid`, o `opc_write` suprime a
escrita, o filtro passa adiante).

> **Emendado pelo ADR-043:** o payload de `flow.exchange` deixa de carregar o booleano `ok` e
> passa a carregar o `Signal` completo (`quality`, `substatus`, `hi_limited`, `lo_limited`) —
> ver ADR-043 §6/§7.2. Cold continua sem publicar.

### D4 — Validade por idade AUTOMÁTICA: `3 × period_s`, sem campo de config

O assinante invalida o valor quando `idade > 3 × period_s`, onde `period_s` é o Ts do flow
publicador que veio no payload (D1) e a idade é medida contra o `ts` da fronteira da
varredura — o mesmo `ts` que o scheduler já entrega a todo `step()`. Expirado, a saída é
`PortSample(último valor, ok=False)`: valor conhecido + flag de invalidez, como o OPC-Read
faz com `quality != 0`. Nunca recebido, a saída é `PortSample(None, False)` — cold start, que
congela o bloco a jusante por `has_cold_input`. A distinção importa: os dois estados têm
efeito diferente no motor e não podem ser colapsados num só.

`3 ×` é a margem de duas varreduras perdidas. Sem essa expiração, parar o flow publicador
deixaria o assinante entregando o último valor com `ok=True` **para sempre**, e um MPC a
jusante controlaria sobre um dado morto — exatamente a falha que a postura fail-safe do
sistema (ADR-009/017) existe para impedir.

**Alternativa rejeitada — campo `max_age_s` na config do bloco.** Um knob no modal parece
mais flexível, mas só o publicador conhece a cadência certa: um `max_age_s = 5` configurado
por engano num assinante de um flow de `Ts = 60 s` invalidaria a variável permanentemente, e
um `max_age_s = 600` num flow de `Ts = 0,5 s` é um dado morto de 10 minutos passando por
válido. Derivar do publicador é sempre coerente e elimina um campo de config de todo o
caminho (parse, validate, contrato TS, modal, checks).

> **Emendado pelo ADR-043:** a expiração deixa de produzir "último valor com `ok=false`" e passa
> a rebaixar por teto — `min(quality publicado, UNCERTAIN)` — mantendo o último valor. Inválida
> para atuação do mesmo jeito, pois `ok ≡ quality is GOOD` (ADR-043 D3/D5) — ver ADR-043 §7.2.

### D5 — `key` única por projeto: duplicata reprova o save (422)

Dois `bus_publish` na mesma `key` seriam last-writer-wins sobre o mesmo nome — o assinante
leria valores alternados de duas fontes sem nenhum aviso. Reprovado no save, nos dois níveis:

- **Mesmo flow:** `validate_graph` reprova (validação pura do grafo, sem I/O).
- **Entre flows do projeto:** o `PUT /api/flows/{id}` consulta os `graph_json` dos flows
  irmãos e reprova 422 nomeando o flow que já publica a `key`. O `POST /api/projects/import`
  aplica a mesma checagem sobre o bundle inteiro — o bundle vem de fora, é fronteira de
  confiança.

Assinar a mesma `key` em N flows é normal e não tem limite: um produtor, quantos
consumidores quiser (é o desacoplamento do ADR-002).

### D6 — Assinante sem publicador NÃO é erro

`bus_subscribe` numa `key` que ninguém publica é aceito no save e fica COLD no runtime. O
publicador pode estar num flow parado, ou num flow que o engenheiro ainda vai desenhar —
flows são editados um por um e não existe ordem de criação imposta. O feedback já existe e é
visual: a porta fica dessaturada no canvas ao vivo (RF-305) e o bloco a jusante não executa.

### D7 — Portas bivalentes (numérico **ou** booleano)

As duas portas (`in` do publicador, `out` do assinante) são bivalentes, como as do bloco
Script (decisão A-5): o barramento é transporte e não reinterpreta o tipo do dado. `v` no
payload é `float | bool` e o assinante entrega exatamente o que foi publicado — um booleano
que sai de um `OUT` de Script chega booleano no outro flow, sem virar `1.0` no caminho.

### D8 — Namespace global, sem prefixo de projeto; `key` é `^[A-Za-z0-9_-]{1,64}$`

Nenhum prefixo de projeto na `key`: só existe **um projeto ativo por vez** (ADR-017), e os
flows de um projeto inativo não estão em execução, logo não publicam nem assinam. O charset é
restrito de propósito (sem `.`, sem glob, sem espaço) para a `key` continuar legível em log e
em payload, e para nunca colidir com a sintaxe de canal/padrão do Redis caso alguma
ferramenta futura queira filtrar por ela.

A `key` viaja no `graph_json` como qualquer outro campo de config — export/import de projeto
(§7.2) a leva verbatim, sem `tag_ref`, sem id interno.

### D9 — O barramento não cria bypass de segurança de processo

Nada aqui toca o caminho de escrita: o `bus_subscribe` produz um valor de porta como qualquer
outro bloco, e os portões de escrita (flow em deploy + watchdog vivo + modo REMOTO, ADR-009/
010) continuam governando o `opc_write`/MPC a jusante. Consequências diretas: flow publicador
parado ⇒ assinante invalida em até `3 × Ts_pub` (D4) ⇒ o bloco a jusante trata invalidez pela
sua própria regra (fail action do MPC, supressão do Write). Uma falha do Redis tem o mesmo
efeito, pelo mesmo caminho.

## Fronteira da entrega

Fora desta decisão, deliberadamente:

- **Ponta viva de `flow.exchange` no `/ws`.** A UI não precisa do canal: o valor da porta do
  assinante já chega ao canvas por `flow.status.<flow_id>.ports` (RF-404). Expor assinatura
  filtrada no `/ws` é aditivo depois, sem mudar produtor nem schema.
- **Aviso no editor para `key` sem publicador.** Exigiria consulta cruzada aos outros flows
  no editor (D6 explica por que a ausência é legítima). O estado COLD no canvas ao vivo já
  mostra o sintoma.
- **Persistência da variável trocada.** Coberta por composição com a variável historiada
  (ADR-041, D2), não por gravação própria deste canal.
- **Entrega garantida.** `flow.exchange` herda o fire-and-forget do ADR-002: mensagem perdida
  numa queda do Redis significa valor velho por algumas varreduras, e a expiração do D4 o
  invalida se a queda durar. Nenhum replay, nenhum ACK — é dado cíclico de processo, o caso
  que o ADR-002 declara aceitável.

## Consequências

- (+) Troca de variável entre flows sem passar por tag OPC: nada de nó gravável no PLC para
  tráfego interno, nada de round-trip pela rede industrial.
- (+) Isolamento de falha por flow (RF-402) preservado: os dois lados seguem sendo tasks
  independentes, com Ts próprio, e a partição por processo (`OTTIMA_FLOW_PARTITIONS`) continua
  funcionando — a troca é pelo barramento justamente porque memória compartilhada não
  atravessa processo.
- (+) Uma linha nova em §7.1 e nenhum canal dinâmico (D1): a lista fechada de canais do
  ADR-002 continua fechada.
- (+) Zero custo de banco: nada de hypertable, política de retenção ou carga de recorder
  (D2).
- (+) Assinante sem config de tempo (D4): não existe combinação de campos que produza
  invalidez permanente ou dado morto "válido".
- (−) Um flow com `Ts = 0,5 s` publica a 2 Hz por variável trocada. É mensagem Redis local
  (mesma ordem de grandeza do que `flow.status` já publica por varredura), mas não é grátis:
  trocar dezenas de variáveis a 2 Hz é carga real no barramento, e o desenho certo nesse caso
  é publicar de um flow mais lento.
- (−) O atraso da troca é de **uma varredura do consumidor**, no melhor caso: o assinante lê
  o que estava no espelho quando o seu `step()` rodou. Igual ao que o RF-401 já diz de uma
  aresta com `exec_order` invertido — determinístico, mas não instantâneo.
- (−) A `key` é um acoplamento por nome, invisível no canvas de cada flow: quem lê só o
  desenho de um flow não vê quem está do outro lado. Mitigado pelo 422 de duplicata (D5), que
  ao menos impede duas fontes para o mesmo nome.
