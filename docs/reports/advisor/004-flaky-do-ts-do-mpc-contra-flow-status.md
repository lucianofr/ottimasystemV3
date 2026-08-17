# Plan 004: O teste de "mesmo relógio" entre `mpc.state` e `flow.status` espera o par certo chegar, em vez de esperar uma mensagem qualquer

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de
> verificação e confirme o resultado esperado antes de passar ao próximo passo. Se
> qualquer condição da seção "Condições de PARADA" ocorrer, pare e relate — não
> improvise. Ao terminar, atualize a linha de status deste plano em
> `docs/reports/advisor/README.md`.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 8f9fe76..HEAD -- services/flow-runtime/tests/test_supervisor_mpc.py`
> Se o arquivo mudou desde que este plano foi escrito, compare o excerto de "Estado
> atual" com o código vivo antes de prosseguir; divergência é condição de PARADA.

## Status

- **Prioridade**: P1
- **Esforço**: S
- **Risco**: LOW
- **Depende de**: nenhum
- **Categoria**: tests
- **Planejado em**: commit `8f9fe76`, 2026-08-16

## Por que isso importa

`test_mpc_state_ts_de_execucao_bate_bit_a_bit_com_flow_status` guarda uma invariante de
verdade — o `ts` de um quadro `mpc.state` tem de ser o MESMO relógio da fronteira de
varredura publicada em `flow.status` (spec F5 §2.1) — e ela já foi quebrada de verdade
uma vez: o docstring do teste registra que antes do "fix round 1" o bloco usava um clock
próprio e os dois `ts` só coincidiam por sorte de timing.

O problema é que a barreira do teste espera **uma** mensagem de `flow.status` e depois
compara com o **último** `mpc.state` recebido. Os dois canais do barramento são
publicações independentes e fire-and-forget (ADR-002): não há ordem garantida entre eles.
Sob carga, o quadro `mpc.state` da varredura N+1 chega enquanto o conjunto de
`flow.status` coletado ainda termina na varredura N, e o teste falha sem que nada tenha
regredido no produto.

Falha observada nesta worktree, em `8f9fe76`, rodando o arquivo inteiro
(`uv run pytest services/flow-runtime/tests/test_supervisor_mpc.py`):

```
FAILED services/flow-runtime/tests/test_supervisor_mpc.py::test_mpc_state_ts_de_execucao_bate_bit_a_bit_com_flow_status
AssertionError: MpcState.ts de uma execucao de fronteira precisa bater bit a bit com o ts de
ALGUMA varredura publicada em flow.status — mesmo relogio (spec F5 SS2.1)
assert datetime.datetime(2026, 8, 16, 13, 15, 50, 586971, tzinfo=TzInfo(0)) in {
  datetime.datetime(2026, 8, 16, 13, 15, 48, 85621, ...),
  datetime.datetime(2026, 8, 16, 13, 15, 48, 58683...),
  datetime.datetime(2026, 8, 16, 13, 15, 49, 586331, ...),
  datetime.datetime(2026, 8, 16, 13, 15, 50, 86274, ...)}
1 failed, 27 passed in 127.04s
```

Leia os números: as varreduras coletadas estão em fase `...086` e `...586`, a cada 0,5 s.
O `ts` do MPC, `50.586971`, está exatamente na fase `.586` — ele **é** um `ts` de
varredura legítimo, da varredura seguinte à última que o teste tinha coletado
(`50.086274`). Não é relógio divergente; é o `flow.status` daquela varredura que ainda
não havia chegado quando a asserção rodou.

Rodado isolado, o mesmo teste passa 3 de 3 vezes (~11 s cada). É flaky sensível a carga —
exatamente a classe que o repo já decidiu não tolerar quando corrigiu o TD-008 ("gate por
CAUSA, não por efeito"). E ele mora na suíte do supervisor do MPC, a área do aceite
RNF-09: um falso vermelho aqui é o pior lugar possível para erodir a confiança no gate,
porque é onde uma regressão real de `ts` apareceria.

Depois deste plano: o teste prova a mesma invariante e só falha quando ela é violada de
verdade.

## Estado atual

Arquivo: `services/flow-runtime/tests/test_supervisor_mpc.py` (1393 linhas, 28 testes,
127 s de execução).

### O teste, em `test_supervisor_mpc.py:271-294`

```python
async def test_mpc_state_ts_de_execucao_bate_bit_a_bit_com_flow_status(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """spec F5 SS2.1: `ts` do quadro do MPC nas execucoes e a fronteira de varredura —
    "mesmo relogio do ts de flow.status". Fix round 1 threou o `fired_ts` do scheduler
    (`FlowTask._scan`) ate `MpcBlock.step(inputs, ts=...)`; antes desse fix o bloco usava
    um clock proprio desacoplado, entao os dois `ts` so coincidiam por sorte de timing."""
    scenario = await _scenario(session_factory)
    flow_status = await collect(channel_flow_status(scenario["flow_id"]))
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    mpc_states = await _deploy_and_warm(harness, collect, scenario)

    await await_until(lambda: len(flow_status.received) >= 1, timeout_s=AWAIT_TIMEOUT_S)

    execucao = _last_mpc_state(mpc_states)
    tss_de_varredura = {
        FlowStatus.model_validate_json(raw).ts
        for raw in flow_status.received
        if FlowStatus.model_validate_json(raw).ports  # so varreduras reais, nao transicao
    }
    assert execucao.ts in tss_de_varredura, (
        "MpcState.ts de uma execucao de fronteira precisa bater bit a bit com o ts de "
        "ALGUMA varredura publicada em flow.status — mesmo relogio (spec F5 SS2.1)"
    )
```

A linha 283 é o defeito: `len(flow_status.received) >= 1` é uma barreira sobre a
QUANTIDADE de mensagens, não sobre a CONDIÇÃO que a asserção seguinte precisa. O teste
segue para o `assert` assim que a primeira mensagem chega, sem nenhuma garantia de que
ela corresponda ao `mpc.state` que o `_last_mpc_state` vai escolher.

### As peças que você vai usar (todas já importadas neste arquivo)

- `await_until(predicado, timeout_s=...)` — de `tests/testkit/await_until.py`. Já é usado
  neste mesmo arquivo com predicado de condição, por exemplo em
  `test_supervisor_mpc.py:312`: `await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)`.
- `AWAIT_TIMEOUT_S` — a constante de timeout do módulo.
- `_last_mpc_state(mpc_states)` — helper local do arquivo.
- `FlowStatus.model_validate_json(raw)` — parse do payload coletado.
- `collect(...)`/`channel_flow_status(...)`/`_scenario(...)`/`_deploy_and_warm(...)` —
  fixtures e helpers locais.

### Convenções do repositório que se aplicam aqui

- Comentários em **pt-BR**, identificadores em inglês. **Sem emoji**.
- `ruff`, `line-length = 100`.
- O repo já tem um precedente exato deste conserto, registrado no TD-008: o gate passou a
  ser "por CAUSA, não por efeito", com `pytest.skip` explícito quando a causa não
  ocorreu. Aqui não é preciso `skip`: a condição sempre ocorre, é só uma questão de
  esperar por ela.
- Preferir `await_until(condição)` a `asyncio.sleep(janela)` é o padrão vigente do
  arquivo (o `sleep` fixo só sobrevive nos casos que provam "nada aconteceu", onde a
  janela é o próprio contrato).

### Invariante que este plano NÃO pode enfraquecer

A asserção tem de continuar sendo **igualdade bit a bit** entre o `ts` do `mpc.state` e o
`ts` de uma varredura real publicada. Não troque por tolerância de tempo, não arredonde,
não compare "por perto". Isso destruiria o valor do teste: o defeito histórico que ele
guarda (clock próprio do bloco) produzia `ts` PARECIDOS, e é exatamente por isso que a
prova é de identidade.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Ambiente | `uv sync --all-packages` | exit 0 |
| Lint | `uv run ruff check .` | `All checks passed!` |
| Formato | `uv run ruff format --check .` | nenhum arquivo a reformatar |
| O teste isolado | `uv run pytest services/flow-runtime/tests/test_supervisor_mpc.py::test_mpc_state_ts_de_execucao_bate_bit_a_bit_com_flow_status -q` | `1 passed` (~11 s) |
| O arquivo inteiro (onde a falha aparece) | `uv run pytest services/flow-runtime/tests/test_supervisor_mpc.py -q` | `28 passed` (~127 s) |

Rode de dentro de `.worktrees/improve`. **NÃO rode `uv run pytest` sem filtro** (~19 min).

## Escopo

**Em escopo** (o único arquivo que você deve modificar):
- `services/flow-runtime/tests/test_supervisor_mpc.py` — e dentro dele, **apenas** o corpo
  de `test_mpc_state_ts_de_execucao_bate_bit_a_bit_com_flow_status` (linhas 271-294).

**Fora de escopo** (NÃO toque):
- `services/flow-runtime/src/**` — **nada de produção muda neste plano**. A falha é do
  teste, não do produto; isso está provado pelos números da falha (o `ts` do MPC está na
  fase correta da grade de varredura).
- Os outros 27 testes do arquivo.
- `services/flow-runtime/tests/conftest.py` — o custo de 127 s do arquivo (spawn de
  worker real por teste, fixtures de banco por teste) é outro achado, listado no índice
  de `docs/reports/advisor/README.md`. Não otimize de carona: misturar as duas coisas torna
  impossível saber qual mudança consertou o flaky.
- `services/flow-runtime/tests/test_isolamento_temporal.py:101` — o `xfail(strict=True)`
  de lá é deliberado e registrado (TD-016/ARCH-11). Não é flaky e não é este plano.

## Fluxo de git

- Branch: você já está em `improve`; commite nela (não faça push, não abra PR).
- **Conventional Commits com mensagem em pt-BR** (`CLAUDE.md:70`). Exemplo real do
  histórico deste repo: `test(flow-runtime): isolamento entre partições sai do marcador slow`.
  Para este plano:
  `test(flow-runtime): gate do ts MPC espera o par flow.status chegar, não uma mensagem qualquer`

## Passos

### Passo 1: reproduzir a falha (opcional, mas recomendado)

Rode o arquivo inteiro e veja se a falha aparece nesta máquina:

`uv run pytest services/flow-runtime/tests/test_supervisor_mpc.py -q`

Ela é sensível a carga, então pode passar. **Se passar, não conclua que não há defeito**:
a leitura do código na seção "Estado atual" é a prova, e ela não depende de reproduzir. Se
quiser forçar, rode com carga concorrente na máquina, ou rode o arquivo duas vezes em
paralelo. Não gaste mais de duas tentativas nisso.

**Verifique**: nada a verificar; é diagnóstico.

### Passo 2: extrair a condição para uma função e usá-la como barreira

Reescreva o corpo entre as linhas 283 e 294 de forma que o predicado do `await_until` seja
a MESMA condição que a asserção verifica. A forma alvo:

1. Extraia o cálculo do conjunto de `ts` de varredura para um helper local (fechado sobre
   `flow_status`), para não duplicar a expressão entre barreira e asserção. Aproveite para
   parsear cada payload **uma vez** — hoje `FlowStatus.model_validate_json(raw)` é chamado
   duas vezes por mensagem, na comprehension e no filtro.
2. Troque a barreira por uma que espere o par: o `ts` do último `mpc.state` presente no
   conjunto de varreduras já coletadas.
3. Mantenha a asserção final **idêntica em semântica** (pertinência exata, mesma mensagem
   pt-BR). Ela deixa de ser a única defesa e passa a ser a confirmação do que a barreira
   já esperou — o que é correto: se o `await_until` estourar o timeout, o teste falha ali,
   e a asserção seguinte dá a mensagem explicativa.

Forma sugerida (adapte aos nomes reais do arquivo):

```python
    def tss_de_varredura() -> set[datetime]:
        quadros = [FlowStatus.model_validate_json(raw) for raw in flow_status.received]
        # so varreduras reais, nao transicao
        return {quadro.ts for quadro in quadros if quadro.ports}

    # A barreira e a MESMA condicao da assercao: `mpc.state` e `flow.status` sao canais
    # independentes e fire-and-forget (ADR-002), sem ordem garantida entre si — esperar
    # "uma mensagem qualquer" deixava o quadro do MPC da varredura seguinte ser comparado
    # com um conjunto que ainda terminava na anterior.
    await await_until(
        lambda: _last_mpc_state(mpc_states).ts in tss_de_varredura(),
        timeout_s=AWAIT_TIMEOUT_S,
    )

    execucao = _last_mpc_state(mpc_states)
    assert execucao.ts in tss_de_varredura(), (
        "MpcState.ts de uma execucao de fronteira precisa bater bit a bit com o ts de "
        "ALGUMA varredura publicada em flow.status — mesmo relogio (spec F5 SS2.1)"
    )
```

Cuidado com um detalhe: `_last_mpc_state(mpc_states)` pode levantar se ainda não houver
nenhum quadro. `_deploy_and_warm` já garante o aquecimento antes desta linha, mas
confirme lendo o helper; se ele não garantir, o predicado precisa tolerar a lista vazia
devolvendo `False`.

Acrescente ao docstring do teste uma linha registrando por que a barreira é essa (a
independência dos dois canais), no estilo do resto do arquivo — o docstring atual já
registra o histórico do "fix round 1"; este é o round seguinte.

**Verifique**:
`uv run pytest services/flow-runtime/tests/test_supervisor_mpc.py::test_mpc_state_ts_de_execucao_bate_bit_a_bit_com_flow_status -q`
→ `1 passed`.

### Passo 3: provar que a barreira ainda protege a invariante

Prove que o teste **não** ficou vazio, isto é, que ele ainda falha se a invariante for
violada. Sem alterar produção: mude temporariamente o predicado/asserção para comparar
com um `ts` deslocado (por exemplo `execucao.ts + timedelta(microseconds=1)`), confirme
que o teste FALHA (por timeout do `await_until` e/ou pela asserção), e então reverta.

Isso é o RED deste plano. Não deixe a alteração temporária no commit.

**Verifique**: com o deslocamento, o teste falha; revertido, passa.

### Passo 4: o arquivo inteiro, verde

`uv run pytest services/flow-runtime/tests/test_supervisor_mpc.py -q`

**Verifique**: `28 passed`.

## Plano de teste

Este plano **é** um conserto de teste, então não há teste novo a escrever. O que
substitui o "teste do teste" é o Passo 3: a prova deliberada de que a asserção ainda
detecta a violação da invariante, feita por deslocamento temporário e revertida.

Modelo estrutural a seguir para o predicado: `test_supervisor_mpc.py:312`, que já usa
`await_until` com predicado de condição no mesmo arquivo.

## Critérios de conclusão

Verificáveis por máquina. TODOS têm de valer:

- [ ] `uv run ruff check .` sai 0 com `All checks passed!`
- [ ] `uv run ruff format --check .` não lista arquivo a reformatar
- [ ] `uv run pytest services/flow-runtime/tests/test_supervisor_mpc.py -q` → `28 passed`
- [ ] `grep -n "len(flow_status.received) >= 1" services/flow-runtime/tests/test_supervisor_mpc.py`
      não retorna nada
- [ ] A asserção final continua sendo pertinência exata (`in`), sem tolerância de tempo:
      `grep -n "execucao.ts in" services/flow-runtime/tests/test_supervisor_mpc.py` retorna a linha
- [ ] `git status --porcelain` lista apenas
      `services/flow-runtime/tests/test_supervisor_mpc.py`
- [ ] `git diff --stat` mostra que **nenhum** arquivo sob `services/flow-runtime/src/`
      foi tocado
- [ ] O Passo 3 foi executado e o deslocamento temporário foi revertido
- [ ] Linha de status deste plano atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- O excerto de "Estado atual" não corresponder ao código vivo.
- O teste falhar com um `ts` do MPC que **não** esteja na fase da grade de varredura do
  flow (nos números da falha registrada, as fases são `...086` e `...586`, a cada 0,5 s).
  Isso seria relógio divergente de verdade — um bug de PRODUTO, não do teste — e este
  plano estaria endereçando a coisa errada. Relate os `ts` observados.
- O `await_until` estourar o timeout de forma consistente depois da mudança: significa
  que o `flow.status` da varredura correspondente nunca chega, o que também aponta para
  produto, não para teste.
- A correção parecer exigir tocar qualquer arquivo sob `services/flow-runtime/src/`.

## Notas de manutenção

- **O que um revisor deve escrutinar**: que a asserção continua sendo igualdade bit a bit
  (a tentação natural aqui é "tolerar 1 ms", e isso mataria o teste); e que nenhum arquivo
  de produção entrou no diff.
- **Irmãos a auditar depois**: este arquivo concentra 6 das 16 ocorrências de
  `asyncio.sleep(QUIET_WINDOW_S)` do repo (a constante mora em
  `services/flow-runtime/tests/runtime_test_helpers.py`). As que esperam uma condição
  POSITIVA podem virar `await_until` pelo mesmo argumento deste plano; as que provam
  "nada aconteceu" precisam legitimamente da janela fixa e devem ficar. Não faça isso
  aqui — é o mesmo eixo, mas outro commit, e misturar impede atribuir o conserto do flaky.
- **Interação futura**: se o barramento ganhar qualquer forma de ordenação entre canais
  (não previsto — o ADR-002 fixa fire-and-forget), esta barreira fica redundante mas
  continua correta.
