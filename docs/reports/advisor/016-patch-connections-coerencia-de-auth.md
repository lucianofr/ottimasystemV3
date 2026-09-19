# Plan 016: `PATCH /api/connections/{id}` passa a checar coerência de autenticação sobre o estado final

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado antes de passar ao próximo. Se qualquer condição da seção "Condições de
> PARADA" ocorrer, pare e relate — não improvise. **O predicado correto NÃO é o mesmo do `POST`** —
> leia a seção "A armadilha" antes de escrever qualquer linha. Ao terminar, atualize a sua linha na
> tabela de status de `docs/reports/advisor/README.md` — a menos que um revisor o tenha despachado
> e dito que ele mantém o índice.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 37b0caa..HEAD -- services/api/src/ottima_api/routers/connections.py packages/ottima-core/src/ottima_core/schemas/connections.py services/api/tests/test_connections.py`
> Se qualquer arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; em caso de divergência, trate como
> condição de PARADA.

## Status

- **Prioridade**: P2
- **Esforço**: S
- **Risco**: LOW — checagem mais estrita numa rota `require_admin`; o risco real é **falso positivo**
  (recusar edição válida), que o Passo 2 cobre com teste dedicado
- **Depende de**: nenhum
- **Categoria**: bug
- **Planejado em**: commit `37b0caa`, 2026-09-19

## Por que isso importa

O `POST /api/connections` recusa uma conexão com `auth_mode="user_password"` sem usuário ou sem
senha. O `PATCH` da mesma conexão **aceita** chegar nesse estado.

O resultado é uma conexão OPC-UA gravada num estado que a própria API considera inválido. O
`opc-worker` — único processo que fala OPC-UA (ADR-006) — tenta autenticar, falha, e o admin não
recebe o 422 que deveria ter recebido no momento de salvar. A falha aparece depois, como conexão
caída no chão de fábrica, longe da causa.

Não é inferência: o **docstring do próprio schema** diz onde a checagem deveria estar, e ela não
está lá.

## Estado atual

**A regra, no `POST`** — `packages/ottima-core/src/ottima_core/schemas/connections.py:38-50`:
```python
class ConnectionCreate(_ConnectionFields):
    project_id: int
    auth_password: str | None = None  # write-only (spec §5.4)

    @model_validator(mode="after")
    def _coerencia(self) -> "ConnectionCreate":
        """Regras de coerência; o ValueError vira 422 no FastAPI."""
        erro = erro_policy_mode(self.security_policy, self.security_mode)
        if erro:
            raise ValueError(erro)
        if self.auth_mode == "user_password" and (not self.auth_username or not self.auth_password):
            raise ValueError("Autenticação usuário/senha exige usuário e senha")
        return self
```

**O contrato do `PATCH`, que aponta para o router** —
`packages/ottima-core/src/ottima_core/schemas/connections.py:53-64`:
```python
class ConnectionUpdate(BaseModel):
    """Atualização parcial; a coerência é checada no router sobre o estado final."""

    name: str | None = Field(default=None, min_length=1)
    endpoint: str | None = Field(default=None, min_length=1)
    security_policy: SecurityPolicy | None = None
    security_mode: SecurityMode | None = None
    auth_mode: AuthMode | None = None
    auth_username: str | None = None
    auth_password: str | None = None  # None = manter a senha atual
    server_cert_file: str | None = None
    polling_period_ms: int | None = Field(default=None, ge=100, le=60000)
```

**O router, que só cumpre metade do que o docstring promete** —
`services/api/src/ottima_api/routers/connections.py:191-218`:
```python
@router.patch("/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: int,
    body: ConnectionUpdate,
    ...
) -> ConnectionOut:
    conn = await _carregar(db, connection_id)
    # auth_password fora do dump: ausente ou None significa manter a senha atual
    data = body.model_dump(exclude_unset=True, exclude={"auth_password"})
    for campo, valor in data.items():
        setattr(conn, campo, valor)
    if body.auth_password is not None:
        conn.auth_password_enc = encrypt_secret(body.auth_password, key=settings.fernet_key)
    if (conn.security_policy == "none") != (conn.security_mode == "none"):
        raise HTTPException(status_code=422, detail=_MSG_POLICY_MODE)
    try:
        await db.commit()
```
A coerência `security_policy`/`security_mode` **é** re-checada (`:207`), sobre o estado final, depois
do merge. A regra de `auth_mode`/`auth_username`/`auth_password` **não é**.

## A armadilha — leia antes de escrever código

**NÃO porte o predicado do `ConnectionCreate._coerencia` para o router.** Ele quebraria toda edição
válida de uma conexão que já usa usuário/senha.

Motivo, visível em `connections.py:201-206` e no comentário do schema (`:62`): no `PATCH`,
`auth_password is None` significa **"manter a senha atual"**, não "não há senha". Um admin que só
renomeia a conexão manda `{"name": "..."}` — `auth_password` chega `None`, e o predicado do `POST`
concluiria "sem senha" e devolveria 422 numa edição perfeitamente legítima.

O predicado correto olha o **estado final persistido**, e a senha final pode vir de dois lugares:

```
auth_mode final == "user_password"
  ⇒ exige  auth_username final não vazio
  E        conn.auth_password_enc preenchido  (senha final, venha ela de onde vier)
```

"Tem senha" se lê **uma vez só**, do estado final persistido. Não some um termo `body.auth_password`
a isso: como a checagem roda **depois** de `conn.auth_password_enc = encrypt_secret(...)` (`:89-90`),
uma senha nova do corpo **já está** em `conn.auth_password_enc` — o termo do corpo seria redundante.

> **BURACO DA STRING VAZIA — o segundo conserto deste plano.** Hoje `:89` testa
> `body.auth_password is not None`. Com `auth_password: ""` isso é **verdadeiro**: cifra-se a
> string vazia, `conn.auth_password_enc` vira um token Fernet não-vazio, e o PATCH passa — enquanto
> `ConnectionCreate._coerencia:48` **recusa** o mesmo corpo (`not self.auth_password` é `True` para
> `""`). Pior: sobrescreve em silêncio uma senha boa por uma vazia cifrada. Então o Passo 2 troca
> `is not None` por verdade-de-string:
> ```python
> if body.auth_password:     # "" deixa de sobrescrever a senha gravada
> ```
> Sem essa troca, a assimetria POST↔PATCH que o plano existe para fechar continua aberta por outra
> porta.

Note também que `auth_username` **está** no `model_dump(exclude_unset=True)`, então o `setattr` do
laço já o aplicou a `conn` quando você fizer a checagem depois do laço — igual ao que a checagem de
`security_policy`/`security_mode` já faz lendo `conn.*`. Só `auth_password` fica de fora do dump
(`exclude={"auth_password"}`), por isso ele precisa ser lido de `body`, não de `conn`.

## Convenções do repositório que se aplicam aqui

- **Python ≥ 3.12**, type hints obrigatórios, Pydantic v2, SQLAlchemy 2.0 async, `ruff` (100 cols).
- **Mensagens de erro em pt-BR, string única no `detail`** — o padrão de `_MSG_POLICY_MODE` e de
  `_reprovado` em `operate.py:282-284`.
- **Helper de mensagem compartilhado**: `erro_policy_mode` já mora em
  `packages/ottima-core/src/ottima_core/schemas/connections.py` e é usado pelo `POST` e (pela forma
  equivalente) pelo `PATCH`. **Siga esse precedente**: extraia a regra nova para uma função no mesmo
  módulo, consumida pelos dois lados — não duplique a string em dois arquivos.
- **Nunca reproduzir valor de segredo** em log, mensagem ou teste. A mensagem fala de *ausência* de
  senha, nunca do valor.
- **Commits em Conventional Commits, mensagem pt-BR.**

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Lint | `uv run ruff check .` | exit 0 |
| Formato | `uv run ruff format --check .` | exit 0 |
| Testes de conexões | `uv run pytest services/api/tests/test_connections.py -q` | tudo passa |
| Testes da API | `uv run pytest services/api/tests -q` | tudo passa |
| Testes do core | `uv run pytest packages/ottima-core -q` | tudo passa |
| Regra num lugar só | `grep -rc 'exige usuário e senha' packages services` | soma `1` (só o schema) |

**NÃO rode** `uv run pytest` sem recorte de pasta (~20 min, testcontainers, dois flaky registrados:
TD-027, TD-028).
**NÃO rode** `docker compose`, `deploy/smoke.sh`, `pytest -m e2e`, `npx playwright test` sem
`--list` — o stack de 8 serviços do dono está no ar com planta simulada viva.
**NÃO invoque** nenhuma ferramenta do servidor MCP `ottima` desta sessão.

## Escopo

**Em escopo** (únicos arquivos a modificar):
- `packages/ottima-core/src/ottima_core/schemas/connections.py` — a função de regra compartilhada
- `services/api/src/ottima_api/routers/connections.py` — a chamada no `PATCH`
- `services/api/tests/test_connections.py`

**Fora de escopo** (NÃO toque, mesmo parecendo relacionado):
- A checagem `security_policy`/`security_mode` em `:207` — **já está certa**. É o modelo.
- `encrypt_secret` e a ausência de guarda de chave vazia (`packages/ottima-core/src/ottima_core/security.py:33-34`)
  — achado real e **separado** (carry-over #4 desta auditoria), registrado no índice. Tocá-lo aqui
  misturaria dois consertos num diff.
- O `POST /api/connections` e `ConnectionCreate._coerencia` — o comportamento dele **não muda**.
  Você extrai a regra, ele passa a chamá-la, e o resultado tem de ser bit a bit o mesmo.
- `services/opc-worker/` inteiro.
- Qualquer modelo de barramento, canal, ou `docs/`.

## Fluxo de git

- Branch: `advisor/016-patch-connections-coerencia`.
- Um commit. Sugestão:
  `fix(api): PATCH de conexao valida coerencia de autenticacao sobre o estado final`
- Sem push, sem PR, a menos que o operador peça.
- Em worktree: caminho **ABSOLUTO** em todo `read`/`write`/`edit`, `cwd` explícito em todo shell,
  confirmação por shell depois de cada escrita (`CLAUDE.md`, "Subagente em worktree").

## Passos

### Passo 1: extrair a regra para o módulo de schemas

Em `packages/ottima-core/src/ottima_core/schemas/connections.py`, ao lado de `erro_policy_mode`,
crie uma função que responda à pergunta sobre o **estado final**, recebendo o que já se sabe:

```python
def erro_auth_user_password(
    auth_mode: AuthMode, auth_username: str | None, *, tem_senha: bool
) -> str | None:
    """`None` quando coerente. `tem_senha` é o estado FINAL da senha — no POST, o valor do corpo;
    no PATCH, `conn.auth_password_enc` depois do merge, porque `auth_password=None` ali significa
    "manter a atual" (schema §5.4) e ausência no corpo não é ausência de senha."""
    if auth_mode == "user_password" and (not auth_username or not tem_senha):
        return "Autenticação usuário/senha exige usuário e senha"
    return None
```

Depois faça `ConnectionCreate._coerencia` **chamar** essa função, substituindo o `if` inline de
`:48-49`, com `tem_senha=bool(self.auth_password)`. O comportamento do `POST` tem de ficar
**idêntico** — a string da mensagem é a mesma.

**Verifique**:
- `grep -rc 'exige usuário e senha' packages services` → soma `1` (a string existe num lugar só)
- `uv run pytest packages/ottima-core -q` → tudo passa
- `uv run pytest services/api/tests/test_connections.py -q` → tudo passa (o `POST` não mudou)

### Passo 2: chamar no `PATCH`, sobre o estado final

Em `services/api/src/ottima_api/routers/connections.py::update_connection`, **depois** do laço de
`setattr` e **depois** da atribuição de `conn.auth_password_enc`, ao lado da checagem de
`security_policy`/`security_mode` que já existe:

```python
    erro_auth = erro_auth_user_password(
        conn.auth_mode,
        conn.auth_username,
        tem_senha=bool(conn.auth_password_enc),
    )
    if erro_auth:
        raise HTTPException(status_code=422, detail=erro_auth)
```

E, logo acima, troque a guarda da cifragem (`:89`) de `is not None` para verdade-de-string:
```python
    if body.auth_password:
        conn.auth_password_enc = encrypt_secret(body.auth_password, key=settings.fernet_key)
```

Pontos que decidem o acerto:
- `conn.auth_mode` e `conn.auth_username` — lidos de **`conn`**, já mesclados pelo laço.
- `tem_senha=bool(conn.auth_password_enc)` — **um termo só**, lido do estado final. A senha nova do
  corpo já foi cifrada para lá na linha acima; somar `body.auth_password is not None` seria
  redundante e reabriria o buraco da string vazia.
- **Ordem**: a cifragem vem antes da checagem, e a checagem **antes** do `await db.commit()`. Se a
  checagem ficar depois do commit, grava e só então recusa.
- **NÃO reuse `erro_auth_username`** (`schemas/connections.py:20-24`): o docstring dele o fixa como
  "só do bundle: exige usuário, nunca senha", porque o import de projeto aterrissa
  deliberadamente sem segredos (`pending_secrets`). Reusá-lo sub-valida aqui; estendê-lo quebra o
  import. Crie a função irmã e deixe-o intocado.
- Acrescente `erro_auth_user_password` ao import existente de `ottima_core.schemas.connections`.

**Verifique**:
- `uv run ruff check services/api` → exit 0
- `uv run pytest services/api/tests/test_connections.py -q` → ainda tudo passa (antes dos testes novos)

### Passo 3: testes — inclusive o falso positivo

Em `services/api/tests/test_connections.py` (leia o arquivo inteiro antes; siga o estilo e as
fixtures dele). **Quatro** casos, e o terceiro é o que protege contra a armadilha:

1. **O buraco fechado**: conexão `anonymous` existente → `PATCH {"auth_mode": "user_password"}` sem
   usuário e sem senha → **422**, `detail` = "Autenticação usuário/senha exige usuário e senha".
   *Este é o RED*: antes do Passo 2 ele devolve **200**. Confirme e registre a saída real.
2. **Usuário sem senha**: `PATCH {"auth_mode": "user_password", "auth_username": "x"}` numa conexão
   que nunca teve senha → **422**.
3. **NÃO-REGRESSÃO, o mais importante**: conexão que **já** é `user_password` com usuário e senha
   gravados → `PATCH {"name": "outro nome"}` → **200**. Prova que "manter a senha atual" continua
   funcionando e que a checagem não virou falso positivo.
4. **Definir tudo de uma vez**: conexão `anonymous` →
   `PATCH {"auth_mode": "user_password", "auth_username": "u", "auth_password": "..."}` → **200**.
5. **String vazia não vira senha**: conexão que já é `user_password` com senha gravada →
   `PATCH {"auth_password": ""}` → a senha gravada **não** é sobrescrita. Antes do conserto de
   `:89`, `""` passa por `is not None`, é cifrada e substitui a senha boa por uma vazia cifrada.
   Asserte que `auth_password_enc` continua igual ao de antes do PATCH (compare o valor lido do
   banco antes e depois — **sem** imprimir nem asserir o conteúdo em si).

**Nunca** asserte o valor da senha nem o conteúdo de `auth_password_enc`; asserte status e, quando
fizer sentido, que `auth_password_enc` deixou de ser nulo.

**Verifique**: `uv run pytest services/api/tests/test_connections.py -q` → tudo passa, com os 4 novos.

### Passo 4: gates finais

- `uv run ruff check .` → exit 0
- `uv run ruff format --check .` → exit 0
- `uv run pytest services/api/tests -q` → tudo passa
- `uv run pytest packages/ottima-core -q` → tudo passa
- `git status --porcelain` lista só os 3 arquivos em escopo

## Plano de teste

- **Novos**: 4 em `services/api/tests/test_connections.py` (Passo 3).
- **Padrão estrutural**: os testes já existentes do mesmo arquivo para `POST`/`PATCH` de conexão.
- **O repo não usa `unittest.mock`** (zero ocorrências, verificado). Não introduza.
- **Nenhum teste existente deve mudar.** Se um teste de `POST` mudar, a extração do Passo 1 alterou
  comportamento — pare e relate.
- **Verificação**: `uv run pytest services/api/tests -q` → tudo passa.

## Critérios de conclusão

- [ ] `erro_auth_user_password` existe em `packages/ottima-core/src/ottima_core/schemas/connections.py`
- [ ] `ConnectionCreate._coerencia` chama a função; o `if` inline de `:48-49` não existe mais
- [ ] `grep -rc 'exige usuário e senha' packages services` → soma `1`
- [ ] O `PATCH` chama a função com `tem_senha=bool(conn.auth_password_enc)` — **um** termo, sem `body.auth_password`
- [ ] A guarda da cifragem virou `if body.auth_password:` (verdade-de-string), fechando o caso `""`
- [ ] `erro_auth_username` (`schemas/connections.py:20-24`) **não** foi alterado nem reusado
- [ ] A checagem está **antes** do `await db.commit()`
- [ ] A checagem de `security_policy`/`security_mode` (`:207`) não foi alterada
- [ ] 5 testes novos passando: não-regressão (caso 3) e string vazia (caso 5) inclusos
- [ ] O RED do caso 1 (200 antes, 422 depois) está registrado no relato
- [ ] Nenhum valor de segredo aparece em teste, log ou mensagem
- [ ] `git diff -- packages/ottima-core/src/ottima_core/security.py` → **vazio**
- [ ] `uv run ruff check .` e `ruff format --check .` → exit 0
- [ ] `uv run pytest services/api/tests -q` e `packages/ottima-core -q` → tudo passa
- [ ] `git status --porcelain` lista só os 3 arquivos em escopo
- [ ] Linha de status atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

- Os excertos de "Estado atual" não baterem com o código vivo (drift desde `37b0caa`).
- O caso 3 (não-regressão) falhar: **seu predicado está errado** — provavelmente faltou o termo
  `bool(conn.auth_password_enc)`. Não "conserte" afrouxando o caso 1; releia "A armadilha".
- `ConnectionUpdate` já não trouxer `auth_password` com o comentário "None = manter a senha atual":
  o contrato mudou e o predicado deste plano pode não valer. Relate.
- Algum teste existente precisar mudar.
- Você se pegar editando `security.py`, `encrypt_secret` ou o `POST`: fora de escopo.
- A coluna do modelo não se chamar `auth_password_enc`: relate o nome real, não adivinhe.

## Notas de manutenção

- **O que interage com isto**: qualquer campo novo de autenticação na conexão. A regra passa a ter
  **um** dono (`erro_auth_user_password`), consumido pelo `POST` e pelo `PATCH` — estenda a função,
  não os call sites.
- **O que um revisor deve olhar no PR**: (1) `tem_senha` com **um** termo, lido de `conn`; (2) a
  guarda da cifragem sendo `if body.auth_password:`, não `is not None`; (3) a checagem antes do
  `commit`; (3) o teste de não-regressão existindo e passando; (4) o comportamento do `POST`
  inalterado.
- **Adiado de propósito**: `encrypt_secret` sem guarda de chave vazia
  (`packages/ottima-core/src/ottima_core/security.py:33-34`, chamado em `connections.py:164` e
  `:206`) — com `OTTIMA_FERNET_KEY` vazia o primeiro cadastro com senha dá 500 opaco. Mesmo arquivo,
  conserto diferente, e o boot já loga `critical` por decisão documentada em `config.py:50-67`. Está
  no índice como vetado sem plano.
