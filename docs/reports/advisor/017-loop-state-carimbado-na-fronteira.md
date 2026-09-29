# Plan 017: `loop.state` passa a ser carimbado na fronteira da varredura, não no relógio de parede

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado antes de passar ao próximo. Se qualquer condição da seção "Condições de
> PARADA" ocorrer, pare e relate — não improvise. Ao terminar, atualize a sua linha na tabela de
> status de `docs/reports/advisor/README.md` — a menos que um revisor o tenha despachado e dito que
> ele mantém o índice.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 37b0caa..HEAD -- services/flow-runtime/src/ottima_flow_runtime/blocks/shell services/flow-runtime/tests services/recorder/src/ottima_recorder/pipeline.py`
> Se qualquer arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; em caso de divergência, trate como
> condição de PARADA.

## Status

- **Prioridade**: P2
- **Esforço**: S
- **Risco**: LOW — encanamento de um timestamp; nenhuma semântica de controle se move
- **Depende de**: nenhum
- **Categoria**: bug
- **Planejado em**: commit `37b0caa`, 2026-09-19

## Por que isso importa

Todo sinal historiado deste sistema é ancorado na **fronteira da varredura** (`fired_ts`) — tags
via `_historized_value`, estado e predição do MPC. O bloco shell (ADR-039, que hospeda PID e Fuzzy)
é a exceção: ele carimba `LoopState.ts` com `datetime.now(UTC)` no instante em que monta o payload.

Esse instante fica **depois** de `await self._flush_events()` — ou seja, na varredura em que houve
troca de modo ou alarme de nível, o carimbo é empurrado pelo tempo de um ida-e-volta real ao Redis.
O desvio é **correlacionado com o evento**: é pior exatamente nos momentos em que o engenheiro mais
precisa de tempo exato na tendência, porque está investigando o que aconteceu em torno daquela
transição.

O dado não é só exibido: `LoopState.ts` é o timestamp **persistido** de toda amostra `pv`/`sp`/`out`
de malha (`services/recorder/src/ottima_recorder/pipeline.py`, `_append_loop(state.ts, ...)`), na
hypertable `loop_samples`. Então a série histórica de malha fica numa grade ligeiramente diferente
da de todos os outros sinais com que ela é sobreposta.

O bloco MPC resolve isso explicitamente, e o docstring dele é a regra da casa —
`services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:1133-1136`:
```python
    def _build_state(self, ts: datetime) -> MpcState:
        """`ts` vem de quem chama: a fronteira de varredura nas publicações de fronteira
        (spec F5 §2.1-1), o instante da própria publicação nas imediatas (mudança de modo,
        SP/MV materializada — F4 §5.2). Nunca decidido aqui."""
```
"Nunca decidido aqui" é precisamente o que o shell faz de errado.

E o `ts` já está disponível: `step()` o recebe. Ele só não é repassado.

## Estado atual

**O scheduler já entrega `ts` a todo bloco, toda varredura** —
`services/flow-runtime/src/ottima_flow_runtime/blocks/base.py:83-86`:
```
`flow.status.ts` (`FlowTask._run`, spec F5 §2.1): o scheduler passa `fired_ts`
para TODO bloco em toda varredura. A maioria dos blocos não carimba nada por si e
ignora o parâmetro; hoje só o MPC usa (spec §2.1/§3.5, `ts`/`prediction.ts` de `mpc.state`).
```

**`step` recebe `ts`** — `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py:204-207`:
```python
    async def step(
        self, inputs: Mapping[str, Signal], *, ts: datetime | None = None
    ) -> dict[str, Signal]:
        dt = self._measure_dt(ts)
```

**`step` tem QUATRO retornos, todos descartando o `ts`** — `block.py:234`, `:251`, `:270` e `:275`,
os quatro literalmente:
```python
            return await self._finish(inputs)
```
Eles são os quatro caminhos de saída de `step`: `dt` inválido/scan perdido (`:234`), modo forçado
(`:251`), erro de kernel / `du` não finito (`:270`) e o caminho normal (`:275`).

> **Consequência de errar a contagem**: `_finish` vai passar a receber `ts` **sem valor default**.
> Encanar só dois dos quatro faz os outros dois levantarem
> `TypeError: _finish() missing 1 required positional argument: 'ts'` — em tempo de execução, nos
> caminhos **degradado e de alarme**, dentro de um bloco que escreve na planta. Pior ainda: um gate
> que esperasse `2` ficaria **verde** sobre esse estado quebrado. Por isso o gate deste plano exige
> `4`.

**`_finish` não recebe `ts`** — `block.py:411`:
```python
    async def _finish(self, inputs: Mapping[str, Signal]) -> dict[str, Signal]:
```

**E publica depois do flush de eventos** — `block.py:430-436`:
```python
        await self._flush_events()
        if self._publish_state is not None:
            agora = time.monotonic()
            if agora - self._last_publish >= LOOP_STATE_MIN_INTERVAL_S:
                self._last_publish = agora
                await self._publish_state(self._loop_state())
        return self._emit()
```

**O carimbo** — `block.py:469-472`:
```python
    def _loop_state(self) -> LoopState:
        cfg = self.cfg
        return LoopState(
            ts=datetime.now(UTC),
```

> Note que `LOOP_STATE_MIN_INTERVAL_S` (throttle ~4 Hz, ADR-039) usa `time.monotonic()` — isso está
> **certo** e não muda. Monotônico é o relógio correto para medir intervalo; o que está errado é usar
> relógio de parede para **carimbar a amostra**. São duas coisas diferentes no mesmo bloco de código;
> não confunda as duas.

## Convenções do repositório que se aplicam aqui

- **Python ≥ 3.12**, type hints obrigatórios, `ruff` (100 cols).
- **O `ts` vem de quem chama, nunca é decidido no construtor do payload** — regra estabelecida pelo
  docstring de `MpcBlock._build_state` (`mpc.py:1133-1136`). Este plano estende essa regra ao shell.
- **Fallback só onde faz sentido**: `step(ts=None)` é o caminho de teste unitário sem scheduler. O
  MPC trata o caso análogo publicando com o instante da publicação. Mantenha `datetime.now(UTC)`
  como fallback **apenas** quando `ts` for `None`.
- **Comentários em pt-BR explicando o porquê**, no estilo denso do arquivo.
- **TDD estrito em lógica pura** (`CLAUDE.md`, "Testes").
- **Commits em Conventional Commits, mensagem pt-BR.**

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Lint | `uv run ruff check .` | exit 0 |
| Formato | `uv run ruff format --check .` | exit 0 |
| Testes do shell | `uv run pytest services/flow-runtime/tests -q -k shell` | tudo passa |
| Testes do runtime | `uv run pytest services/flow-runtime/tests -q` | tudo passa |
| Testes do recorder | `uv run pytest services/recorder -q` | tudo passa |
| Sem relógio de parede no carimbo | `grep -n 'datetime.now' services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py` | só o fallback |

**NÃO rode** `uv run pytest` sem recorte de pasta (~20 min, testcontainers; TD-028 é um flaky
conhecido **exatamente em** `services/flow-runtime/tests/test_supervisor.py:265` — se ele falhar,
**não é regressão sua**; confirme rodando o arquivo isolado e registre no relato).

**NÃO rode** `docker compose`, `deploy/smoke.sh`, `pytest -m e2e`, `npx playwright test` sem
`--list` — o stack de 8 serviços do dono está no ar com planta simulada viva.
**NÃO invoque** nenhuma ferramenta do servidor MCP `ottima` desta sessão.

## Escopo

**Em escopo** (únicos arquivos a modificar):
- `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py`
- `services/flow-runtime/tests/test_shell_block_basics.py` — o teste novo vai aqui. O diretório tem
  um harness próprio, `services/flow-runtime/tests/shell_harness.py`: **leia-o primeiro e use-o**,
  não construa o bloco à mão nem crie fixture nova.

**Fora de escopo** (NÃO toque, mesmo parecendo relacionado):
- `services/recorder/src/ottima_recorder/pipeline.py` — ele **já** persiste `state.ts` corretamente.
  O defeito é a origem do carimbo, não o consumidor.
- `packages/ottima-core/src/ottima_core/bus.py` (`LoopState`) — o campo `ts` já existe e já é
  `datetime`. **Nenhuma mudança de contrato de barramento**, nenhum canal novo (ADR-002).
- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py` — é o modelo, não o alvo.
- `LOOP_STATE_MIN_INTERVAL_S` e o throttle por `time.monotonic()` — **corretos**, não mexa.
- `blocks/kernels/pid.py` e `blocks/kernels/fuzzy.py` — o kernel não carimba nada.
- `services/flow-runtime/src/ottima_flow_runtime/scheduler.py` — já passa o `ts`.
- Migrations, `docs/`, frontend.

## Fluxo de git

- Branch: `advisor/017-loop-state-fronteira`.
- Um commit. Sugestão:
  `fix(flow-runtime): loop.state carimba a fronteira da varredura, nao o relogio de parede`
- Sem push, sem PR, a menos que o operador peça.
- Em worktree: caminho **ABSOLUTO** em todo `read`/`write`/`edit`, `cwd` explícito em todo shell,
  confirmação por shell depois de cada escrita (`CLAUDE.md`, "Subagente em worktree").

## Passos

### Passo 1: o teste que falha (RED)

No arquivo de teste do shell, acrescente um teste que prove que o carimbo é o da varredura:

- Construa um `BlockShell` (siga exatamente a forma de construção dos testes vizinhos — leia um
  inteiro antes; não invente fixture nova).
- Chame `await bloco.step(inputs, ts=TS)` com um `TS` fixo e **distante do relógio real** (ex.:
  `datetime(2020, 1, 1, tzinfo=UTC)`), com `_publish_state` capturando o `LoopState` publicado.
- Asserte `publicado.ts == TS`.

> **REGRA DO TESTE: um `step()` por instância nova, e asserte só a PRIMEIRA publicação.**
>
> O publish é estrangulado: `block.py:431-435` só publica quando
> `time.monotonic() - self._last_publish >= LOOP_STATE_MIN_INTERVAL_S` (0,25 s), e `_last_publish`
> nasce `0.0` (`:117`). Como `time.monotonic()` é uptime do processo (≫ 0,25), a **primeira**
> publicação sempre sai. Mas um **segundo** `step()` no mesmo teste roda microssegundos depois e é
> **estrangulado** — um teste que dê dois `step()` com `ts` diferentes esperando dois `LoopState`
> recebe **um** e falha por um motivo que não tem nada a ver com o conserto.
>
> As duas saídas óbvias estão **fechadas de propósito**: mexer no throttle é proibido pelos
> critérios de conclusão deste plano, e `sleep(0.25)` reintroduziria exatamente o gate por relógio
> de parede que é a classe de defeito do TD-027/TD-028 (e que a nota ao revisor deste plano exige
> evitar).
>
> Portanto: **cada caso constrói uma instância nova, chama `step()` uma vez, e asserta a
> publicação que saiu dessa chamada.** Não encadeie varreduras para comparar carimbos.

Acrescente também o caso do fallback: `await bloco.step(inputs)` **sem** `ts` ⇒ `publicado.ts` é um
`datetime` com tzinfo UTC (não asserte o valor, só que é aware e recente).

**Verifique**: `uv run pytest services/flow-runtime/tests -q -k shell` → **o primeiro teste FALHA**,
com `publicado.ts` sendo o horário real em vez de `TS`. Registre a saída real no relato — é a prova
de que o teste morde.

### Passo 2: encanar o `ts`

Três edições em `block.py`, todas mecânicas:

1. `_loop_state` passa a receber o carimbo:
   ```python
   def _loop_state(self, ts: datetime) -> LoopState:
       cfg = self.cfg
       return LoopState(
           ts=ts,
   ```
2. `_finish` passa a receber e repassar:
   ```python
   async def _finish(self, inputs: Mapping[str, Signal], ts: datetime | None) -> dict[str, Signal]:
   ```
   e, no ponto de publicação (`:435`):
   ```python
   await self._publish_state(self._loop_state(ts if ts is not None else datetime.now(UTC)))
   ```
   Acrescente um comentário curto em pt-BR registrando o porquê, no estilo do arquivo — por exemplo:
   *"Carimbo é a fronteira da varredura, nunca o instante do publish: o `_flush_events` acima pode
   custar um ida-e-volta ao Redis, e o desvio ficaria correlacionado com troca de modo/alarme.
   Mesma regra de `MpcBlock._build_state`. `None` só no caminho de teste sem scheduler."*
3. Os **QUATRO** `return await self._finish(inputs)` passam a `return await self._finish(inputs, ts)`.
   Eles estão em `block.py:234`, `:251`, `:270` e `:275` — confirme a lista com
   `grep -n 'self._finish(' services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py`
   (a chamada de definição, `:411`, também aparece nesse grep; ela é a `def`, não um call site).

**Atenção**: são **quatro** call sites, um por caminho de saída de `step` — saída antecipada por
`dt` inválido/scan perdido (`:234`), saída por modo forçado (`:251`), saída por erro de kernel
(`:270`) e o caminho normal (`:275`). Perder qualquer um deixa aquele caminho ainda no relógio de
parede, e os três primeiros são justamente os **anômalos**, onde o tempo exato importa mais.

**Verifique**:
- `uv run pytest services/flow-runtime/tests -q -k shell` → tudo passa, incluindo os do Passo 1
- `grep -c '_finish(inputs, ts)' services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py` → `4`
- `uv run ruff check services/flow-runtime` → exit 0

### Passo 3: gates finais

- `uv run ruff check .` → exit 0
- `uv run ruff format --check .` → exit 0
- `uv run pytest services/flow-runtime/tests -q` → tudo passa (exceto TD-028, se aparecer — justifique)
- `uv run pytest services/recorder -q` → tudo passa
- `git diff -- packages services/recorder` → **vazio**
- `git status --porcelain` lista só os arquivos em escopo

## Plano de teste

- **Novos**: 2 no arquivo de teste do shell — carimbo igual ao `ts` da varredura; fallback aware
  quando `ts is None`.
- **Padrão estrutural**: os testes vizinhos do shell (`test_*loop*`/`test_shell*` em
  `services/flow-runtime/tests/`). Leia um inteiro antes de escrever.
- **O repo não usa `unittest.mock`** (zero ocorrências, verificado). Não introduza; capture o
  publish com um callable simples, como os testes vizinhos fazem.
- **Não** escreva teste que dependa de `sleep` nem de relógio de parede — essa é a classe de defeito
  já registrada três vezes neste repo (TD-008, TD-027, TD-028). O teste do Passo 1 é determinístico
  exatamente porque injeta `ts`.
- **Nenhum teste existente deve mudar.** Se algum asserta o `ts` de `LoopState` contra o horário
  real, ele estava pinhando o defeito — nesse caso **pare e relate**, não o reescreva sozinho.
- **Verificação**: `uv run pytest services/flow-runtime/tests -q` → tudo passa.

## Critérios de conclusão

- [ ] `_loop_state` recebe `ts: datetime` como parâmetro
- [ ] `_finish` recebe `ts: datetime | None` e o repassa
- [ ] `grep -c '_finish(inputs, ts)' .../blocks/shell/block.py` → `4` (os quatro call sites)
- [ ] `datetime.now(UTC)` aparece em `block.py` **apenas** como fallback de `ts is None`
- [ ] O throttle por `time.monotonic()` e `LOOP_STATE_MIN_INTERVAL_S` estão intocados
- [ ] 2 testes novos passando; o RED do Passo 1 registrado no relato
- [ ] `git diff -- packages/ottima-core/src/ottima_core/bus.py` → **vazio** (contrato inalterado)
- [ ] `git diff -- services/recorder` → **vazio**
- [ ] `uv run ruff check .` e `ruff format --check .` → exit 0
- [ ] `uv run pytest services/flow-runtime/tests -q` → tudo passa (TD-028 justificado, se ocorrer)
- [ ] `git status --porcelain` lista só os arquivos em escopo
- [ ] Linha de status atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

- Os excertos de "Estado atual" não baterem com o código vivo (drift desde `37b0caa`).
- `_finish` tiver um número de call sites **diferente de quatro**: relate todos, não adapte em silêncio.
- Um teste existente assertar `LoopState.ts` contra o horário real: ele pinha o defeito. **Pare e
  relate** — mudar teste alheio para acomodar conserto exige decisão de quem o escreveu.
- Você concluir que é preciso mudar `LoopState` em `bus.py`: **não é**. O campo já é `datetime`.
- Você concluir que o throttle deveria passar a usar `ts` em vez de `time.monotonic()`: **não**.
  Monotônico é o relógio certo para medir intervalo. Relate se discordar.
- `test_supervisor.py:265` falhar: é o **TD-028**, registrado. Não conserte aqui.

## Notas de manutenção

- **O que interage com isto**: qualquer kernel novo da fábrica ADR-039 D8 — todos passam por
  `BlockShell.step`/`_finish`, então herdam o carimbo correto de graça.
- **O que um revisor deve olhar no PR**: (1) os **quatro** call sites de `_finish` alterados — conte-os,
  porque encanar só alguns quebra os demais com `TypeError` em runtime; (2)
  `datetime.now(UTC)` sobrando só no fallback; (3) `bus.py` e `recorder` intocados; (4) o teste é
  determinístico (injeta `ts`), sem `sleep`.
- **Achado vizinho, deliberadamente fora**: `FuzzyState.ok` ainda é `bool` cru pós-ADR-043
  (`blocks/fuzzy.py:231-236`, com comentário do próprio autor dizendo "fora do escopo desta
  migração (Task 4)"), enquanto `PortValue`/`ExchangeValue`/`LoopState` já carregam o tri-state. É
  migração de contrato entre serviços (bus + recorder + frontend), não encanamento local. Está no
  índice como vetado sem plano.
