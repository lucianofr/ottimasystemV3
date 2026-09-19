# Plan 018: Três lacunas da camada rápida — default de segurança do faceplate, colisão de chave no import, router `system_settings`

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado antes de passar ao próximo. Se qualquer condição da seção "Condições de
> PARADA" ocorrer, pare e relate — não improvise. **Este plano só ACRESCENTA testes**: se você se
> pegar editando código de produção, pare. Ao terminar, atualize a sua linha na tabela de status de
> `docs/reports/advisor/README.md` — a menos que um revisor o tenha despachado e dito que ele
> mantém o índice.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 37b0caa..HEAD -- frontend/src/features/operate/gradeVariaveis.ts services/api/src/ottima_api/routers/projects.py services/api/src/ottima_api/routers/system_settings.py services/api/tests`
> Se qualquer arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; em caso de divergência, trate como
> condição de PARADA.

## Status

- **Prioridade**: P2 (o item A é P1 pelo que protege, mas é uma asserção)
- **Esforço**: S
- **Risco**: LOW — só testes; nenhum comportamento muda
- **Depende de**: nenhum
- **Categoria**: tests
- **Planejado em**: commit `37b0caa`, 2026-09-19

## Por que isso importa

A disciplina de teste deste repo é alta: zero `unittest.mock` no repositório inteiro, nenhuma
asserção trivial encontrada, e uma varredura mecânica de "módulo de produção importado por nenhum
teste" produziu **10 candidatos, todos falsos positivos**. As lacunas reais são poucas e estreitas —
estas três.

**A. O default de segurança do faceplate é exercitado mas nunca asserido.** É o mais grave dos três:
a linha que mantém a escrita em planta travada antes da primeira confirmação de modo não tem teste
que falhe se alguém a mudar.

**B. A regra de chave única do barramento tem duas implementações; só uma é testada.** A do `PUT`
tem 4 testes; a do **import de projeto** — escrita separadamente, na fronteira de confiança de um
bundle vindo de fora — tem zero.

**C. `system_settings.py` é o único dos 17 routers sem teste na camada rápida.** É `require_admin`,
muta o log level do processo inteiro e publica evento de auditoria; só é coberto por cenários
marcados `e2e`, que o `uv run pytest` padrão **exclui** e que exigem a stack de 8 serviços. Este é o
**carry-over #3** da auditoria de 2026-08-16, verificado **AINDA VALE** em `37b0caa`.

## Estado atual

### A. `gradeDeVariaveis` — o default que trava a escrita

`frontend/src/features/operate/gradeVariaveis.ts:10-21`:
```ts
/** Monta a lista de props de `FaceplateVariavel` na ordem fixada pelo spec (MV → CV →
 *  Restrição → DV) a partir de `GET /api/operate/mpcs` (definição) e `mpc.state.vars`
 *  (valor ao vivo). `modos` cai no default de partida do deploy (LOCAL/MAN) enquanto o
 *  primeiro `mpc.state` não chega — mantém todo campo de escrita desabilitado até então,
 *  nunca finge um modo que ainda não foi confirmado. */
export function gradeDeVariaveis(
  mpc: MpcNodeOut,
  mpcState: MpcState | undefined,
  flowId: number,
  blockId: string,
): (FaceplateVariavelProps & { key: string })[] {
  const modos = mpcState?.modes ?? { local_remote: "local" as const, man_auto: "man" as const };
```

Esse `??` é o que trava a escrita: `FaceplateVariavel.tsx:246-251` libera o campo de MV só com
`local_remote === "remote" && man_auto === "man"`, e o de CV só com `man_auto === "auto"`.

**A lacuna**: em `frontend/src/features/operate/faceplateVariavel.check.ts`, a única ocorrência de
`local_remote`/`man_auto` é uma **fixture montada à mão** (`:31`):
```ts
    modos: { local_remote: "local", man_auto: "man" },
```
Há chamadas com `mpcState` indefinido (`:91-102`), mas **nenhuma asserta o objeto `modos`
resultante**. Trocar o default para `remote`/`auto` — num refactor, ou por troca acidental dos dois
eixos — liberaria escrita manual de MV/SP para a planta antes de qualquer modo confirmado, e
**nenhum teste do repositório ficaria vermelho**.

### B. Colisão de chave `bus_publish` no import de projeto

A regra ADR-042 D5 ("`key` publicada é única por projeto") tem duas implementações independentes.

A do save, **testada** — `services/api/src/ottima_api/routers/flows.py:131-161`, coberta por
`services/api/tests/test_flows.py:494`
(`test_put_key_publicada_por_outro_flow_do_projeto_422`) e três testes irmãos.

A do import, **não testada** — `services/api/src/ottima_api/routers/projects.py:535-562`:
```python
    # ADR-042 D5: `key` publicada é única no projeto. O bundle vem de fora (fronteira de
    # confiança), então a checagem entre flows roda aqui também, não só no save do editor.
    publicadores: dict[str, str] = {}
    ...
        colisoes = [
            (key, publicadores[key]) for key in bus_publish_keys(grafo) if key in publicadores
        ]
        problemas_grafo.extend(
            f"fluxo '{bf.name}': a chave de barramento '{key}' já é publicada pelo fluxo '{dono}'"
            for key, dono in colisoes
        )
        if colisoes:
            continue
        publicadores.update(dict.fromkeys(bus_publish_keys(grafo), bf.name))
```
`services/api/tests/test_projects_import.py` tem 711 linhas e **zero** ocorrências de
`bus_publish`, `bus_subscribe` ou `barramento`.

### C. `system_settings.py` sem teste rápido

`services/api/src/ottima_api/routers/system_settings.py` (~63 linhas, um `GET` e um `PUT`
`require_admin`, com `publish_event` de auditoria) não tem `services/api/tests/test_system_settings.py`.
É coberto só por `tests/e2e/test_settings_log_level.py` e `tests/e2e/test_settings_events_retention.py`,
ambos `pytestmark = pytest.mark.e2e` — excluídos do run padrão por
`pyproject.toml:39` (`addopts = "-m 'not e2e and not slow' ..."`).

## Convenções do repositório que se aplicam aqui

- **`*.check.ts`** são checagens **puras em Node**, rodadas por `cd frontend && npm run test:unit`
  (config `playwright.unit.config.ts`, sem projeto de navegador). Não renderizam React. O item A é
  função pura — cabe perfeitamente ali.
- **O repo não usa `unittest.mock` em lugar nenhum** (zero ocorrências, verificado nesta auditoria).
  **Não introduza.**
- **Testes Python**: `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`), sem classe, função
  `test_*` com docstring em pt-BR explicando **a regra**, não o mecanismo.
- **Um teste só se defende contrato observável.** Não escreva teste de fiação. Os três aqui
  defendem: escrita em planta travada, recusa de bundle incoerente, e RBAC de rota admin.
- **Commits em Conventional Commits, mensagem pt-BR** (`test:` é o prefixo destes).

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Checks do frontend | `cd frontend && npm run test:unit` | tudo passa |
| Typecheck | `cd frontend && npm run typecheck` | exit 0 |
| Testes da API | `uv run pytest services/api/tests -q` | tudo passa |
| Lint Python | `uv run ruff check .` | exit 0 |
| Formato Python | `uv run ruff format --check .` | exit 0 |
| C tem teste rápido | `ls services/api/tests/test_system_settings.py` | existe |

**NÃO rode** `uv run pytest` sem recorte de pasta (~20 min, testcontainers, TD-027/TD-028 flaky).
**NÃO rode** `docker compose`, `deploy/smoke.sh`, `pytest -m e2e`, `npm run e2e` nem
`npx playwright test` sem `--list` — o stack de 8 serviços do dono está no ar com planta simulada
viva, e `frontend/e2e/fixtures.ts::criarAmbiente` ativa projeto próprio.
**NÃO invoque** nenhuma ferramenta do servidor MCP `ottima` desta sessão.

## Escopo

**Em escopo** (únicos arquivos a modificar/criar):
- `frontend/src/features/operate/faceplateVariavel.check.ts` (item A — **acrescentar** casos)
- `services/api/tests/test_projects_import.py` (item B — **acrescentar** casos)
- `services/api/tests/test_system_settings.py` (item C — **criar**)

**Fora de escopo** (NÃO toque):
- **Qualquer arquivo de produção.** Este plano não muda comportamento. Em particular:
  `gradeVariaveis.ts`, `FaceplateVariavel.tsx`, `projects.py`, `flows.py`, `system_settings.py`.
- `services/api/tests/test_flows.py` — os 4 testes da regra no `PUT` **já existem e passam**; são o
  modelo do item B, não alvo.
- `tests/e2e/` inteiro — os cenários e2e de settings continuam como estão; o item C **acrescenta**
  uma camada, não substitui.
- `frontend/src/features/operate/aoVivo.*` — é do plano 013. Se ele já tiver sido executado, os
  testes dele coexistem com os seus sem conflito.

## Fluxo de git

- Branch: `advisor/018-lacunas-de-teste`.
- **Três commits**, um por item, para o revisor poder aceitar parcialmente:
  1. `test(frontend): default de seguranca do faceplate deixa de ser so exercitado`
  2. `test(api): colisao de chave de barramento no import de projeto`
  3. `test(api): cobertura rapida do router de configuracoes do sistema`
- Sem push, sem PR, a menos que o operador peça.
- Em worktree: caminho **ABSOLUTO** em todo `read`/`write`/`edit`, `cwd` explícito em todo shell,
  confirmação por shell depois de cada escrita (`CLAUDE.md`, "Subagente em worktree").

## Passos

### Passo 1 (item A): assertar o default de segurança

Em `frontend/src/features/operate/faceplateVariavel.check.ts`, **acrescente** casos (não altere os
existentes). Leia o arquivo inteiro antes para seguir o estilo e reusar os helpers de fixture que
já existem lá (ex.: `mpcComDv(...)`).

Dois casos:

1. **O default em si**: chamar `gradeDeVariaveis(mpc, undefined, flowId, blockId)` e assertar que
   **toda** linha traz `modos` igual a `{ local_remote: "local", man_auto: "man" }`.
   Asserte o objeto inteiro, não um campo — trocar os dois eixos é justamente um dos erros que se
   quer pegar.
2. **A consequência**: com esse default, a MV **não** é editável e a CV **não** é editável. Se a
   regra de editabilidade morar em `FaceplateVariavel.tsx` (componente) e não numa função pura,
   **não renderize** — asserte a precondição que o componente consome
   (`local_remote !== "remote" || man_auto !== "man"` para MV; `man_auto !== "auto"` para CV) e
   registre no relato que a ligação componente↔regra fica coberta pelo Playwright, não aqui.
   **Não introduza jsdom/testing-library** — seria uma segunda convenção de teste no repo.

**RED genuíno**: troque temporariamente o default em `gradeVariaveis.ts:21` para
`{ local_remote: "remote", man_auto: "man" }`, rode `npm run test:unit` → **deve falhar**. Reverta
**editando de volta** (nunca `git checkout`/`stash`/`reset`), rode de novo → passa. Registre as duas
saídas no relato. Confirme a reversão por shell:
`grep -c 'local_remote: "local" as const' frontend/src/features/operate/gradeVariaveis.ts` → `1`.

**Verifique**:
- `cd frontend && npm run test:unit` → tudo passa, com os novos
- `cd frontend && npm run typecheck` → exit 0
- `git diff -- frontend/src/features/operate/gradeVariaveis.ts` → **vazio**

### Passo 2 (item B): colisão de chave no import

Em `services/api/tests/test_projects_import.py`, **acrescente** casos seguindo as fixtures de bundle
que o arquivo já usa (leia-o inteiro antes) e espelhando os 4 testes de
`services/api/tests/test_flows.py:494` e vizinhos.

Três casos:

1. **Colisão entre dois flows do mesmo bundle** → o import reprova, e a mensagem nomeia **os dois**
   fluxos. Asserte contra a forma real de `projects.py:557`:
   `"fluxo '<B>': a chave de barramento '<key>' já é publicada pelo fluxo '<A>'"`.
   Não invente o texto — copie a f-string do código e confira.
2. **Publish num flow, subscribe em outro** → import **passa**. É o caso legítimo do ADR-042 e o que
   garante que o teste 1 não é um falso positivo grosseiro.
3. **Mesma chave em projeto diferente** → passa. A unicidade é **por projeto** (ADR-042), e este
   caso prova que o acumulador `publicadores` não vaza entre importações.

**Verifique**: `uv run pytest services/api/tests/test_projects_import.py -q` → tudo passa, com os 3
novos.

### Passo 2b (item A, segunda metade): `podeComandar` da tela de malha

**Terceiro caso, mesma natureza — `podeComandar`.** Em
`frontend/src/features/loop/LoopOperatePage.tsx:31-33`:
```ts
/** Modo comandável está em `permitted`? Pura para check. */
export function podeComandar(estado: LoopState, modo: ModoLoop): boolean {
  return MODOS_COMANDAVEIS.includes(modo) && estado.permitted.includes(modo);
}
```
Ela é **exportada** e o docstring diz "Pura para check" — foi deliberadamente extraída para ser
testada. Mas `frontend/src/features/loop/` contém **só** `HeatmapSuperficie.check.ts`; não há check
nenhum cobrindo `podeComandar`. É o predicado que governa `disabled` nos botões que comandam o modo
de uma malha na planta (`:169`), exatamente a mesma natureza do item A: função pura, trava escrita
em planta, sem asserção.

Crie `frontend/src/features/loop/loopOperate.check.ts` (ou acrescente ao check existente do
diretório, se preferir seguir o agrupamento dele) com 3 casos:
- modo em `MODOS_COMANDAVEIS` **e** em `estado.permitted` → `true`
- modo em `MODOS_COMANDAVEIS` mas **fora** de `permitted` → `false`
- modo **fora** de `MODOS_COMANDAVEIS` (ex.: `"iman"` ou `"lo"`, que existem no FF mas só são
  atingidos por rebaixamento/cascata) → `false`, mesmo que apareça em `permitted`


### Passo 3 (item C): teste rápido do `system_settings`

Crie `services/api/tests/test_system_settings.py`. Use `services/api/tests/test_history_retention.py`
como modelo estrutural (é o router vizinho mais parecido: admin-gated, poucas rotas) — leia-o
inteiro antes para copiar a forma das fixtures de cliente e de sessão.

Antes de escrever, **leia `services/api/src/ottima_api/routers/system_settings.py` inteiro** e
cubra o que ele realmente faz. No mínimo:

1. `GET` como **operador** → permitido (confirme a dependência real no router: se for
   `require_operator`, 200; se for `require_admin`, então 403 — **asserte o que o código diz**, não
   o que este plano supõe).
2. `PUT` como **operador** → **403**. Esta é a asserção que mais importa: é o único portão entre um
   operador e o log level do processo inteiro.
3. `PUT` como **admin** com valor válido → 200/204, e o `GET` seguinte devolve o valor novo
   (round-trip). **Ver a exigência de teardown abaixo antes de escrever este caso.**
4. `PUT` como **admin** com valor inválido → **422**, não 500.
5. O evento de auditoria é publicado no `PUT` bem-sucedido — se o arquivo de teste vizinho tiver um
   coletor de eventos, use-o; se não houver forma sem stack, **pule este caso** e registre no relato.

**Verifique**: `uv run pytest services/api/tests/test_system_settings.py -q` → tudo passa.

### Passo 4: gates finais

- `cd frontend && npm run test:unit` → tudo passa
- `cd frontend && npm run typecheck` → exit 0
- `uv run pytest services/api/tests -q` → tudo passa
- `uv run ruff check .` → exit 0
- `uv run ruff format --check .` → exit 0
- `git diff -- services/api/src packages frontend/src` → **vazio** (nenhum código de produção mudou)
- `git status --porcelain` lista só os 3 arquivos em escopo

## Plano de teste

> **TEARDOWN OBRIGATÓRIO — sem ele este teste envenena a sessão inteira.**
>
> `services/api/src/ottima_api/routers/system_settings.py:50` faz
> `logging.getLogger().setLevel(body.log_level)` — muta o **root logger do processo de teste**, e
> nada restaura. Um `PUT {"log_level": "DEBUG"}` bem-sucedido deixa **todo teste subsequente da
> mesma sessão** em DEBUG: SQLAlchemy, asyncio e testcontainers passam a emitir, o que inunda a
> saída **e carrega a máquina**.
>
> Isso importa concretamente neste repo: é exatamente o modo de contenção que a nota do **TD-027**
> responsabiliza ("reproduz com alta taxa porque carrega a máquina antes"), e os arquivos
> alfabeticamente posteriores (`test_tags.py`, `test_users.py`) herdariam o nível — assim como
> todas as demais suítes num `uv run pytest` completo.
>
> **Exija uma fixture `autouse` no arquivo novo** que salve `logging.getLogger().level` antes e o
> restaure depois, e **asserte no fim** que o nível voltou ao original. Sem isso, o plano troca uma
> lacuna de cobertura por um defeito de suíte.

Este plano **é** o plano de teste. Resumo do que entra:

| Item | Arquivo | Casos | Defende |
|---|---|---|---|
| A | `faceplateVariavel.check.ts` + `loopOperate.check.ts` | 2 + 3 | escrita em planta travada: default de modo do MPC e `permitted` da malha |
| B | `test_projects_import.py` | 3 | ADR-042 D5 na fronteira de confiança do bundle |
| C | `test_system_settings.py` | 4-5 + teardown do root logger | RBAC e forma de erro do único router sem camada rápida |

- **Padrões estruturais**: `faceplateVariavel.check.ts` (ele mesmo) para A;
  `services/api/tests/test_flows.py:494` para B; `services/api/tests/test_history_retention.py` para C.
- **Sem `unittest.mock`**, sem jsdom, sem framework novo.
- **Nenhum teste existente deve mudar.**

## Critérios de conclusão

- [ ] Item A: `faceplateVariavel.check.ts` asserta o objeto `modos` completo do default
- [ ] Item A: RED reproduzido e revertido; `grep -c 'local_remote: "local" as const' frontend/src/features/operate/gradeVariaveis.ts` → `1`
- [ ] Item A (2b): `podeComandar` coberto com 3 casos, incluindo o modo fora de `MODOS_COMANDAVEIS`
- [ ] Item B: 3 casos novos em `test_projects_import.py`, um deles provando que publish/subscribe entre flows **passa**
- [ ] Item B: a mensagem asserida é a f-string real de `projects.py:557`, não texto inventado
- [ ] Item C: `services/api/tests/test_system_settings.py` existe, com o `PUT` como operador → **403**
- [ ] Item C: as dependências asseridas correspondem ao que o router realmente declara
- [ ] Item C: fixture `autouse` salva e restaura `logging.getLogger().level`, e um caso asserta que o nível voltou ao original
- [ ] Item C: nenhum teste deixa o root logger em nível diferente do que encontrou
- [ ] `cd frontend && npm run test:unit` → tudo passa
- [ ] `cd frontend && npm run typecheck` → exit 0
- [ ] `uv run pytest services/api/tests -q` → tudo passa
- [ ] `uv run ruff check .` e `ruff format --check .` → exit 0
- [ ] `git diff -- services/api/src packages frontend/src` → **vazio**
- [ ] Três commits separados, mensagens pt-BR com prefixo `test:`
- [ ] Linha de status atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

- Os excertos de "Estado atual" não baterem com o código vivo (drift desde `37b0caa`).
- Item A: o default em `gradeVariaveis.ts:21` já não for `local`/`man` — **pare e relate**. Se
  alguém mudou, é decisão de produto (ou um bug), e não cabe a um plano de teste "corrigir" pinhando
  o valor novo.
- Item A: a regra de editabilidade não estar acessível sem renderizar React e você se sentir
  tentado a introduzir jsdom/testing-library: **não introduza**. Cubra a precondição e relate.
- Item B: a mensagem real de `projects.py` divergir do excerto: use a real, e registre a divergência
  (significa drift desde `37b0caa`).
- Item C: o router declarar dependências diferentes das supostas: **asserte o que o código diz** e
  registre no relato. Não "conserte" o router — é fora de escopo.
- Item C: você concluir que não dá para testar o evento de auditoria sem stack: pule esse caso,
  registre, e entregue os outros. Não suba stack.
- Qualquer necessidade de editar arquivo de produção.

## Notas de manutenção

- **O que um revisor deve olhar no PR**: (1) `git diff` de produção **vazio**; (2) o RED do item A
  registrado — sem ele, a asserção pode estar passando por acidente; (3) o caso B-2
  (publish/subscribe entre flows passa) presente, senão o B-1 pode estar reprovando bundles válidos;
  (4) nenhum `unittest.mock`, nenhum jsdom.
- **O que NÃO fica coberto, e é bom estar escrito**: a ligação entre o default de `modos` e o
  `disabled` real dos campos no DOM continua só no Playwright (`operate-faceplate.spec.ts`), que é
  manual por decisão (ADR-035) e registrado como custo no **TD-026**. O item A cobre a função pura;
  não afirme que cobre a tela.
- **Achados vizinhos de teste, deliberadamente fora deste plano** (registrados no índice como
  vetados sem plano): `test_mpc_arming.py:101-119` e `test_shell`/`test_watchdog.py:473-505` decidem
  por relógio de parede — mesma classe de TD-027/TD-028, mas consertá-los exige seam de clock no
  código de produção (`watch_arm`, `FlowWatchdog`), o que os tira de um plano "só testes".
