# Plan 011: Escrita OPC ganha timeout de I/O e a fila fica observável — sem decidir política de descarte

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado antes de passar ao próximo. Se qualquer condição da seção "Condições de
> PARADA" ocorrer, pare e relate — não improvise. **Este plano tem uma decisão que NÃO é sua**
> (Passo 5): se você chegar nela, pare e relate as opções. Ao terminar, atualize a sua linha na
> tabela de status de `docs/reports/advisor/README.md` — a menos que um revisor o tenha despachado
> e dito que ele mantém o índice.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 37b0caa..HEAD -- services/opc-worker/src/ottima_opc_worker/writes.py services/opc-worker/src/ottima_opc_worker/state.py services/opc-worker/src/ottima_opc_worker/watchdog.py services/opc-worker/src/ottima_opc_worker/polling.py`
> Se qualquer arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; em caso de divergência, trate como
> condição de PARADA.

## Status

- **Prioridade**: P1
- **Esforço**: S (Passos 1-4) · a política do Passo 5 é decisão do dono, não esforço
- **Risco**: LOW para os Passos 1-4 (aditivos) · a política do Passo 5 é MED e **não deve ser
  decidida por um executor**
- **Depende de**: nenhum
- **Categoria**: bug / segurança de processo
- **Planejado em**: commit `37b0caa`, 2026-09-19

## Por que isso importa

O `opc-worker` é o **único processo que escreve na planta** (ADR-006). Dentro dele, três caminhos
fazem I/O OPC-UA. Dois têm orçamento de tempo explícito; o que **escreve valor de processo** não tem.

- `watchdog.py:144` envolve a leitura em `asyncio.wait_for(..., self._io_timeout_s)`.
- `watchdog.py:155-158` envolve a **escrita** do bit de watchdog em `asyncio.wait_for(...)` — com
  um comentário nomeando exatamente o risco: *"Sessão zumbi: a leitura/escrita não completa; sem
  isso a task ficaria pendurada para sempre e o flow preso em `watchdog_dead`."*
- `polling.py:336-338` envolve as leituras de processo em `asyncio.wait_for(...)`.
- `writes.py:270` — a escrita de MV/SP comandada pelo MPC — **não tem nada**.

O `_io_timeout_s` dos dois caminhos protegidos é `max(10.0, 3 * self._period_s)`, calculado depois
de um incidente real de "sessão zumbi" (o comentário de `polling.py:178` registra o motivo). A
escrita de processo fica dependendo do default implícito do asyncua, que não escala com a cadência
do flow e não é deliberado.

Segunda metade do achado: a fila por conexão (`writes.py:477`) é um `asyncio.Queue()` **sem
`maxsize`**, e a sua profundidade não aparece em `/health` (`state.py::to_health`). O código já se
defende de *consumidor morto* — `writes.py:470-473` confere a task viva a cada escrita e a recria
sobre a mesma fila — mas **não** se defende de *consumidor vivo e lento*: nesse caso a fila cresce
sem teto e sem nenhum sinal visível ao operador, no processo que escreve na planta.

**Este plano resolve o que é seguro e verificável** (timeout + observabilidade) e **explicitamente
não resolve a política de descarte**, porque descartar escrita de planta é decisão de semântica de
controle, não de tuning de buffer — ver Passo 5.

## Estado atual

**A escrita sem timeout** — `services/opc-worker/src/ottima_opc_worker/writes.py:266-271`:
```python
        variant_type = runtime.variant_type_for(tag.id)
        valor = coerce_value(write.value, variant_type)
        try:
            node = client.get_node(tag.node_id)
            await node.write_value(ua.DataValue(ua.Variant(valor, variant_type)))
        except Exception as exc:
```
O `except Exception` logo abaixo (`:271-294`) já faz o trabalho de falha certo: incrementa
`runtime.snapshot.write_errors`, loga e publica evento `severity="warning"`. **Um `TimeoutError`
cai nesse mesmo `except`** — ou seja, adicionar o `wait_for` não exige caminho de erro novo; ele já
existe e já produz evento visível.

**O padrão a copiar, no mesmo serviço** — `services/opc-worker/src/ottima_opc_worker/watchdog.py:152-158`:
```python
                agora = time.monotonic()
                if agora >= proxima_escrita:
                    proxima_escrita = agora + self._period_s
                    await asyncio.wait_for(
                        write_node.write_value(value, ua.VariantType.Boolean),
                        timeout=self._io_timeout_s,
                    )
```

**Como o orçamento é calculado** (idêntico nos dois lugares protegidos) —
`watchdog.py:73` e `polling.py:178`:
```python
self._io_timeout_s = max(10.0, 3 * self._period_s)
```

**A fila sem teto** — `services/opc-worker/src/ottima_opc_worker/writes.py:475-479`:
```python
        queue = self._conn_queues.get(write.conn_id)
        if queue is None:
            queue = asyncio.Queue()
            self._conn_queues[write.conn_id] = queue
        queue.put_nowait(write)
```

**O `/health` que não mostra a fila** — `services/opc-worker/src/ottima_opc_worker/state.py:117-133`.
`ConnectionSnapshot.to_health()` devolve `name`, `state`, `flow_watchdog_alive`, `session_up_since`,
`last_publish_ts`, `tags_polled`, `read_errors`, `write_errors`. **Não há campo de fila.** O
docstring do método registra a convenção do que entra ali: *"`last_values` fica de fora de
propósito: o `/health` é diagnóstico de conexão, não canal de dados de processo."* Profundidade de
fila é diagnóstico de conexão, não dado de processo — cabe.

## Convenções do repositório que se aplicam aqui

- **Python ≥ 3.12, type hints obrigatórios**, `ruff` line-length 100.
- **Nunca bloquear o event loop**; `asyncio.wait_for` é o idioma da casa para orçamento de I/O.
- **Falhar para o lado seguro é inegociável** (`PRODUCT.md:62`): qualquer dúvida resolve-se
  devolvendo o comando ao PLC. Um timeout que vira evento `warning` + `write_errors += 1` está
  desse lado; um `await` que nunca retorna não está.
- **UI/superfícies refletem estado publicado, nunca eco de comando** (ADR-002). Não invente canal
  novo: o evento vai pelo pipeline `events` existente (`publish_event`), que `writes.py` já usa.
- **Commits em Conventional Commits, mensagem pt-BR.** Exemplo real do `git log`:
  `fix(historizadas): constroi OpcValue dentro do try do publish`.
- **Comentários em pt-BR**, explicando o *porquê* — veja `watchdog.py:162-163` e
  `writes.py:470-473` como modelo: nomeiam o incidente ou o desfecho evitado, não descrevem a linha.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Lint | `uv run ruff check .` | exit 0 |
| Formato | `uv run ruff format --check .` | exit 0 |
| Testes do opc-worker | `uv run pytest services/opc-worker -q` | tudo passa |
| Testes do core | `uv run pytest packages/ottima-core -q` | tudo passa |
| Timeout entrou | `grep -c 'wait_for' services/opc-worker/src/ottima_opc_worker/writes.py` | ≥ `1` |
| Fila no health | `grep -n 'queue' services/opc-worker/src/ottima_opc_worker/state.py` | ≥ 1 linha |

**NÃO rode** `uv run pytest` sem recorte de pasta (~20 min, testcontainers, dois flaky já
registrados: `TD-027` está exatamente em `services/opc-worker/tests/test_heartbeat.py`). Rode por
pacote. Se `test_heartbeat.py::test_tag_que_muda_nao_e_republicada_pelo_heartbeat` falhar, **é o
TD-027, não é regressão sua** — confirme rodando o arquivo isolado duas vezes e registre no seu
relato; não tente consertá-lo neste plano.

**NÃO rode** nenhum `docker compose`, `deploy/smoke.sh`, `pytest -m e2e` nem `npx playwright test`:
o stack de 8 serviços do dono está no ar com planta simulada viva.

**NÃO invoque nenhuma ferramenta do servidor MCP `ottima`** montado nesta sessão
(`flow_deploy`, `flow_stop`, `mpc_write_mv`, `mpc_write_sp`, `mpc_set_mode`, …): elas comandam a
planta viva do dono em `http://localhost:8080`.

## Escopo

**Em escopo** (únicos arquivos a modificar):
- `services/opc-worker/src/ottima_opc_worker/writes.py`
- `services/opc-worker/src/ottima_opc_worker/state.py`
- `services/opc-worker/tests/test_writes.py`

**Fora de escopo** (NÃO toque, mesmo parecendo relacionado):
- `services/opc-worker/src/ottima_opc_worker/watchdog.py` e `polling.py` — **já estão certos**.
  São o modelo a copiar, não alvo de mudança.
- `services/opc-worker/src/ottima_opc_worker/connection.py` — o `Client(config.endpoint)` sem
  `timeout=` explícito é um achado real mas separável; mudar o default do cliente afeta leitura,
  watchdog **e** escrita de uma vez, e merece plano próprio com medição.
- **A gate de escrita** (`_gate_reason`, `_block`, o caminho `no_watchdog`/`watchdog_dead`/
  `session_down`). A semântica de "quando é permitido escrever" **não muda** neste plano.
- `services/opc-worker/tests/test_heartbeat.py` — é o TD-027, débito registrado, fora daqui.
- Qualquer outro serviço, o barramento, ou `docs/`.
- **Qualquer política de descarte de escrita** — ver Passo 5.

## Fluxo de git

- Branch: `advisor/011-escrita-opc-timeout`.
- **Um commit só** para os Passos 1-4. Sugestão de mensagem:
  `fix(opc-worker): escrita de processo ganha timeout de I/O e fila vira observavel`
- Sem push, sem PR, a menos que o operador peça.
- Em worktree: caminho **ABSOLUTO** em todo `read`/`write`/`edit`, `cwd` explícito em todo shell,
  confirmação por shell depois de cada escrita (`CLAUDE.md`, "Subagente em worktree").

## Passos

### Passo 1: dar ao `WriteConsumer` um orçamento de I/O explícito

**Atenção — a fórmula dos irmãos NÃO se transplanta.** `polling.py:178` e `watchdog.py:73` fazem
`max(10.0, 3 * self._period_s)` porque são **laços periódicos**: o orçamento é derivado da própria
cadência deles. O `WriteConsumer` é **dirigido a evento** — não tem cadência. O único "period" em
`writes.py` é `_BlockedPeriod` (`:140`), que é janela de agregação de escrita bloqueada, coisa
completamente diferente. Copiar a fórmula sem base faria o executor travar ou inventar um número.

Escolha **uma** das duas bases e **registre a escolha no relato**:

- **(a) Constante achatada, recomendada.** Escrita é evento pontual; a latência aceitável dela não
  tem relação com a cadência de varredura da conexão. Defina uma constante de módulo em
  `writes.py`, ao lado das demais, com comentário dizendo por que é achatada:
  ```python
  # Escrita é dirigida a evento, não periódica: não há cadência de onde derivar orçamento
  # (ao contrário de polling.py:178 / watchdog.py:73). O teto existe para o caso "sessão
  # zumbi" — o mesmo que watchdog.py:162-163 nomeia —, não para casar com o scan.
  WRITE_IO_TIMEOUT_S = 10.0
  ```
  `10.0` é o **piso** que os dois irmãos já usam, então não é número novo no sistema.
- **(b) Derivar do período de polling da conexão**: `runtime.config.polling_period_ms / 1000`, que
  **está disponível** (é o mesmo campo que `polling.py:174` consome). Use só se você encontrar
  razão real para a escrita herdar a cadência de leitura — e diga qual no relato.

**Não** invente um terceiro valor e **não** crie módulo de constantes novo.

**Verifique**: `uv run ruff check services/opc-worker` → exit 0.

### Passo 2: envolver a escrita de processo

Em `writes.py`, na linha que hoje é:
```python
            await node.write_value(ua.DataValue(ua.Variant(valor, variant_type)))
```
passe para:
```python
            await asyncio.wait_for(
                node.write_value(ua.DataValue(ua.Variant(valor, variant_type))),
                timeout=self._io_timeout_s,
            )
```

**Não adicione `except TimeoutError` separado.** O `except Exception` existente (`:271`) já captura
`TimeoutError`, incrementa `write_errors`, loga e publica o evento `warning` com o nome da tag e da
conexão. Acrescentar um ramo próprio duplicaria o caminho de falha. Confirme lendo `:271-294` antes
de concluir o passo.

Confirme que `asyncio` já está importado no topo do arquivo (`grep -n '^import asyncio' services/opc-worker/src/ottima_opc_worker/writes.py`).

**Verifique**:
- `grep -c 'wait_for' services/opc-worker/src/ottima_opc_worker/writes.py` → ≥ `1`
- `uv run ruff check services/opc-worker` → exit 0

### Passo 3: expor a profundidade da fila no `/health`

Em `state.py`, adicione ao `ConnectionSnapshot` um campo inteiro de diagnóstico de fila
(por exemplo `write_queue_depth: int = 0`) e inclua-o no dict devolvido por `to_health()`, ao lado
de `write_errors`. **Não** inclua o conteúdo da fila, só a profundidade — o docstring do método já
fixa a regra ("o `/health` é diagnóstico de conexão, não canal de dados de processo").

Depois, no ponto de `writes.py` onde o snapshot é atualizado (o mesmo lugar que incrementa
`write_errors`), alimente o campo com `queue.qsize()` da fila da conexão.

**Não** adicione campo novo a nenhum modelo Pydantic de barramento, nem canal novo (ADR-002). O
`/health` já é a superfície existente para isto, e a L2 já o consulta
(`OTTIMA_HEALTH_URL_OPC_WORKER`, `CLAUDE.md` seção "Comandos").

**Verifique**:
- `grep -n 'queue' services/opc-worker/src/ottima_opc_worker/state.py` → ≥ 1 linha
- `uv run ruff check services/opc-worker` → exit 0
- `uv run pytest services/opc-worker -q` → tudo passa (o formato do `/health` é aditivo; se algum
  teste existente comparar o dict inteiro por igualdade, atualize **esse teste** para incluir o
  campo novo e registre isso no seu relato — não remova a asserção)

### Passo 4: teste — o timeout produz evento, não travamento

Em `services/opc-worker/tests/test_writes.py`, siga o padrão dos testes existentes do arquivo
(leia-o inteiro antes de escrever; o repo **não usa `unittest.mock` em lugar nenhum** — a
verificação do auditor de testes confirmou zero ocorrências. Descubra como os testes vizinhos
substituem o cliente asyncua e use o mesmo mecanismo; **não introduza `unittest.mock`**).

Cubra dois casos:

1. **Escrita que excede o orçamento** → o consumidor não trava; `write_errors` incrementa; um
   evento `severity="warning"` é publicado nomeando a tag. Este é o RED genuíno: sem o Passo 2 o
   teste fica pendurado ou não produz o evento.
2. **Profundidade de fila visível** → com N escritas enfileiradas e o consumidor retido,
   `to_health()` reporta `write_queue_depth == N`.

**Verifique**: `uv run pytest services/opc-worker/tests/test_writes.py -q` → tudo passa, incluindo
os novos.

### Passo 5: PARE aqui — a política de descarte é decisão do dono

A fila continua **sem `maxsize`** depois dos Passos 1-4. Isso é deliberado neste plano: limitar a
fila exige escolher o que acontece com uma escrita de planta que não cabe, e essa escolha muda a
semântica de controle.

**Não implemente nenhuma das opções abaixo.** Registre no seu relatório final que o Passo 5 ficou
pendente de decisão, com as três opções e o trade-off de cada uma:

| Opção | O que faz | Risco de processo |
|---|---|---|
| **A. Descartar a mais antiga** (o que o `recorder` faz em `pipeline.py:59-68`) | `put_nowait` com `maxsize`, drop-oldest | **Inaceitável sem decisão explícita**: a fila é por **conexão** e carrega escritas de **várias tags diferentes**. Descartar a mais antiga joga fora um valor comandado da tag A para preservar um da tag B — decisão de semântica de planta, não de buffer |
| **B. Colapsar por `tag_id`** (last-write-wins por tag) | Fila passa a ser mapa `tag_id -> escrita mais recente` | Preserva "o último comando de cada tag vence", que é provavelmente a semântica certa para MV/SP; mas **muda a ordem de execução entre tags**, e ordem é contrato em sistema de controle |
| **C. Rejeitar com evento, sem descartar em silêncio** | Fila com `maxsize`; `put_nowait` estourando ⇒ evento `alarm` + recusa explícita ao publicador | Mais conservador: nada é jogado fora em silêncio. Mas a recusa chega tarde demais para quem publicou (fire-and-forget, ADR-002), então o efeito prático é alarme, não proteção |

> **Restrição técnica que limita as três opções**: `_enqueue` é **síncrono** (`def`, usa
> `put_nowait` — `writes.py:463`). Com `maxsize`, `put_nowait` **levanta `QueueFull`**; não
> bloqueia. Então qualquer opção precisa dizer o que acontece nesse ramo. Tornar `_enqueue`
> assíncrono para poder aguardar mudaria **todos** os chamadores e o caminho de `_dispatch` — está
> **fora** de qualquer versão deste plano.
>
> **Precedente interno para a metade de observabilidade**: `_BlockedPeriod` (`writes.py:140`, usado
> em `:391`) com `KIND_WRITE_BLOCKED` (importado em `:32`) já resolve "não inundar o canal de
> eventos" agregando contagem de escritas suprimidas por período. Se a política escolhida precisar
> emitir evento, **siga essa forma**, não um evento por escrita descartada.

As três exigem também decidir **o teto** (fixo? derivado de `period_s`? por conexão ou por tag?) e
**a severidade do evento** (`warning` como as falhas de escrita, ou `alarm`).

O precedente do `recorder` (`_DropOldestBuffer`) **não se transfere**: aquilo é telemetria, onde
perder amostra antiga é aceitável por construção. Aqui é comando de atuador.

## Plano de teste

- **Novos**: 2 testes em `services/opc-worker/tests/test_writes.py` (Passo 4).
- **Padrão estrutural**: os testes vizinhos do mesmo arquivo. Leia `test_writes.py` inteiro antes de
  escrever — ele já cobre a gate de escrita (`no_watchdog`/`watchdog_dead`/`session_down`), então o
  mecanismo de substituir o cliente asyncua já está resolvido lá. Siga-o.
- **Nada de `unittest.mock`**: o repo não usa em lugar nenhum; introduzir aqui criaria uma segunda
  convenção.
- **Nenhum teste existente deve mudar**, exceto (Passo 3) um que compare o dict do `/health` por
  igualdade — e nesse caso você **acrescenta o campo**, não remove a asserção.
- **Verificação**: `uv run pytest services/opc-worker -q` → tudo passa.

## Critérios de conclusão

Todos devem valer:

- [ ] `grep -c 'wait_for' services/opc-worker/src/ottima_opc_worker/writes.py` → ≥ `1`
- [ ] O timeout usa a base escolhida no Passo 1 — constante achatada (a) **ou** `polling_period_ms/1000` (b) — e a escolha está justificada no relato
- [ ] O timeout **não** usa `max(10.0, 3 * period_s)` copiado dos irmãos: o `WriteConsumer` não tem cadência de onde derivar
- [ ] Nenhum `except TimeoutError` separado foi adicionado em `writes.py`
- [ ] `grep -n 'queue' services/opc-worker/src/ottima_opc_worker/state.py` → ≥ 1 linha
- [ ] Nenhum canal de barramento novo, nenhum modelo Pydantic de barramento alterado
- [ ] 2 testes novos em `test_writes.py` passando
- [ ] `uv run ruff check .` → exit 0
- [ ] `uv run ruff format --check .` → exit 0
- [ ] `uv run pytest services/opc-worker -q` → tudo passa (ou só o TD-027 vermelho, justificado no relato)
- [ ] `uv run pytest packages/ottima-core -q` → tudo passa
- [ ] `git status --porcelain` lista só os 3 arquivos em escopo
- [ ] **O Passo 5 está relatado como pendente de decisão do dono, com as três opções**
- [ ] Linha de status atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- Os excertos de "Estado atual" não baterem com o código vivo (drift desde `37b0caa`).
- Você não conseguir aplicar **nenhuma** das duas bases do Passo 1 — por exemplo, se
  `runtime.config.polling_period_ms` não existir e você também julgar a constante achatada
  inadequada. Relate; não invente um terceiro valor nem passe `None` para o `wait_for`.
- Você concluir que adicionar o `wait_for` exige um ramo de exceção novo: releia `writes.py:271-294`
  primeiro. Se ainda parecer necessário, relate em vez de adicionar.
- Um teste existente quebrar por causa do campo novo no `/health` de forma que não seja só
  acrescentar o campo ao valor esperado.
- Você se pegar implementando drop-oldest, colapso por `tag_id` ou qualquer teto de fila: **pare**.
  Isso é o Passo 5 e é decisão do dono.
- `test_heartbeat.py` falhar: é o **TD-027**, débito registrado. Não conserte aqui; registre no
  relato e siga.

## Notas de manutenção

- **O que interage com isto**: a decisão do Passo 5. Qualquer teto de fila implementado depois
  precisa responder "o que acontece com um comando de MV que não coube" — e a resposta tem de estar
  escrita antes do código, não depois.
- **O que um revisor deve olhar no PR**: (1) o timeout usa a mesma fórmula dos irmãos, não um
  número mágico novo; (2) nenhum ramo de erro duplicado; (3) o `/health` ganhou **um inteiro**, não
  o conteúdo da fila; (4) a gate de escrita não foi tocada — o diff em `_gate_reason`/`_block` deve
  estar vazio.
- **Adiado de propósito, e por quê**:
  - `connection.py::build_client` sem `timeout=` explícito — afeta leitura, watchdog e escrita
    juntos; merece plano próprio com medição.
  - **A política de descarte** — ver Passo 5. É o único item deste achado que não é conserto
    mecânico, e deixá-lo para um executor seria deixá-lo escolher semântica de planta por omissão.
- **Se um dia aparecer `block_overrun` em produção**: o `TD-016` registrou esse como o gatilho
  objetivo para reabrir a ADR-004. Fila de escrita crescendo é um sintoma vizinho mas distinto —
  registre a observação no `_tech-debt.md` em vez de assumir que é o mesmo problema.
