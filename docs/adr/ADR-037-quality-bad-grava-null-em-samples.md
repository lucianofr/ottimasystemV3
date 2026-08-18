# ADR-037 — `quality == BAD` grava NULL em `samples.value`, nunca o dado bruto

**Status:** Aceito · 2026-08-17

## Contexto
`RecorderPipeline.ingest_sample` (ADR-003, spec F2 §6.1) é um "dumb pipe": grava verbatim o que
chega em `opc.values.*`/`calc.values`, sem interpretar `kind`, sem filtrar severidade, sem validar
`tag_id` contra `tags`. Isso incluía o campo `value` mesmo quando o próprio payload já carrega
`quality = 2` (BAD, spec F1 §3.2) — um valor bruto, possivelmente sem sentido (nó offline, leitura
que falhou), ficava indistinguível de um dado real em `/api/history`, em tendências, e em qualquer
`avg`/`sum` que esqueça de filtrar por `quality`.

## Decisão

### `value = NULL`, linha sempre gravada, cadência inalterada
Quando `quality == 2` (BAD), `ingest_sample` grava `value = None` (SQL `NULL`) no lugar do valor
recebido; `ts`, `tag_id` e `quality` seguem exatamente o payload, e a linha é gravada com a MESMA
cadência de hoje — nunca pulada. Alternativa descartada: não gravar a linha. O CAgg `samples_1m`
(migration 0002) calcula `max(quality) AS worst_quality` por bucket — pular a linha faria um bucket
com só amostra ruim aparentar "nunca leu", regredindo essa agregação. NULL preserva a evidência
"tentamos ler, veio ruim" e a cadência que quem consome a série espera, sem exigir migração da view.

### NULL, não NaN — a escolha certa é a que os agregados SQL já sabem tratar
Primeira tentativa desta decisão usava `float("nan")`. Corrigida: **NaN se propagaria por
`avg`/`sum` (`NaN + x = NaN`) e por `max` (Postgres ordena NaN como maior que qualquer float, então
uma única amostra ruim vira o `MAX` do bucket inteiro)** — verificado empiricamente contra o
Postgres 17/TimescaleDB deste ambiente: `avg`/`max` sobre um conjunto com um `NaN` retornam `NaN`;
só `min` sobrevive (Postgres ordena NaN como "maior", então `min` o ignora, a menos que o bucket
inteiro seja NaN) — o que mascararia a corrupção parcial em vez de sinalizá-la. Um `samples_1m` de
1 minuto com 59 leituras boas e 1 ruim reportaria `avg_value`/`max_value = NaN` para o minuto
inteiro, apagando as 59 boas de qualquer tendência de janela longa (`/api/history` serve
`avg_value` como `v` no modo downsample, `RAW_WINDOW_HOURS` acima).

`NULL` não tem esse problema: `avg`/`sum`/`max`/`min`/`count(coluna)` do SQL **ignoram NULL
nativamente**, por definição do padrão — sem `FILTER (WHERE quality = 0)` em lugar nenhum, sem
migrar `samples_1m`. Um bucket com 3 amostras boas e 1 NULL reporta `avg`/`min`/`max` calculados só
sobre as 3 boas; um bucket 100% NULL reporta `NULL` nos três (comportamento correto: não há dado
finito nenhum ali). Verificado com teste real contra o CAgg (`test_bucket_1m_com_amostra_null_ignora_null_no_agregado`
e `test_bucket_1m_totalmente_ruim_devolve_tudo_null`, `services/api/tests/test_history.py`), não
só por leitura da definição SQL.

`NULL` também é a convenção JÁ EXISTENTE deste repo para "sem valor válido" — `mpc_samples.sp`
(`timeseries.py`) e `FuzzyVarState.v`/`PortSample.v` (`ottima_core/bus.py`) já usam `float | None`
com exatamente esse significado. `NaN` seria uma segunda convenção nova para o mesmo conceito; não
há nenhum precedente de NaN como sentinela em nenhum lugar do repo. `NULL` reusa o padrão.

### Só `quality == 2` (BAD) — não `quality == 1` (UNCERTAIN)
UNCERTAIN grava o valor real, sem mudança. Só BAD (o tri-state mais extremo, spec F1 §3.2) perde o
valor bruto.

### Escopo: só `samples`, via `ingest_sample`
`mpc_samples`/`fuzzy_samples` não têm coluna `quality` — usam um conceito diferente de invalidez
(`ok`) já tratado por decisão anterior (bloco MPC congela/reage a `ok=False`). `ingest_sample`
processa tanto `opc.values.*` quanto `calc.values` (ambos `OpcValue`, mesma tabela, ADR-033) — a
mudança cobre as duas origens sem código extra.

### Exceção estreita ao "dumb pipe", não reversão
O pipeline continua sem validar `tag_id` contra `tags`, sem filtrar por `kind`/severidade, sem
decidir SE grava — só substitui o valor de UM campo (`value`) quando o PRÓPRIO registro que está
sendo gravado já diz "não confie neste valor" (`quality`, mesmo payload). Nenhuma validação cruzada
nova. O docstring do módulo (`pipeline.py`) documenta a exceção.

### Migration 0013: `samples.value` relaxa para `nullable`
A coluna nasceu `DOUBLE PRECISION NOT NULL` na migration 0002. `ALTER TABLE samples ALTER COLUMN
value DROP NOT NULL` (migration 0013) é a única mudança de schema necessária; `timeseries.py`
(handle Core, fora do autogenerate — ver docstring do módulo) acompanha com `nullable=True`. O
downgrade apaga as linhas `value IS NULL` antes de reimpor `NOT NULL` (mesmo raciocínio de todo
downgrade que reaperta uma constraint relaxada: dado que só existe sob a constraint nova não
sobrevive à volta).

### `/api/history`: nenhum código novo de serialização
`HistorySeries.v`/`v_min`/`v_max` (`ottima_core/schemas/history.py`) passam de `list[float]`/
`list[float] | None` para `list[float | None]`/`list[float | None] | None` — mesmo padrão já usado
em `MpcHistorySeries.sp`. **A rota (`history.py`) não muda uma linha**: `samples_table.c.value`
devolve `None` do asyncpg quando a coluna é `NULL`, `samples_1m.avg_value`/`min_value`/`max_value`
idem quando o agregado não tem nenhum dado finito no bucket, e o `None` do Python serializa como
`null` no JSON nativamente — não existe "token `NaN` cru" a evitar, porque nunca existiu `NaN` em
lugar nenhum desta cadeia. (Uma primeira versão desta decisão cogitou um guard explícito
`_finito_ou_none()`/`math.isfinite()` na rota para essa conversão; removido — além de
desnecessário, `math.isfinite(None)` levantaria `TypeError` na primeira leitura de uma linha NULL
real, o que teria sido descoberto tarde se o teste de ponta a ponta não tivesse sido escrito antes
de confiar no guard.) `/ws` não é afetado: encaminha `OpcValue` ao vivo direto do barramento, nunca
lê de `samples`.

### Frontend: `q` já governa `v`, sem mudança necessária no consumo
`useHistory.ts` (`montarMatriz`/`resumirSeries`) já nunca lê `serie.v[i]` sem checar
`serie.q[i] === QUALIDADE_BAD` primeiro — todo ponto BAD já virava `null` na tela antes desta
decisão, driven by `q`, não por `v`. `v[i]` passar a ser `None`/`null` de verdade nesses índices não
muda nenhum caminho de leitura existente. `frontend/openapi.json` e os tipos TS gerados a partir
dele (`api-types.ts`, `HistorySeries.v: number[]`) ficam desatualizados quanto ao tipo declarado
(deveriam ser `(number | null)[]`) — fora do escopo desta mudança (só `services/recorder` e a rota
de `services/api` tocada); regenerar é um passo de follow-up sem risco de comportamento conhecido.

## Consequências
- (+) `/api/history`, tendências e qualquer consumidor de `samples.value` deixam de receber um
  valor bruto potencialmente sem sentido travestido de dado real quando `quality == 2`.
- (+) `avg`/`sum`/`max`/`min` sem filtro de `quality` ignoram a amostra ruim automaticamente — sem
  contaminar o bucket inteiro (a lição que descartou NaN) e sem precisar de `FILTER` em lugar
  nenhum.
- (+) `worst_quality` do CAgg (migration 0002) continua correto: a linha ruim não desaparece.
- (+) Reusa a convenção existente do repo (`float | None`) em vez de introduzir uma segunda para o
  mesmo conceito.
- (+) Nenhum código de serialização novo em `history.py`: `None` → `null` é nativo.
- (−) `frontend/openapi.json`/tipos TS gerados ficam desatualizados quanto ao tipo declarado de
  `v`/`v_min`/`v_max` até uma regeneração — sem impacto de comportamento verificado (`useHistory.ts`
  já gate por `q`, nunca por `v` diretamente), mas fora do escopo desta mudança.
- `quality == 1` (UNCERTAIN) não muda: valor real gravado, sem guard nenhum.
