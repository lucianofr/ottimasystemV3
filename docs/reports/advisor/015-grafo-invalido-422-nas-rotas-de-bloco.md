# Plan 015: `graph_json` inválido devolve 422 de domínio, não 500 — nas rotas de bloco único

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado antes de passar ao próximo. Se qualquer condição da seção "Condições de
> PARADA" ocorrer, pare e relate — não improvise. Ao terminar, atualize a sua linha na tabela de
> status de `docs/reports/advisor/README.md` — a menos que um revisor o tenha despachado e dito que
> ele mantém o índice.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 37b0caa..HEAD -- services/api/src/ottima_api/routers/operate.py services/api/src/ottima_api/routers/history.py services/api/src/ottima_api/routers/historized_vars.py services/api/tests`
> Se qualquer arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; em caso de divergência, trate como
> condição de PARADA.

## Status

- **Prioridade**: P1
- **Esforço**: S
- **Risco**: LOW — tratamento de exceção aditivo; nenhum caminho feliz muda
- **Depende de**: nenhum. **Atenção**: o plano 010 (`LOOP_TYPES` fonte única) também toca
  `operate.py`. Se ambos forem executados, faça em commits separados e, de preferência, **010
  antes** — ele remove `_LOOP_TYPES_API` (`operate.py:62`), que este plano não toca.
- **Categoria**: bug
- **Planejado em**: commit `37b0caa`, 2026-09-19

## Por que isso importa

Um flow cujo `graph_json` persistido ficou estruturalmente inválido — formato antigo depois de uma
mudança de contrato, escrita parcial de um hot-swap abortado, intervenção manual no banco, uma
migração futura que não retro-preencheu — faz **sete rotas** devolverem `500 Internal Server Error`
em vez do `422` de domínio que o resto da API garante.

E não são sete rotas quaisquer: são exatamente as que o faceplate de `/operacao` usa ao vivo —
comando de modo, de SP, de MV e de OUT, detalhe de malha, superfície de malha, detalhe fuzzy — mais
as quatro de histórico (`/mpc`, `/fuzzy`, `/loop`, `/ssto/last`). Um operador enfrentando um
distúrbio de planta, com o grafo de um flow corrompido, recebe um 500 genérico do FastAPI cujo corpo
o `frontend/src/lib/api.ts` nem trata do mesmo jeito que o contrato pt-BR de 422.

**A prova de que isto é lacuna e não escolha** está no mesmo arquivo: as rotas de **LISTA** da mesma
família **já protegem a chamada idêntica**. `_mpc_nodes` (`operate.py:617`), `_fuzzy_nodes` (`:686`)
e `_loop_nodes` (`:761`) capturam `(GraphParseError, ValueError)`, logam e seguem. E
`historized_vars.py:53-62` (`_grafo_salvo`) faz exatamente o que este plano pede: captura e
converte em `422`. Existe até teste do comportamento de lista —
`services/api/tests/test_operate.py::test_mpcs_graph_invalido_pulado_com_log` — cobrindo **só** o
lado lista.

O `docstring` de `_mpc_nodes` (`operate.py:531-536`) explica a distinção de intenção: a listagem é
"melhor-esforço", então pula com log; um recurso **identificado por id** merece 404/422. As rotas de
bloco único são identificadas por id — e hoje não cumprem a própria regra.

## Estado atual

**O helper de 422 que já existe** — `services/api/src/ottima_api/routers/operate.py:282-284`:
```python
def _reprovado(mensagem: str) -> HTTPException:
    """422 de domínio com `detail` string única, como no resto da API (padrão `flows.py`)."""
    return HTTPException(status_code=422, detail=mensagem)
```

**Call site 1 — `_mpc_config`** — `operate.py:287-299`:
```python
async def _mpc_config(db: AsyncSession, flow_id: int, block_id: str) -> MpcConfig:
    """Bloco `mpc` tipado, ou 404 (flow inexistente) / 422 (bloco, spec §6.1)."""
    flow = await db.get(Flow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=MSG_FLOW_NAO_ENCONTRADO)
    graph = parse_graph(flow.graph_json)          # <-- sem guarda
    try:
        node = graph.node(block_id)
    except KeyError:
        raise _reprovado(f"Bloco '{block_id}' não encontrado no flow") from None
```

**Call site 2 — `_node_do_flow`** — `operate.py:302-311`:
```python
async def _node_do_flow(db: AsyncSession, flow_id: int, block_id: str) -> FlowNode:
    """No do graph_json persistido, ou 404 (flow) / 422 (bloco)."""
    flow = await db.get(Flow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=MSG_FLOW_NAO_ENCONTRADO)
    graph = parse_graph(flow.graph_json)          # <-- sem guarda
    try:
        return graph.node(block_id)
    except KeyError:
        raise _reprovado(f"Bloco '{block_id}' não encontrado no flow") from None
```

**Call site 3 — `_fuzzy_flow_and_node`** — `operate.py:646-656`, mesma forma
(`graph = parse_graph(flow.graph_json)` em `:649`, sem guarda).

> **Estes três helpers cobrem as rotas de operação.** `_mpc_config` alimenta `set_mv`;
> `_node_do_flow` alimenta `set_mode`, `set_sp`, `set_out`, `get_loop_detail`, `get_loop_surface`
> (e `_loop_config` em `:314-319` passa por ele); `_fuzzy_flow_and_node` alimenta `get_fuzzy_detail`.
> **Consertar os três helpers conserta todas as rotas de operação de uma vez** — não edite as rotas.

**Call sites 4-7 — `history.py`**: `get_history_mpc` (`:350`), `get_history_fuzzy` (`:452`),
`get_history_loop` (`:544`), `get_history_ssto_last` (`:623`) chamam `parse_graph(flow.graph_json)`
sem guarda. **Confirme cada um lendo o arquivo** — a numeração pode ter se movido; o que importa é
que são as quatro rotas `@router.get` de histórico que fazem parse do grafo.

**O padrão a seguir, já no repo** — `services/api/src/ottima_api/routers/historized_vars.py:53-62`:
```python
async def _grafo_salvo(flow: Flow) -> FlowGraph:
    """Parse do `graph_json` JÁ GRAVADO do flow — mesmo padrão de `flows.py::_validar_grafo`
    (CPU-bound fora do event loop). Grafo vazio (flow recém-criado, ADR-017) é tratado como
    "flow precisa ser salvo antes": não há bloco nenhum para historiar."""
    try:
        grafo = await asyncio.to_thread(parse_graph, flow.graph_json)
    except GraphParseError:
        raise HTTPException(status_code=422, detail=MSG_GRAFO_NAO_SALVO) from None
```

**A mensagem: você vai CRIAR uma, no lugar certo.** Verificado em `37b0caa`:
`MSG_GRAFO_NAO_SALVO` **não** mora em `messages.py` — é constante privada de
`services/api/src/ottima_api/routers/historized_vars.py:37-39`, e o texto dela é
específico de historização:

```python
MSG_GRAFO_NAO_SALVO = (
    "Flow ainda não tem um grafo salvo; salve o desenho antes de historiar uma porta"
)
```

**Reutilizá-la seria errado duas vezes**: (a) importar constante privada de um router para
outro acopla os módulos; (b) o texto mandaria o operador "historiar uma porta" quando ele
está comandando um modo — mensagem enganosa numa tela de planta.

O lugar certo é o módulo compartilhado, que existe exatamente para isto —
`services/api/src/ottima_api/messages.py`, íntegro em `37b0caa`:
```python
"""Mensagens pt-BR compartilhadas entre routers (fonte única, decisão A-9)."""

MSG_FLOW_NAO_ENCONTRADO = "Flow não encontrado"
MSG_PROJETO_NAO_ENCONTRADO = "Projeto não encontrado"
MSG_PROJETO_NOME_EM_USO = "Nome de projeto já em uso"
```
`operate.py:28` já faz `from ottima_api.messages import MSG_FLOW_NAO_ENCONTRADO`, e
`history.py` importa do mesmo módulo. **Você acrescenta uma quarta constante lá** (Passo 0) e
a usa nos dois routers.

**O teste precedente** — `services/api/tests/test_operate.py::test_mpcs_graph_invalido_pulado_com_log`.
Leia-o inteiro: ele mostra como o repo constrói um flow com `graph_json` inválido em teste. É o
modelo para os testes do Passo 3.

## Convenções do repositório que se aplicam aqui

- **Python ≥ 3.12, type hints obrigatórios**, Pydantic v2, `ruff` line-length 100.
- **Nenhum 5xx por dado degradável.** O `docstring` de `_mpc_nodes` (`operate.py:531-536`) e o de
  `_grafo_salvo` (`historized_vars.py:54-56`) estabelecem a regra: `graph_json` alheio inválido é
  dado degradável, não exceção de infraestrutura.
- **`raise ... from None`** para não vazar o encadeamento interno no corpo da resposta — os dois
  precedentes fazem assim.
- **CPU-bound fora do event loop** (ADR-004, e o TD-002 que já converteu `parse_graph`/`validate_graph`
  em `asyncio.to_thread` em três call sites). **Atenção**: os três helpers de `operate.py` são
  `async def` mas chamam `parse_graph` **diretamente**, não via `to_thread`. Este plano **não** muda
  isso — ver "Adiado de propósito" nas Notas de manutenção. Não "aproveite" para converter; seria
  mistura de escopo num plano de tratamento de erro.
- **Commits em Conventional Commits, mensagem pt-BR.** Exemplo real:
  `fix(historizadas): constroi OpcValue dentro do try do publish`.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Lint | `uv run ruff check .` | exit 0 |
| Formato | `uv run ruff format --check .` | exit 0 |
| Testes da API | `uv run pytest services/api/tests -q` | tudo passa |
| Guarda em operate | `grep -c 'GraphParseError' services/api/src/ottima_api/routers/operate.py` | ≥ `3` |
| Guarda em history | `grep -c 'GraphParseError' services/api/src/ottima_api/routers/history.py` | ≥ `4` |
| Nada de 500 novo | `git diff --stat HEAD~1 -- services/api` | só os 2 routers + testes |

**NÃO rode** `uv run pytest` sem recorte de pasta (~20 min, testcontainers, dois flaky já
registrados: TD-027 e TD-028). Rode `services/api/tests`.

**NÃO rode** `docker compose`, `deploy/smoke.sh`, `pytest -m e2e`, `npx playwright test` sem
`--list`: o stack de 8 serviços do dono está no ar com planta simulada viva.
**NÃO invoque** nenhuma ferramenta do servidor MCP `ottima` desta sessão.

## Escopo

**Em escopo** (únicos arquivos a modificar):
- `services/api/src/ottima_api/routers/operate.py`
- `services/api/src/ottima_api/routers/history.py`
- `services/api/tests/test_operate.py`
- `services/api/src/ottima_api/messages.py` — a constante nova (Passo 0)
- `services/api/tests/test_history_mpc.py`, `test_history_fuzzy.py`, `test_history_ssto.py` e
  `test_history.py` — os quatro existem; use o que corresponde a cada rota

**Fora de escopo** (NÃO toque, mesmo parecendo relacionado):
- `services/api/src/ottima_api/routers/historized_vars.py` — **já está certo**. É o modelo.
- `services/api/src/ottima_api/routers/flows.py` — `_validar_grafo` já usa `to_thread` e trata erro.
- `packages/ottima-core/src/ottima_core/flowgraph/parse.py` — **não torne `parse_graph` mais
  tolerante**. O parse estrito é o portão de segurança entre um `graph_json` gravado e um runtime que
  escreve na planta (1103 linhas, `validate.py` 1153). Amolecê-lo para evitar 500 seria consertar o
  sintoma no lugar errado.
- As três funções de lista (`_mpc_nodes`, `_fuzzy_nodes`, `_loop_nodes`) — **já tratam** o erro, com
  a semântica correta de melhor-esforço (pular com log). Não as converta em 422; isso mudaria o
  contrato de listagem.
- `_LOOP_TYPES_API` (`operate.py:62`) — é do plano 010.
- A migração `0009_mpc_max_rate.py` — é o TD-019, avaliado e deliberadamente deixado intocado.
- `frontend/`, `docs/`, qualquer worker.

## Fluxo de git

- Branch: `advisor/015-grafo-invalido-422`.
- Um commit. Sugestão: `fix(api): graph_json invalido devolve 422 de dominio nas rotas de bloco unico`
- Sem push, sem PR, a menos que o operador peça.
- Em worktree: caminho **ABSOLUTO** em todo `read`/`write`/`edit`, `cwd` explícito em todo shell,

## Passos

### Passo 0: criar a mensagem no módulo compartilhado

Em `services/api/src/ottima_api/messages.py`, acrescente **uma** constante, seguindo o estilo das
três existentes (pt-BR, frase única, sem ponto final):

```python
MSG_GRAFO_INVALIDO = "O desenho deste flow não pôde ser lido; salve o flow novamente no editor"
```

Regras:
- **Não** altere nem reordene as três constantes existentes.
- **Não** mova `MSG_GRAFO_NAO_SALVO` de `historized_vars.py` para cá. Ele tem texto próprio, de
  historização, e é consumido só lá — mover ampliaria o diff sem ganho e mudaria a mensagem de uma
  rota que hoje está correta.
- O texto acima é uma sugestão; se o `docs/GLOSSARY.md` fixar termo diferente para "desenho"/
  "grafo", **use o do glossário** (`CLAUDE.md`: o glossário governa nomes na UI) e registre a
  escolha no relato.

**Verifique**:
- `grep -c 'MSG_GRAFO_INVALIDO' services/api/src/ottima_api/messages.py` → `1`
- `grep -c '^MSG_' services/api/src/ottima_api/messages.py` → `4`
- `uv run ruff check services/api` → exit 0

### Passo 1: proteger os três helpers de `operate.py`

Nos três helpers — `_mpc_config` (`:287`), `_node_do_flow` (`:302`), `_fuzzy_flow_and_node` (`:646`)
— envolva a chamada `parse_graph(flow.graph_json)` em `try/except GraphParseError` que levante
`_reprovado(MSG_GRAFO_INVALIDO)` com `from None`.

Forma a produzir, no corpo de cada um (o resto do helper não muda):
```python
    try:
        graph = parse_graph(flow.graph_json)
    except GraphParseError:
        raise _reprovado(MSG_GRAFO_INVALIDO) from None
```

Passos concretos:
1. Confirme que `GraphParseError` já está importado em `operate.py`
   (`grep -n 'GraphParseError' services/api/src/ottima_api/routers/operate.py` — deve aparecer nas
   três funções de lista). Se estiver, **não** adicione import duplicado.
2. Acrescente `MSG_GRAFO_INVALIDO` ao import existente de `ottima_api.messages` (a linha
   `operate.py:28` já importa desse módulo — **estenda-a**, não crie linha nova).
3. Aplique o `try/except` nos três.

**Não altere** os `except KeyError` existentes nem as mensagens de "não encontrado"/"não é um bloco
MPC"/"não é um bloco malha". Elas continuam corretas para o caso de grafo **válido** com bloco
ausente.

**Verifique**:
- `grep -c 'GraphParseError' services/api/src/ottima_api/routers/operate.py` → ≥ `6` (3 das listas
  que já existiam + 3 novas)
- `uv run ruff check services/api` → exit 0

### Passo 2: proteger as quatro rotas de `history.py`

Mesma forma nas quatro rotas que fazem parse do grafo: `get_history_mpc`, `get_history_fuzzy`,
`get_history_loop`, `get_history_ssto_last`. **Localize-as pelo nome, não pelo número de linha** —
confirme com `grep -n 'parse_graph' services/api/src/ottima_api/routers/history.py`.

`history.py` **não tem** `_reprovado` (é helper privado de `operate.py`). Use
`HTTPException(status_code=422, detail=MSG_GRAFO_INVALIDO)` diretamente, que é a forma que
`historized_vars.py:60` faz. **Não importe `_reprovado` de `operate.py`** — importar helper privado
entre routers acoplaria os dois módulos.

**Verifique**:
- `grep -c 'GraphParseError' services/api/src/ottima_api/routers/history.py` → ≥ `4`
- `grep -c 'parse_graph' services/api/src/ottima_api/routers/history.py` → o mesmo número de antes
  (você envolveu as chamadas, não as removeu)
- `uv run ruff check services/api` → exit 0

### Passo 3: testes — o RED que prova a mudança

**3a. Operação.** Em `services/api/tests/test_operate.py`, siga
`test_mpcs_graph_invalido_pulado_com_log` para construir um flow com `graph_json` inválido, e
acrescente testes cobrindo **pelo menos**:
- `POST /api/operate/{flow_id}/{block_id}/mode` com grafo inválido → **422**, e o `detail` é
  `MSG_GRAFO_INVALIDO` (não um 500, não uma string vazia).
- `GET /api/operate/loop/{flow_id}/{block_id}` com grafo inválido → **422**.
- `GET /api/operate/fuzzy/{flow_id}/{block_id}` com grafo inválido → **422**.

Confirme o **RED genuíno** antes de aplicar o Passo 1: escreva o teste primeiro, rode, e verifique que
ele falha com **500** (não com 422 errado). Registre a saída real no seu relato. Se você aplicar o
Passo 1 antes de ver o RED, não tem prova de que o teste morde.

**3b. Histórico.** No arquivo de teste de histórico correspondente, um teste por rota cobrindo o
mesmo: grafo inválido → **422**. Se não existir arquivo de teste de histórico, crie
`services/api/tests/test_history_grafo_invalido.py` seguindo a estrutura de fixture de
`services/api/tests/test_history_retention.py` (leia-o inteiro primeiro).

**3c. Não-regressão do caminho feliz.** Confirme que os testes existentes de
`test_mpcs_graph_invalido_pulado_com_log` e os de operação/histórico com grafo **válido** continuam
passando sem modificação. Se algum precisar mudar, **pare** (Condições de PARADA).

**Verifique**: `uv run pytest services/api/tests -q` → tudo passa, com os novos.

### Passo 4: gates finais

**Verifique**, nesta ordem:
- `uv run ruff check .` → exit 0
- `uv run ruff format --check .` → exit 0
- `uv run pytest services/api/tests -q` → tudo passa
- `git status --porcelain` lista só os arquivos em escopo
- `git diff -- packages services/flow-runtime services/opc-worker frontend` → **vazio**

## Plano de teste

- **Novos**: 3 de operação + 4 de histórico (um por rota), todos assertando **422** e o `detail`
  igual a `MSG_GRAFO_INVALIDO`.
- **Padrão estrutural**: `services/api/tests/test_operate.py::test_mpcs_graph_invalido_pulado_com_log`
  para construir o grafo inválido; `services/api/tests/test_history_retention.py` para a fixture de
  banco, se precisar de arquivo novo.
- **O repo não usa `unittest.mock` em lugar nenhum** (verificado nesta auditoria: zero ocorrências).
  Não introduza.
- **Nenhum teste existente deve mudar.**
- **Verificação**: `uv run pytest services/api/tests -q` → tudo passa.

## Critérios de conclusão

Todos devem valer:

- [ ] `grep -c 'GraphParseError' services/api/src/ottima_api/routers/operate.py` → ≥ `6`
- [ ] `grep -c 'GraphParseError' services/api/src/ottima_api/routers/history.py` → ≥ `4`
- [ ] Nenhum `_reprovado` importado de `operate.py` em `history.py`
- [ ] `MSG_GRAFO_INVALIDO` existe em `messages.py` e é a ÚNICA string nova; `MSG_GRAFO_NAO_SALVO` não foi importada de `historized_vars.py`
- [ ] As três funções de lista (`_mpc_nodes`, `_fuzzy_nodes`, `_loop_nodes`) **não foram alteradas**
- [ ] `git diff -- packages/ottima-core/src/ottima_core/flowgraph` → **vazio** (parse não foi amolecido)
- [ ] 7 testes novos passando, com o RED (500 antes, 422 depois) registrado no relato
- [ ] `uv run ruff check .` → exit 0
- [ ] `uv run ruff format --check .` → exit 0
- [ ] `uv run pytest services/api/tests -q` → tudo passa
- [ ] `git status --porcelain` lista só os arquivos em escopo
- [ ] Linha de status atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- Os excertos de "Estado atual" não baterem com o código vivo (drift desde `37b0caa`).
- `services/api/src/ottima_api/messages.py` não existir ou não ter as três constantes do excerto:
  relate o conteúdo real, não crie módulo novo.
- `history.py` tiver **mais ou menos** de quatro chamadas `parse_graph`: relate a contagem e os
  nomes das rotas, não adapte em silêncio.
- Algum teste existente precisar mudar para continuar verde.
- O teste do Passo 3a falhar com algo que **não** seja 500 na fase RED: significa que a rota já
  tratava o erro, ou que a fixture não produz grafo inválido de verdade. Investigue e relate.
- Você concluir que a saída certa é tornar `parse_graph` tolerante a grafo inválido: **não faça**.
  É o portão de segurança entre dado gravado e runtime que escreve na planta.
- Aparecer um **oitavo** call site de `parse_graph` sem guarda que este plano não lista: relate o
  `file:line`, não conserte por conta própria sem registrar.

## Notas de manutenção

- **O que interage com isto**: qualquer rota nova que faça parse de `graph_json` persistido. A regra
  passa a ser: parse de grafo **gravado** em rota de recurso identificado ⇒ `try/except
  GraphParseError` ⇒ 422 com `MSG_GRAFO_INVALIDO`; em rota de **lista** ⇒ pular com log
  (melhor-esforço). As duas posturas já estão documentadas nos docstrings de `_grafo_salvo` e
  `_mpc_nodes`.
- **O que um revisor deve olhar no PR**: (1) o diff é **só** `try/except` — nenhuma mudança de
  assinatura, de ordem de verificação ou de mensagem; (2) as três funções de lista intactas; (3)
  `parse.py`/`validate.py` intocados; (4) o RED registrado (500 antes).
- **Adiado de propósito, e por quê**:
  - **Converter esses `parse_graph` para `asyncio.to_thread`.** É a classe do TD-002 e seria uma
    melhoria real, mas é achado separado (CORR-03 desta auditoria, **rebaixado**: `_fuzzy_nodes` usa
    `to_thread` porque chama `introspect_fll`, que é CPU-bound de verdade; `_mpc_nodes` e
    `_loop_nodes` não usam porque fazem só projeção Pydantic sobre ~10 flows — julgamento
    consistente, não regressão). Misturar conversão de concorrência com tratamento de erro num mesmo
    diff tornaria a revisão pior. Se algum dia for feito, exige **medição** do custo de `_mpc_nodes`
    antes — o advisor anterior rejeitou um item de performance não medido com "Reconsidere só com
    telemetria".
  - **`RecursionError` por profundidade de JSON no import de projeto** (`routers/projects.py:343-346`):
    já avaliado e rejeitado como prioridade pelo advisor anterior — a rota é `require_admin`, o
    efeito é um 500 opaco em vez de 422, e quem consegue chamá-la já pode apagar todos os projetos.
    Vale carona num plano que já toque o arquivo. Não é este.
