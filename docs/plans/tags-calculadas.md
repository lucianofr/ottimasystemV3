# Plano — TAG CALCULADA (tela Tags + worker dedicado)

**Status:** aguardando aprovação (GATE 1) · **Tier:** large (novo serviço, migration, canal novo, superfície de UI, execução de código do usuário)

## 1. Pedido (verbatim do usuário)

> adicione na tela TAGS a possibilidade do usuário criar TAG CALCULADA. A tag calculada deverá poder
> utilizar tags já cadastradas como variaveis de entrada. Ao selecionar um tag existe para fazer parte
> da tag calculada o script deve referenciar ela como IN1, IN2, IN3 assim sucessivamente para cada tag
> adicionada na sequencia. O valor da tag calculada deverá ser atribuido a variavel OUT no script. O
> usuário irá entrar com um script em python para calcular a tag. Deverá ser criado um worker novo para
> executar os scripts dos tags calculados. O resultado dos tags calculados devem ser publicados no redis.
> No campo de propriedades da tag calculada o usuario deverá informar a periodicidade que o tag calculado
> deverá ser calculado, deixe valores pre-selecionados num combobox 1, 2, 5, 10, 30 e 60 segundos. O
> sistema deverá ter um novo worker em thread separada para cada tag calculado criado, isso impede que
> problemas em um tag afete outros.

## 2. Decisões de arquitetura (exigem aprovação — ADR novo)

### D1 — Tag calculada é uma linha em `tags`, não uma tabela paralela

`samples.tag_id` é `BIGINT` **sem FK** (`models/timeseries.py:24-31`). Uma tabela `calculated_tags`
com sequence própria colidiria com ids de tags OPC dentro de `samples` — duas séries distintas no mesmo
`tag_id`. Compartilhar o id space de `tags` é o que faz histórico, `/api/history`, WS e retenção
funcionarem **sem nenhuma alteração** (evidência: `routers/history.py:191-247` não faz join com `tags`;
`recorder/pipeline.py` é "dumb pipe" e aceita `tag_id` órfão; `history_retention.py:21-27` é por tabela).

Discriminador = `connection_id IS NULL` (sem coluna `kind` redundante). Invariante estrutural no banco:

```
CHECK ((connection_id IS NOT NULL AND project_id IS NULL     AND node_id IS NOT NULL)
    OR (connection_id IS NULL     AND project_id IS NOT NULL AND node_id IS NULL))
```

Consequência de segurança verificada: `opc-worker/supervisor.py:168-172` carrega tags por
`Tag.connection_id.in_(...)` — tags calculadas ficam **naturalmente fora** do opc-worker. Nenhuma
tentativa de subscription/escrita OPC sobre elas. Nada a mudar lá.

### D2 — Canal novo `calc.values` (ADR-002 exige ADR para canal novo)

Produtor: `calc-worker`. Payload: `OpcValue` **exatamente como está** (`{tag_id, ts, value, quality}`),
sem modelo novo. Reusar `opc.values.<conn_id>` com um `conn_id` sintético funcionaria sem tocar em
consumidor nenhum (todos filtram por `tag_id` e ignoram o sufixo), mas mentiria no contrato do PRD §7.1
(produtor = opc-worker, sufixo = conn_id) e deixaria `opc.values.999999` para alguém investigar às 3h.
Custo da honestidade: 3 listeners de 2 linhas + 1 prefixo no frontend.

### D3 — Isolamento: task asyncio por tag + processo de sandbox, não thread

O pedido diz "thread separada para cada tag". ADR-004 proíbe job queue e manda loop vivo asyncio;
ADR-018 já executa script do usuário em **processo separado** (`ScriptPool`, `proc.kill()` no timeout).
Processo é estritamente mais isolado que thread: `while True: pass` num script mata o worker daquele job
e ele re-sobe; numa thread seria impossível interromper. Portanto:

- 1 `asyncio.Task` por tag calculada (`calc-tag-<id>`), cadência própria, falha não propaga;
- `exec()` num processo do `ScriptPool`, timeout = `0.7 × período` (mesma política do ADR-018);
- **teto conhecido:** com `pool_size` menor que o nº de tags simultâneas, uma tag lenta faz outra esperar
  por worker livre (o tempo de espera conta no orçamento dela). `OTTIMA_CALC_POOL_SIZE` (default 4) é o
  knob. Marcado com comentário `ponytail:` no código.

### D4 — `ScriptPool` e `ValueSnapshot` sobem para `ottima-core`

Ambos são primitivas sem domínio de flow (`script_pool.py` recebe code/inputs/state/timeout;
`snapshot.py` é cache `dict[tag_id]` sobre `PatternListener`). Dois serviços passam a consumi-las →
casa é `packages/ottima-core`. Cutover limpo: módulos movidos, imports do flow-runtime atualizados,
sem shim nem re-export.

`ScriptPool.run` ganha `output_names: Sequence[str] | None = None` (None → `OUT1..OUTn`, comportamento
atual intacto). Tag calculada passa `("OUT",)` — o nome que o usuário pediu.

### D5 — Fronteira do v1: tag calculada **não** é entrada de bloco OPC-Read

`ottima_core/tags.py::project_tags` faz INNER JOIN com `opc_connections` e `TagRef.conn_id` é `int`
obrigatório. Incluir tag calculada ali é outra fatia (validação de grafo, contrato de porta, canvas).
Não pedido → fora do escopo. Efeito prático: o editor de flow recusa referência a tag calculada, com a
mensagem de validação que já existe. Tag calculada **pode** ser entrada de outra tag calculada (o
snapshot do calc-worker assina `calc.values`), com defasagem de 1 período — sem deadlock, tudo é
último-valor.

### D6 — Export/import inclui tags calculadas

Não foi pedido, mas RF-102/ADR-012 dizem que o export de um projeto contém "conexões OPC, tags". Sem
isso o export fica silenciosamente incompleto — bug introduzido por omissão. `projects.py:206` usa
INNER JOIN (não quebra, só omite) e `bundle.py:33` daria `KeyError` se a tag chegasse lá. Fatia pequena:
`BundleTag` ganha campos opcionais e `connection` passa a `str | None`.

## 3. Modelo de dados (migration `0012_calculated_tags`, down_revision `0011_opc_polling_period`)

```sql
ALTER TABLE tags ALTER COLUMN connection_id DROP NOT NULL;
ALTER TABLE tags ALTER COLUMN node_id       DROP NOT NULL;
ALTER TABLE tags ADD COLUMN project_id BIGINT REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE tags ADD CONSTRAINT ck_tags_owner CHECK (...);            -- D1
CREATE UNIQUE INDEX uq_tags_project_name ON tags (project_id, name) WHERE connection_id IS NULL;

CREATE TABLE calculated_tags (
  tag_id         BIGINT PRIMARY KEY REFERENCES tags(id) ON DELETE CASCADE,
  code           TEXT     NOT NULL,
  period_seconds SMALLINT NOT NULL CHECK (period_seconds IN (1,2,5,10,30,60)),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE calculated_tag_inputs (
  calc_tag_id   BIGINT   NOT NULL REFERENCES calculated_tags(tag_id) ON DELETE CASCADE,
  position      SMALLINT NOT NULL CHECK (position BETWEEN 1 AND 8),   -- IN1..IN8 (MAX_SCRIPT_PORTS)
  source_tag_id BIGINT   NOT NULL REFERENCES tags(id) ON DELETE RESTRICT,
  PRIMARY KEY (calc_tag_id, position),
  CHECK (source_tag_id <> calc_tag_id)
);
```

`uq_tags_connection_name` permanece (NULL é distinto no Postgres, não restringe as calculadas).
`ON DELETE RESTRICT` na origem: apagar tag usada por uma calculada vira **409**, não um script quebrado
em silêncio. Nenhuma hypertable nova, nenhuma policy de retenção nova (D1).

## 4. task_list (fatias verticais, ordem de execução)

| # | Fatia | Arquivos | Depende de |
|---|-------|----------|-----------|
| 1 | **ADR-033 + PRD** — canal `calc.values`, serviço `calc-worker`, tag calculada como linha de `tags`, fronteiras D5; linha em PRD §7.1, linha em §3, RF-208..212 em §5.3 | `docs/adr/ADR-033-tags-calculadas.md`, `docs/PRD.md` | — |
| 2 | **Core: primitivas compartilhadas** — mover `script_pool.py` e `snapshot.py` para `ottima_core`, `output_names` no `run()`, `ValueSnapshot(patterns=...)`, `CHANNEL_CALC_VALUES`, `KIND_CALC_TAG_*`, extrair `check_script_code()` de `flowgraph/validate.py` | `packages/ottima-core/src/ottima_core/{script_pool,snapshot,bus}.py`, `flowgraph/validate.py`, imports+testes do flow-runtime | 1 |
| 3 | **Core: modelo + schemas + migration** — `CalculatedTag`, `CalculatedTagInput`, `Tag` relaxado, `0012_calculated_tags`, `models/__init__.py`, schemas `calculated_tags.py`, `TagOut` com `connection_id/node_id` opcionais + `project_id` | `packages/ottima-core/{src/ottima_core/models,src/ottima_core/schemas,alembic/versions}` | 1 |
| 4 | **API: CRUD `/api/calculated-tags`** — list/create/get/patch/delete numa transação (tag + spec + inputs ordenados), validação de save (AST dunder, `compile`, `OUT` atribuído, `IN{i}` ≤ nº de inputs, 422 pt-BR), eventos de auditoria, 409 no delete de tag-origem | `services/api/src/ottima_api/routers/calculated_tags.py`, `app.py`, `routers/tags.py` | 3 |
| 5 | **calc-worker: runner de uma tag** — `CalcTagRunner`: loop de período, coleta IN1..INn do snapshot, `ScriptPool.run(output_names=("OUT",))`, publica `OpcValue` em `calc.values`, hold do último valor bom + latch/dedupe de evento (timeout/erro/recovered), `state` persistente | `services/calc-worker/src/ottima_calc_worker/runner.py` | 2, 3 |
| 6 | **calc-worker: supervisor + processo** — poll de watermark 10 s + hint pelo canal `events`, uma task por tag do projeto ativo, diff spawn/teardown/reconfig, `main.py` (lifespan + `/health` na 8004), `pyproject.toml` | `services/calc-worker/**` | 5 |
| 7 | **Deploy + health agregado** — serviço no compose (`PACKAGE: ottima-calc-worker`, 8004, sem volume de certs), `Settings.health_url_calc_worker`, 4º braço em `/api/health/workers`, `.env.example` | `deploy/docker-compose.yml`, `packages/ottima-core/src/ottima_core/config.py`, `services/api/src/ottima_api/routers/health.py` | 6 |
| 8 | **Consumidores do canal novo** — `PatternListener`/`ChannelListener` de `calc.values` no recorder e no `/ws`; prefixo no `CanalAoVivo.tsx` | `services/recorder/src/ottima_recorder/pipeline.py`, `services/api/src/ottima_api/ws.py`, `frontend/src/app/CanalAoVivo.tsx` | 3 |
| 9 | **Frontend: form + lista** — `TagCalculadaForm.tsx` (Card inline, período `<Select>`, lista ordenada IN1..INn add/remover/subir/descer, `<textarea>` no padrão `CamposScript`), `useCalculatedTags.ts`, `calcTag.ts` + `calcTag.check.ts`, botão e coluna em `TagsPage.tsx` | `frontend/src/features/tags/**`, `frontend/src/lib/api.ts` | 4 |
| 10 | **Trend: seletor** — incluir tags calculadas do projeto ativo no picker | `frontend/src/features/trend/TrendPage.tsx` | 3 |
| 11 | **Export/import (D6)** — `BundleTag` com campos de tag calculada, `montar_bundle`, importador | `packages/ottima-core/src/ottima_core/portability/**`, `services/api/src/ottima_api/routers/projects.py` | 3 |
| 12 | **Verificação** — L1 smoke, `uv run pytest`, `ruff`, `npm run build`, `npm run test:unit`, roteiro de browser na tela Tags com valor vivo chegando pelo WS | — | todas |

## 5. Testes (TDD, RED primeiro — CLAUDE.md §Testes)

Lógica pura (RED→GREEN obrigatório): mapeamento posicional IN1..INn, `output_names=("OUT",)` no pool,
timeout = 0,7 × período, hold do último valor bom, latch/dedupe de evento, validação de save
(dunder, `OUT` ausente, `IN{i}` fora do range), invariante `ck_tags_owner`, unicidade de nome por projeto,
409 ao apagar tag-origem.

Worker (padrão `test_supervisor.py`): Timescale + Redis reais via testcontainers, `await_until`,
uma task por tag, script travado mata só o worker do pool e re-sobe, tag removida do banco → task
encerrada sem vazar (`_tasks_do_worker`), falha de uma tag não interrompe a cadência da outra.

Frontend: `calcTag.check.ts` no padrão `*.check.ts`.

## 6. Riscos

1. `TagOut.connection_id` vira `int | None` → tipos gerados mudam; `FlowEditorPage.tsx:365` e
   `TrendPage.tsx:83-86` filtram por `connection_id` (comportamento preservado: calculadas ficam fora
   do editor por D5, e entram no Trend por fatia 10).
2. `bundle.py:33` daria `KeyError` se uma tag calculada chegasse ao export sem a fatia 11.
3. Modelo de ameaça segue ADR-018 (admin autenticado, sem sandbox pesado). A superfície aumenta:
   antes só quem edita flow executava código; agora quem cria tag também. Mesma proteção
   (`ALLOWED_BUILTINS` sem `__import__`, `os.environ.clear()` no worker, AST sem dunder, processo
   separado) e mesmo papel exigido (`require_admin`).
4. Alembic 0012 altera tabela existente. `downgrade()` precisa recusar (ou limpar) tags calculadas
   antes de voltar `connection_id` para NOT NULL.
