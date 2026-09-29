# Plan 010: `LOOP_TYPES` passa a ter UMA fonte — as três cópias viram import

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado antes de passar ao próximo. Se qualquer condição da seção "Condições de
> PARADA" ocorrer, pare e relate — não improvise. Ao terminar, atualize a sua linha na tabela de
> status de `docs/reports/advisor/README.md` — a menos que um revisor o tenha despachado e dito
> que ele mantém o índice.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 37b0caa..HEAD -- packages/ottima-core/src/ottima_core/flowgraph/validate.py services/flow-runtime/src/ottima_flow_runtime/definition.py services/api/src/ottima_api/routers/operate.py services/api/src/ottima_api/routers/history.py`
> Se qualquer arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; em caso de divergência, trate como
> condição de PARADA.

## Status

- **Prioridade**: P1
- **Esforço**: S
- **Risco**: LOW
- **Depende de**: nenhum
- **Categoria**: tech-debt
- **Planejado em**: commit `37b0caa`, 2026-09-19

## Por que isso importa

"Este bloco é um bloco malha?" é uma pergunta que o sistema responde **três vezes**, a partir de
três literais idênticos em três pacotes diferentes. Duas das três cópias não têm teste nenhum.

A [ADR-039](../../adr/ADR-039-block-shell.md) D8 é explicitamente uma fábrica kernel+shell: um
terceiro kernel (além de `pid` e `fuzzy`) é o próximo passo **desenhado**, não uma hipótese. Cada
kernel novo significa editar três frozensets em três pacotes. O custo de errar é assimétrico e
grave nos dois sentidos:

- **Perder a cópia da API** ⇒ o operador recebe `422 "Bloco 'x' não é um bloco malha"` sobre um
  loop **em execução**: o faceplate de modo/SP/OUT de um bloco que escreve na planta fica
  incomandável, com uma mensagem afirmando que o bloco não existe.
- **Perder a cópia do runtime** ⇒ o bloco nunca é instanciado como shell. Essa falha já aconteceu
  e está registrada no próprio repo: `services/flow-runtime/tests/test_fuzzy_loop_definition.py:157`
  documenta `'FuzzyLoopConfig' object has no attribute 'matrix'`, com a nota "achado no smoke
  fim-a-fim".

Já existe inconsistência **dentro do mesmo serviço**: `history.py` importa o canônico de
`ottima_core.flowgraph`, `operate.py` mantém uma cópia privada. Dois routers do MESMO app FastAPI
respondem à mesma pergunta a partir de fontes diferentes.

## Estado atual

Os três literais, verbatim em `37b0caa`:

**Cópia canônica** — `packages/ottima-core/src/ottima_core/flowgraph/validate.py:559`:
```python
LOOP_TYPES: frozenset[str] = frozenset({"pid_loop", "fuzzy_loop"})
```
Já é re-exportada por `packages/ottima-core/src/ottima_core/flowgraph/__init__.py:83` (import) e
`:100` (lista `__all__`). **Não precisa criar exportação nenhuma.**

**Cópia do runtime** — `services/flow-runtime/src/ottima_flow_runtime/definition.py:84`:
```python
LOOP_TYPES: frozenset[str] = frozenset({"pid_loop", "fuzzy_loop"})
```
Usada em `definition.py:156` (classe de hot-swap) e `:370` (dispatch de instanciação).

**Cópia da API** — `services/api/src/ottima_api/routers/operate.py:62`:
```python
_LOOP_TYPES_API: frozenset[str] = frozenset({"pid_loop", "fuzzy_loop"})
```
Usada em `operate.py:317, 381, 419, 750, 793`.

**O precedente que prova que o import funciona** — `services/api/src/ottima_api/routers/history.py:14`:
```python
from ottima_core.flowgraph import LOOP_TYPES, parse_graph
```
(usado em `history.py:551`). O mesmo app FastAPI já faz exatamente o que este plano pede.

**O tipo que o teste novo vai cruzar** — `packages/ottima-core/src/ottima_core/flowgraph/parse.py:34-50`:
```python
NODE_TYPES: tuple[str, ...] = (
    "opc_read", "opc_write", "constant", "script", "fuzzy", "tfs", "mpc",
    "first_order", "kalman", "pid", "pid_loop", "fuzzy_loop", "scaler",
    "integrator", "bus_publish", "bus_subscribe",
    ...
)
```
(Confirme a lista completa ao ler o arquivo — o excerto acima pode estar truncado no final. Os
dois sufixos `_loop` presentes em `37b0caa` são `pid_loop` e `fuzzy_loop`.)

**Único teste que pinha alguma cópia hoje** — `services/flow-runtime/tests/test_fuzzy_loop_definition.py:34-35`
asserta `"fuzzy_loop" in LOOP_TYPES`, mas **só da cópia do runtime**. Nenhuma cópia da API é pinhada.

## Convenções do repositório que se aplicam aqui

- **Python ≥ 3.12, type hints obrigatórios**, `ruff` line-length 100 (`pyproject.toml:41-49`).
- **Identificadores de código em inglês; strings de UI, comentários e docs em pt-BR.** O
  `docs/GLOSSARY.md` é o cânone de tradução.
- **Commits em Conventional Commits, mensagem em pt-BR** (`CLAUDE.md`, seção "Convenções de
  código"). Exemplos reais do `git log`: `fix(historizadas): constroi OpcValue dentro do try do
  publish`, `refactor(qualidade): OpcQuality tipa a polaridade OPC num vocabulário único`.
- **TDD estrito em lógica pura** (`CLAUDE.md`, seção "Testes"). Este plano é exatamente isso: uma
  função/regra pura com teste que falha antes e passa depois.
- **Não criar uma segunda convenção ao lado da existente.** O import de `ottima_core.flowgraph`
  já é o padrão em `history.py` — siga-o, não invente um módulo de constantes novo.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Lint | `uv run ruff check .` | exit 0 |
| Formato | `uv run ruff format --check .` | exit 0, "N files already formatted" |
| Testes do core | `uv run pytest packages/ottima-core -q` | tudo passa |
| Testes do runtime | `uv run pytest services/flow-runtime/tests -q` | tudo passa |
| Testes da API | `uv run pytest services/api/tests -q` | tudo passa |
| Cópia do runtime sumiu | `grep -c 'LOOP_TYPES: frozenset' services/flow-runtime/src/ottima_flow_runtime/definition.py` | `0` |
| Cópia da API sumiu | `grep -rn '_LOOP_TYPES_API' services/api/src` | nenhuma saída |
| Fonte única | `grep -rn 'LOOP_TYPES: frozenset' packages services` | **exatamente 1** linha, em `validate.py` |

**NÃO rode** `uv run pytest` sem recorte de pasta: a suíte do workspace leva ~20 min, sobe
testcontainers e contém dois testes flaky já registrados (`TD-027`, `TD-028`) cujo vermelho não é
regressão sua. Rode por pacote, como na tabela.

**NÃO rode** nenhum `docker compose`, `deploy/smoke.sh`, `pytest -m e2e` nem `npx playwright test`:
o stack de 8 serviços do dono está no ar com planta simulada viva, e `frontend/e2e/fixtures.ts`
ativa projeto próprio — derrubaria os flows dele.

## Escopo

**Em escopo** (únicos arquivos a modificar):
- `services/flow-runtime/src/ottima_flow_runtime/definition.py`
- `services/api/src/ottima_api/routers/operate.py`
- `packages/ottima-core/tests/test_loop_types.py` (**criar**)

**Fora de escopo** (NÃO toque, mesmo parecendo relacionado):
- `packages/ottima-core/src/ottima_core/flowgraph/validate.py` — a definição canônica já está
  correta e já é exportada. Mexer nela é trabalho sem ganho e risco num arquivo de 1153 linhas que
  é o portão entre um `graph_json` gravado e um runtime que escreve na planta.
- `packages/ottima-core/src/ottima_core/flowgraph/__init__.py` — a exportação já existe.
- `services/api/src/ottima_api/routers/history.py` — **já importa o canônico**. Não "padronize"
  o que já está certo.
- `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/*` e `blocks/kernels/*` — a fábrica
  de kernels. Este plano não adiciona kernel nenhum.
- Qualquer resposta de API, modelo Pydantic ou contrato de barramento. A forma do `422` de
  "não é bloco malha" **não muda**.
- `frontend/` inteiro.

## Fluxo de git

- Branch: `advisor/010-loop-types-fonte-unica` (o repo usa `exec/NNN` nas worktrees do advisor
  anterior — qualquer um dos dois serve; seja consistente).
- Um commit, mensagem pt-BR em Conventional Commits. Sugestão:
  `refactor(flowgraph): LOOP_TYPES passa a ter fonte unica em ottima-core`
- **Sem push, sem PR**, a menos que o operador peça.
- Se estiver numa worktree: use caminho **ABSOLUTO** em todo `read`/`write`/`edit`, passe `cwd`
  explícito em todo comando de shell, e confirme por shell depois de cada escrita. A regra está em
  `CLAUDE.md`, seção "Subagente em worktree: caminho ABSOLUTO, sempre" — dois incidentes reais
  (`TD-025`) motivaram-na.

## Passos

### Passo 1: escrever o teste que falha (RED)

Crie `packages/ottima-core/tests/test_loop_types.py`. O teste pinha a **invariante**, não o
literal: todo tipo de nó com sufixo `_loop` está em `LOOP_TYPES`, e nada em `LOOP_TYPES` está fora
de `NODE_TYPES`. É isso que impede um quarto kernel de ser entregue semi-registrado.

```python
"""LOOP_TYPES é a fonte única de "é um bloco malha" (ADR-039 D8).

A invariante é cruzada com NODE_TYPES de propósito: a fábrica kernel+shell da ADR-039 D8
prevê kernels novos, e um kernel novo cujo tipo não entre aqui nasce incomandável pela API
(422 "não é um bloco malha" sobre um bloco em execução).
"""

from ottima_core.flowgraph import LOOP_TYPES, NODE_TYPES


def test_todo_tipo_com_sufixo_loop_esta_em_loop_types() -> None:
    esperados = {t for t in NODE_TYPES if t.endswith("_loop")}
    assert esperados, "nenhum tipo _loop em NODE_TYPES — a premissa do teste mudou"
    assert set(LOOP_TYPES) == esperados


def test_loop_types_so_contem_tipos_de_no_validos() -> None:
    assert set(LOOP_TYPES) <= set(NODE_TYPES)


def test_os_dois_kernels_entregues_estao_registrados() -> None:
    assert {"pid_loop", "fuzzy_loop"} <= set(LOOP_TYPES)
```

**Verifique**: `uv run pytest packages/ottima-core/tests/test_loop_types.py -q` → **3 passed**.
(Estes três passam já em `37b0caa` — o canônico está correto. O RED genuíno vem no Passo 4.)

### Passo 2: apagar a cópia do runtime

Em `services/flow-runtime/src/ottima_flow_runtime/definition.py`:

1. Remova a linha 84 (`LOOP_TYPES: frozenset[str] = frozenset({"pid_loop", "fuzzy_loop"})`).
2. Adicione `LOOP_TYPES` ao import já existente de `ottima_core.flowgraph`. Se não houver import
   desse módulo no arquivo, crie um na ordem isort (`ruff` regra `I`):
   `from ottima_core.flowgraph import LOOP_TYPES`.
3. **Não altere** os usos em `:156` e `:370` — o nome é o mesmo.

**Verifique**:
- `grep -c 'LOOP_TYPES: frozenset' services/flow-runtime/src/ottima_flow_runtime/definition.py` → `0`
- `uv run ruff check services/flow-runtime` → exit 0
- `uv run pytest services/flow-runtime/tests -q` → tudo passa

### Passo 3: apagar a cópia da API

Em `services/api/src/ottima_api/routers/operate.py`:

1. Remova a linha 62 (`_LOOP_TYPES_API: frozenset[str] = frozenset({"pid_loop", "fuzzy_loop"})`).
2. Adicione `LOOP_TYPES` ao import de `ottima_core.flowgraph` já presente no arquivo (confirme com
   `grep -n 'from ottima_core.flowgraph' services/api/src/ottima_api/routers/operate.py`).
3. Substitua os **cinco** usos (`:317, :381, :419, :750, :793`) de `_LOOP_TYPES_API` por
   `LOOP_TYPES`. Confirme que não sobrou nenhum:
   `grep -rn '_LOOP_TYPES_API' services/api/src` → **nenhuma saída**.

**Verifique**:
- `uv run ruff check services/api` → exit 0
- `uv run pytest services/api/tests -q` → tudo passa

### Passo 4: o RED genuíno — provar que a invariante morde

Este passo prova que o teste do Passo 1 não é decoração. Sem ele, você não tem evidência de que um
kernel novo semi-registrado seria pego.

1. Em `packages/ottima-core/src/ottima_core/flowgraph/parse.py`, acrescente temporariamente
   `"teste_loop"` ao tuple `NODE_TYPES` (última posição).
2. Rode `uv run pytest packages/ottima-core/tests/test_loop_types.py -q`.
   → **esperado: 1 failed**, em `test_todo_tipo_com_sufixo_loop_esta_em_loop_types`, com
   `set(LOOP_TYPES) == esperados` mostrando `teste_loop` faltando.
3. **Reverta a edição do passo 4.1.** Confirme a reversão por shell — a resposta de sucesso da
   ferramenta de edição não é prova (`CLAUDE.md`, regra de worktree):
   `grep -c 'teste_loop' packages/ottima-core/src/ottima_core/flowgraph/parse.py` → `0`
4. Rode de novo `uv run pytest packages/ottima-core/tests/test_loop_types.py -q` → **3 passed**.

Não use `git checkout`/`git stash`/`git reset` para reverter: edite de volta. Um `git checkout`
pode descartar trabalho de outra sessão.

### Passo 5: gates finais

**Verifique**, nesta ordem:
- `uv run ruff check .` → exit 0
- `uv run ruff format --check .` → exit 0
- `grep -rn 'LOOP_TYPES: frozenset' packages services` → **exatamente 1** linha (`validate.py`)
- `uv run pytest packages/ottima-core -q` → tudo passa
- `uv run pytest services/flow-runtime/tests -q` → tudo passa
- `uv run pytest services/api/tests -q` → tudo passa
- `git status --porcelain` lista **só** os 3 arquivos em escopo

## Plano de teste

- **Novo**: `packages/ottima-core/tests/test_loop_types.py` (Passo 1) — 3 testes de invariante.
- **Padrão estrutural a seguir**: os testes existentes de `packages/ottima-core/tests/` são
  funções `test_*` simples, sem classe, com docstring em pt-BR explicando a regra. Veja
  `services/flow-runtime/tests/test_fuzzy_loop_definition.py:34-35` para o estilo de asserção
  sobre `LOOP_TYPES`.
- **Nenhum teste existente precisa mudar.** Se algum mudar, é sinal de que você alterou
  comportamento, não só fonte de constante — pare e relate.
- **Verificação**: `uv run pytest packages/ottima-core -q` → todos passam, incluindo os 3 novos.

## Critérios de conclusão

Todos devem valer:

- [ ] `grep -rn 'LOOP_TYPES: frozenset' packages services` devolve exatamente 1 linha, em `validate.py`
- [ ] `grep -rn '_LOOP_TYPES_API' services/api/src` não devolve nada
- [ ] `grep -c 'LOOP_TYPES: frozenset' services/flow-runtime/src/ottima_flow_runtime/definition.py` → `0`
- [ ] `packages/ottima-core/tests/test_loop_types.py` existe com 3 testes passando
- [ ] O RED do Passo 4 foi reproduzido e revertido (`grep -c 'teste_loop' .../parse.py` → `0`)
- [ ] `uv run ruff check .` → exit 0
- [ ] `uv run ruff format --check .` → exit 0
- [ ] `uv run pytest packages/ottima-core -q` → tudo passa
- [ ] `uv run pytest services/flow-runtime/tests -q` → tudo passa
- [ ] `uv run pytest services/api/tests -q` → tudo passa
- [ ] `git status --porcelain` lista só os 3 arquivos em escopo
- [ ] Linha de status atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- Os literais em "Estado atual" não baterem com o código vivo (drift desde `37b0caa`).
- `ottima_core.flowgraph` **não** exportar `LOOP_TYPES` no `__init__.py` — significaria que a
  premissa do plano caiu; não crie a exportação por conta própria sem relatar.
- Algum dos cinco usos de `_LOOP_TYPES_API` em `operate.py` não for uma simples substituição de
  nome (por exemplo, se um deles depender de um tipo que só a cópia privada tem).
- Um teste existente precisar mudar para continuar verde.
- Você concluir que `history.py` também precisa de ajuste: **não precisa**, já importa o canônico.
  Relate se achar o contrário, em vez de editar.
- Aparecer um quarto literal `{"pid_loop", "fuzzy_loop"}` em outro lugar do repo que este plano
  não cobre: relate o `file:line`, não conserte por conta própria (ampliaria o escopo).

## Notas de manutenção

- **O que interage com isto**: qualquer kernel novo da fábrica ADR-039 D8. O procedimento passa a
  ser: adicionar o tipo em `NODE_TYPES` (`parse.py`) e em `LOOP_TYPES` (`validate.py`) — e o teste
  do Passo 1 falha até os dois estarem coerentes. É essa a rede que faltava.
- **O que um revisor deve olhar no PR**: que `definition.py` e `operate.py` ganharam um *import* e
  perderam um *literal*, e nada mais. Se o diff mostrar qualquer mudança de lógica, de dispatch ou
  de mensagem de erro, está fora do escopo.
- **Adiado de propósito, e por quê**: `ARCH-05` (`EventMessage` em `bus.py:305` e `EventOut` em
  `schemas/events.py:9` redeclarando os mesmos cinco campos) é a mesma classe de duplicação, mas
  cruza a fronteira modelo↔schema, onde a duplicação é às vezes deliberada para independência de
  contrato. Não entra aqui.
- **Adiado de propósito**: `DEBT-02` do índice (a vertical MPC→Fuzzy→Loop clonada em três camadas)
  é a versão maior deste problema. Este plano é o corte barato e seguro que remove **um** dos três
  pontos de edição mecânica; o outro exige preservar três contratos REST vivos e não cabe aqui.
