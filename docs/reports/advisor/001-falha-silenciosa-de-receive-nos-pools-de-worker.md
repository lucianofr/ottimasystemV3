# Plan 001: Toda falha de `recv()` nos dois pools de worker vira resultado sintético + respawn, nunca uma task morta em silêncio

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de
> verificação e confirme o resultado esperado antes de passar ao próximo passo. Se
> qualquer condição da seção "Condições de PARADA" ocorrer, pare e relate — não
> improvise. Ao terminar, atualize a linha de status deste plano em
> `docs/reports/advisor/README.md`.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 8f9fe76..HEAD -- services/flow-runtime/src/ottima_flow_runtime/mpc/host.py packages/ottima-core/src/ottima_core/script_pool.py`
> Se algum arquivo em escopo mudou desde que este plano foi escrito, compare os
> excertos de "Estado atual" com o código vivo antes de prosseguir; divergência é
> condição de PARADA.

## Status

- **Prioridade**: P1
- **Esforço**: S
- **Risco**: LOW
- **Depende de**: `docs/reports/advisor/004-flaky-do-ts-do-mpc-contra-flow-status.md` — obrigatório,
  ver "Teste flaky conhecido" abaixo. Sem o 004, o critério de conclusão deste plano é
  vermelho por um motivo alheio a ele.
- **Categoria**: bug
- **Planejado em**: commit `8f9fe76`, 2026-08-16

## Teste flaky conhecido nesta suíte — leia antes de rodar qualquer coisa

`services/flow-runtime/tests/test_supervisor_mpc.py::test_mpc_state_ts_de_execucao_bate_bit_a_bit_com_flow_status`
**é flaky no commit `8f9fe76`, antes de qualquer mudança sua.** Medido: passa 3 de 3 vezes
rodado isolado (~11 s cada) e falha ao rodar o arquivo inteiro (28 testes, 127 s), com esta
mensagem:

```
AssertionError: MpcState.ts de uma execucao de fronteira precisa bater bit a bit com o ts de
ALGUMA varredura publicada em flow.status — mesmo relogio (spec F5 SS2.1)
```

A causa é uma barreira fraca no próprio teste (ele espera UMA mensagem de `flow.status` e
compara com o ÚLTIMO `mpc.state`; os dois canais são independentes e fire-and-forget,
ADR-002), e o plano 004 a corrige. Nada disso tem relação com `MpcHost`.

Isto importa muito para você porque `test_supervisor_mpc.py` exercita `MpcHost`
diretamente, com spawn real de processo. Se você vir esse teste vermelho depois de editar
`host.py`, a conclusão natural e ERRADA é que a sua mudança causou a falha.

**Regra**: execute o plano 004 antes deste. Se por qualquer motivo isso não for possível,
e esse teste específico ficar vermelho, rode-o isolado
(`uv run pytest 'services/flow-runtime/tests/test_supervisor_mpc.py::test_mpc_state_ts_de_execucao_bate_bit_a_bit_com_flow_status' -q`):
passando isolado, é o flaky conhecido e **não** é regressão sua — registre isso no relato e
siga. Qualquer OUTRO teste vermelho continua sendo condição de PARADA.

## Por que isso importa

`MpcHost` e `ScriptPool` são os dois lugares onde o processo pai espera um resultado
vindo de um subprocesso por `multiprocessing.Connection.recv()`. Os dois tratam
`EOFError`/`OSError` (pipe morreu) com cuidado e documentam a decisão. Nenhum dos dois
trata as OUTRAS exceções que `recv()` pode levantar — `pickle.UnpicklingError`,
`AttributeError`/`ImportError` na desserialização, `struct.error` num fluxo
truncado-mas-completo-no-header.

A consequência no `MpcHost` é a pior que este sistema admite: `self._busy` fica `True`
para sempre, `dispatch()` passa a devolver `False` em toda fronteira, e o bloco MPC
**congela a MV no último valor comandado enquanto continua se anunciando armado e em
REMOTO**. O próprio código documenta a invariante que esse caminho quebra, em
`blocks/mpc.py:682`: *"o `mpc_overrun` já saiu (ou sairá) pelo caminho de `poll()`
quando o host sintetizar o resultado"* — nesse caminho o host nunca sintetiza nada,
então nenhum evento sai e o operador não recebe sinal nenhum de que o controlador
parou de otimizar.

No `ScriptPool` a consequência é um encolhimento silencioso: o worker sai de rotação
sem voltar para a fila de livres e sem ser reposto, e no boot handshake sobra um
processo do SO órfão em `self._state.workers`.

Depois deste plano: qualquer falha de recebimento nos dois pools produz o mesmo
resultado sintético e o mesmo respawn que uma morte de pipe já produz hoje.

## Estado atual

Arquivos e papéis:

- `services/flow-runtime/src/ottima_flow_runtime/mpc/host.py` — dono do subprocesso do
  solver do-mpc/IPOPT. `_receive` (função de módulo, roda em thread), `dispatch()`,
  `_await_response()` (task de segundo plano), `_schedule_respawn()`.
- `packages/ottima-core/src/ottima_core/script_pool.py` — pool de workers que executam
  código Python do usuário (ADR-018/033). `_receive` (função de módulo), `run()`,
  `_enqueue_when_ready()`.

### `mpc/host.py:102-110` — o `except` estreito

```python
def _receive(conn: Connection, timeout_s: float) -> Any:
    """Espera uma mensagem no pipe com timeout. Roda **numa thread** — nunca no event loop
    (ADR-004), mesmo padrão de `script_pool._receive`."""
    try:
        if not conn.poll(timeout_s):
            return None
        return conn.recv()
    except (EOFError, OSError):
        return _CRASHED
```

`_CRASHED` é um sentinela de módulo (`host.py:96`) e o contrato dos três retornos está
documentado em `host.py:97-99`: `None` = deadline estourado, `_CRASHED` = pipe morreu,
qualquer outra coisa = o `SolveResult` real.

### `mpc/host.py:290-314` — o `await` sem rede

```python
    async def _await_response(self, conn: Connection) -> None:
        """Task criada por `dispatch()`: espera a resposta (ou o deadline, ou um crash) do
        pedido que acabou de ser mandado por `conn` — `conn` é passado por parâmetro, não
        lido de `self._conn`, para nunca correr atrás de um respawn concorrente que troque
        o pipe embaixo desta espera."""
        outcome = await self._off_loop(partial(_receive, conn, self._deadline_s))
        self._busy = False

        if outcome is None:
            # Deadline de 0.7xTs_mpc estourado, medido do dispatch (spec §4.2).
            self._pending_result = empty_result(
                status="overrun",
                detail="orçamento de 70% do Ts_mpc excedido",
                wall_ms=self._deadline_s * 1000.0,
            )
            self._schedule_respawn()
            return

        if outcome is _CRASHED:
            self._pending_result = empty_result(status="error", detail="crash", wall_ms=0.0)
            self._schedule_respawn()
            return

        self._last_solve_ms = outcome.wall_ms
        self._pending_result = outcome
```

Se o `await` da linha 295 levantar, a linha 296 (`self._busy = False`) nunca roda.

### `mpc/host.py:242-245` — a task cuja exceção ninguém observa

```python
        self._busy = True
        task = asyncio.get_running_loop().create_task(self._await_response(conn))
        self._background.add(task)
        task.add_done_callback(self._background.discard)
```

Compare com o padrão que o próprio serviço já usa em
`services/flow-runtime/src/ottima_flow_runtime/supervisor_mpc.py`: lá as tasks de
segundo plano recebem um callback `_log_se_falhou` que chama `task.exception()` e loga
com `flow_id`/`block_id`. Aqui só há `discard`, então a exceção cai no handler default
do asyncio ("Task exception was never retrieved"), sem identificação do flow nem do
bloco.

### `mpc/host.py:223` — por que o travamento é permanente

```python
        if self._stopped or not self._ready or self._busy:
            return False
```

### `script_pool.py:186-194` — `_receive` sem nenhum tratamento

```python
def _receive(conn: Connection, timeout_s: float) -> Any:
    """Espera um resultado no pipe. Roda **numa thread** — nunca no event loop (ADR-004).

    `poll` e `recv` na mesma thread: `poll` só garante que há bytes, não a mensagem inteira,
    então deixar o `recv` para o event loop reintroduziria o bloqueio que se quer evitar.
    """
    if not conn.poll(timeout_s):
        return None
    return conn.recv()
```

### `script_pool.py:352-375` — o `except` estreito do `run()`

```python
            await self._off_loop(partial(worker.conn.send, (code, inputs, state, names)))
            result = await self._off_loop(
                partial(_receive, worker.conn, max(0.0, deadline - loop.time()))
            )
        except asyncio.CancelledError:
            # O worker pode estar rodando código arbitrário do usuário: devolvê-lo à fila é
            # inaceitável — kill + respawn, e o cancelamento segue propagando. `_replace`
            # (abaixo) já se blinda contra uma segunda cancelação chegando aqui — ver o
            # docstring dela para a interleaving exata que isso fecha (débito m3).
            await self._replace(worker, hard=True)
            raise
        except (OSError, EOFError, ValueError):
            await self._replace(worker, hard=False)
            return ScriptResult("error", None, None, "o worker do pool morreu durante o script")

        if result is None:
            await self._replace(worker, hard=True)
            return ScriptResult("timeout", None, None, None)
        if not isinstance(result, ScriptResult):
            await self._replace(worker, hard=True)
            return ScriptResult("error", None, None, "o worker do pool devolveu lixo no pipe")

        self._idle.put_nowait(worker)
        return result
```

Uma exceção fora da tupla da linha 363 escapa sem passar por `_idle.put_nowait` (linha
374) nem por `_replace` (linhas 361/364/368/371) — o worker desaparece de rotação.

### `script_pool.py:388-394` — o mesmo `except` estreito no boot

```python
    async def _enqueue_when_ready(self, worker: _Worker) -> None:
        """Só entra na fila de livres depois do handshake — um worker ainda importando numpy
        consumiria o orçamento de quem o pegasse."""
        try:
            ready = await self._off_loop(partial(_receive, worker.conn, _BOOT_TIMEOUT_S))
        except (OSError, EOFError, ValueError):
            ready = None
```

O tratamento correto já está logo abaixo (linhas 395-409: remove de
`self._state.workers`, publica evento, `_shutdown(hard=True)`), e ele é alcançado por
`ready = None`. Uma exceção fora da tupla pula tudo isso.

### Convenções do repositório que se aplicam aqui

- Comentários e mensagens de erro em **pt-BR**; identificadores em inglês
  (`CLAUDE.md:69`). O `GLOSSARY.md` é o cânone de tradução.
- `ruff` cobre lint e formato, `line-length = 100`, `select = ["E","F","I","UP","B","ASYNC"]`.
- Tipos obrigatórios em toda assinatura nova (`CLAUDE.md:67`).
- **Sem emoji** em código, comentário ou documentação.
- Exemplar de estilo para o tratamento de falha de worker: leia
  `packages/ottima-core/src/ottima_core/script_pool.py:395-409` (o caminho de boot
  falho, que já faz remoção + evento + shutdown) e
  `services/flow-runtime/src/ottima_flow_runtime/mpc/host.py:113-130`
  (`_shutdown_worker`, que "nunca levanta"). Combine com esses.

### Invariantes que este plano NÃO pode violar

- **ADR-004**: `recv()`/`poll()`/`send()` e criação de processo sempre FORA do event
  loop, via `self._off_loop`. Não mova nada para dentro do loop.
- **ADR-018**: o `ScriptPool` mata e repõe o processo no estouro; cada serviço tem o seu
  pool. Não compartilhe pool, não remova o kill.
- **spec §4.2 do MPC**: worker indisponível na fronteira conta como overrun e mantém a
  MV, sem acumular fila. O resultado sintético novo tem de manter esse contrato.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Ambiente | `uv sync --all-packages` | exit 0 |
| Lint | `uv run ruff check .` | `All checks passed!` |
| Formato | `uv run ruff format --check .` | `N files already formatted`, zero a reformatar |
| Testes do host MPC | `uv run pytest services/flow-runtime/tests/test_mpc_host.py -q` | todos passam |
| Testes do pool | `uv run pytest packages/ottima-core/tests/test_script_pool_executor.py packages/ottima-core/tests/test_script_pool_teardown.py -q` | todos passam |
| Suíte do flow-runtime | `uv run pytest services/flow-runtime/tests -q` | todos passam (ver "Teste flaky conhecido") |
| Suíte do core | `uv run pytest packages/ottima-core/tests -q` | todos passam |

Rode os comandos de dentro de `.worktrees/improve` (a raiz do workspace uv).
**NÃO rode `uv run pytest` sem filtro**: a suíte inteira leva ~19 minutos.

## Escopo

**Em escopo** (os únicos arquivos que você deve modificar):
- `services/flow-runtime/src/ottima_flow_runtime/mpc/host.py`
- `packages/ottima-core/src/ottima_core/script_pool.py`
- `services/flow-runtime/tests/test_mpc_host.py` (acrescentar testes)
- `packages/ottima-core/tests/test_script_pool_executor.py` (acrescentar testes)

**Fora de escopo** (NÃO toque, mesmo parecendo relacionado):
- `services/flow-runtime/src/ottima_flow_runtime/blocks/script.py` — o `await
  self._pool.run(...)` da linha 86 não tem `try/except`, então uma exceção que escape
  do pool derruba o flow inteiro em vez de só as saídas daquele bloco. Isso é real, mas
  mudar ali toca o contrato documentado "falha mantém as saídas verbatim" e exige teste
  próprio. Depois deste plano o pool não deixa mais exceção escapar, então o risco
  residual cai; a mudança de isolamento fica registrada em "Notas de manutenção".
- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py` — não mude a contagem
  de overrun nem o caminho de evento. Este plano faz o host voltar a cumprir o
  contrato que `blocks/mpc.py:682` já assume; o bloco não precisa mudar.
- `services/flow-runtime/src/ottima_flow_runtime/mpc/worker.py` e
  `packages/ottima-core/src/ottima_core/script_pool.py::_worker_main` — o lado FILHO do
  pipe. O defeito é no lado pai.
- Qualquer mudança no sentinela `_CRASHED` ou na assinatura de `empty_result`.

## Fluxo de git

- Branch: você já está em `improve`; commite nela (não crie branch nova, não faça push,
  não abra PR).
- Um commit por passo, ou um commit para os dois passos de produção e um para os testes.
- Padrão **Conventional Commits com mensagem em pt-BR** (`CLAUDE.md:70`). Exemplos reais
  do histórico deste repo:
  - `fix(core): pool de scripts e host MPC ganham executor de thread próprio`
  - `fix(opc-worker): escrita travada numa conexão não atrasa mais as demais`
  Para este plano, algo como:
  `fix(flow-runtime): falha de recv no host MPC vira crash sintético em vez de travar o dispatch`

## Passos

### Passo 1: `mpc/host.py` — `_receive` converte QUALQUER falha em `_CRASHED`

Em `_receive` (linha 102), troque a tupla `(EOFError, OSError)` por `Exception`. Ajuste
o docstring citando por que: `recv()` também levanta erro de desserialização
(`pickle.UnpicklingError` e parentes) num fluxo corrompido, e para o host isso é
indistinguível de "o worker morreu" — os dois levam ao mesmo respawn.

Não capture `BaseException`: `CancelledError` e `KeyboardInterrupt` têm de continuar
propagando.

**Verifique**: `uv run ruff check .` → `All checks passed!`

### Passo 2: `mpc/host.py` — `_await_response` blinda o `await` e a task passa a logar

Duas mudanças na mesma função (linha 290):

1. Envolva a linha 295 (`outcome = await self._off_loop(...)`) num `try/except
   Exception`. No `except`: logue com `logger.exception` incluindo o contexto que o
   host conhece, ponha `outcome = _CRASHED` e siga o fluxo normal — assim o ramo já
   existente da linha 308 produz o `empty_result(status="error", detail=...)` e chama
   `_schedule_respawn()`, sem duplicar lógica. Garanta que `self._busy = False` rode em
   TODOS os caminhos (use `finally` ou ponha a atribuição antes do tratamento).
   Detalhe importante: `_schedule_respawn()` é idempotente por construção
   (`host.py:316-323`), então chamá-lo pelo ramo de `_CRASHED` é seguro.
2. Em `dispatch()` (linha 243-245), acrescente um callback que observa a exceção da
   task, no mesmo espírito do `_log_se_falhou` de `supervisor_mpc.py`. Ele é defesa em
   profundidade: depois da mudança 1 a task não deveria mais levantar, e é exatamente
   por isso que uma exceção ali precisa aparecer no log com identificação, não no
   handler default do asyncio.

**Verifique**: `uv run pytest services/flow-runtime/tests/test_mpc_host.py -q` → todos
passam (nenhum teste existente deve quebrar; eles cobrem os caminhos de `None` e de
`_CRASHED`).

### Passo 3: `script_pool.py` — os dois `except` estreitos passam a cobrir `Exception`

1. Em `run()`, linha 363: `except (OSError, EOFError, ValueError):` → `except
   Exception:`. Mantenha o `except asyncio.CancelledError` ACIMA dele, intacto — a
   ordem importa, `CancelledError` não é subclasse de `Exception` no Python 3.12 mas o
   ramo dedicado documenta a decisão (débito m3) e tem de continuar sendo o primeiro.
   Mantenha a mensagem pt-BR existente.
2. Em `_enqueue_when_ready()`, linha 393: mesma troca. O `ready = None` resultante já
   leva ao tratamento correto das linhas 395-409 (remoção, evento, shutdown).
3. Opcional e recomendado, mesmo padrão do Passo 1: deixe `script_pool._receive`
   (linha 186) defensivo como o do host, para o caso de um chamador futuro. Se fizer,
   ele precisa distinguir "nada chegou" (`None`, que hoje significa timeout) de
   "falhou" — então NÃO devolva `None` numa exceção; deixe a exceção subir e seja
   tratada pelos `except Exception` dos passos 3.1/3.2. Se isso complicar, pule este
   sub-passo: 3.1 e 3.2 já fecham o defeito.

**Verifique**:
`uv run pytest packages/ottima-core/tests/test_script_pool_executor.py packages/ottima-core/tests/test_script_pool_teardown.py -q`
→ todos passam.

### Passo 4: testes

Ver "Plano de teste" abaixo.

**Verifique**: `uv run pytest services/flow-runtime/tests -q` e
`uv run pytest packages/ottima-core/tests -q` → ambos verdes, com os testes novos
contados. A única exceção tolerada é o flaky conhecido descrito no topo deste plano, e
só depois de você confirmar que ele passa isolado.

## Plano de teste

Escreva PRIMEIRO o teste vermelho de cada caso (TDD estrito é a regra do repo para
lógica pura — `CLAUDE.md:75`; aqui a lógica é de ciclo de vida, então o RED é
"reverta mentalmente o fix e o teste falha").

**Em `services/flow-runtime/tests/test_mpc_host.py`** — modele pelos testes já
existentes no arquivo, que usam workers-stub de módulo (o padrão
`mpc_host_echo_worker` e parentes). Acrescente um worker-stub que responde com um
payload que faz `recv()` levantar algo fora de `(EOFError, OSError)`. A forma mais
simples e determinística: um worker que escreve bytes crus inválidos no pipe (ou que
envia um objeto cuja desserialização falha no pai). Dois testes:

1. **`_busy` não fica preso**: depois da falha de receive, um `dispatch()` seguinte é
   ACEITO (devolve `True`) uma vez que o respawn conclua — hoje devolveria `False` para
   sempre. Este é o teste que prova o defeito.
2. **resultado sintético chega ao consumidor**: `poll()` devolve um `SolveResult` com
   `status == "error"` depois da falha, em vez de `None` eterno. É o que faz
   `blocks/mpc.py::_apply_result` emitir `mpc_solver_error` e o operador ver alarme.

**Em `packages/ottima-core/tests/test_script_pool_executor.py`** — um teste:

3. **o worker é reposto, o pool não encolhe**: depois de uma falha de receive fora da
   tupla antiga, `run()` devolve `ScriptResult` com `status == "error"` e uma chamada
   seguinte a `run()` é atendida (o pool voltou ao tamanho nominal). Sem o fix, a
   segunda chamada estoura por falta de worker livre.

Verificação: os comandos do Passo 4 acima, com 3 testes novos contados.

## Critérios de conclusão

Verificáveis por máquina. TODOS têm de valer:

- [ ] `uv run ruff check .` sai 0 com `All checks passed!`
- [ ] `uv run ruff format --check .` não lista arquivo a reformatar
- [ ] `uv run pytest services/flow-runtime/tests -q` verde — ou, se o plano 004 ainda não
      tiver sido executado, verde exceto o flaky conhecido, confirmado passando isolado
- [ ] `uv run pytest packages/ottima-core/tests -q` verde
- [ ] Os 3 testes novos existem e passam
- [ ] `grep -n "except (EOFError, OSError)" services/flow-runtime/src/ottima_flow_runtime/mpc/host.py`
      não retorna nada
- [ ] `grep -n "except (OSError, EOFError, ValueError)" packages/ottima-core/src/ottima_core/script_pool.py`
      não retorna nada
- [ ] `git status --porcelain` não lista arquivo fora da lista "Em escopo"
- [ ] Linha de status deste plano atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- Os excertos de "Estado atual" não corresponderem ao código vivo — o repositório
  mudou desde que este plano foi escrito.
- Um teste existente de `test_mpc_host.py` ou dos `test_script_pool_*.py` ficar
  vermelho depois da mudança. Isso significa que algum caminho DEPENDE de a exceção
  escapar, e a premissa deste plano ("nada depende disso") é falsa.
- Você não conseguir produzir a falha de desserialização de forma determinística em
  duas tentativas. Nesse caso relate: um teste flaky aqui é pior que teste nenhum, e
  há alternativa (injetar um `_receive` que levanta, via monkeypatch) que precisa de
  decisão sobre estar testando o contrato ou a implementação.
- A mudança parecer exigir tocar `blocks/script.py` ou `blocks/mpc.py` (ambos fora de
  escopo).

## Notas de manutenção

- **Follow-up deliberadamente deferido**: `blocks/script.py:86` chama
  `await self._pool.run(...)` sem `try/except`, e `ScriptBlock.step()` só trata o caso
  `result.status != "ok"`. Depois deste plano o pool não deixa mais exceção escapar por
  falha de receive, mas o isolamento estrutural continua sendo por disciplina, não por
  construção: uma exceção qualquer vinda do pool ainda sobe até
  `scheduler.py::FlowTask._scan` e derruba o FLOW inteiro (`state='failed'`), não só as
  saídas daquele bloco. Isso é parente próximo do TD-016/ARCH-11 (isolamento entre
  flows depende de disciplina de bloco) e deveria ser tratado junto com ele, não aqui.
- **O que um revisor deve escrutinar**: que `self._busy = False` roda em todos os
  caminhos de `_await_response`, incluindo o novo; e que a ordem dos `except` em
  `ScriptPool.run()` mantém `CancelledError` antes de `Exception`.
- **Interação futura**: se algum dia o `MpcHost` passar a multiplexar mais de um pedido
  em voo (hoje `_busy` é um booleano de um só slot), a correção deste plano precisa ser
  revisitada — o reset do estado deixa de ser um booleano.
