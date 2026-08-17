# Plan 003: `POST /api/auth/login` passa a ter teto de tentativas por IP no nginx, sem trancar operador

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de
> verificação e confirme o resultado esperado antes de passar ao próximo passo. Se
> qualquer condição da seção "Condições de PARADA" ocorrer, pare e relate — não
> improvise. Ao terminar, atualize a linha de status deste plano em
> `docs/reports/advisor/README.md`.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 8f9fe76..HEAD -- frontend/nginx.conf frontend/Dockerfile services/api/src/ottima_api/routers/auth.py deploy/docker-compose.yml`
> Se algum arquivo em escopo mudou desde que este plano foi escrito, compare os
> excertos de "Estado atual" com o código vivo antes de prosseguir; divergência é
> condição de PARADA.

## Status

- **Prioridade**: P1
- **Esforço**: S
- **Risco**: LOW
- **Depende de**: nenhum
- **Categoria**: security
- **Planejado em**: commit `8f9fe76`, 2026-08-16

## Por que isso importa

`POST /api/auth/login` não tem teto de tentativas em nenhuma camada: nem contador na
aplicação, nem `limit_req` no nginx que serve a SPA e faz proxy da API. Qualquer máquina
com acesso à porta HTTP da planta pode tentar senhas em série, na velocidade que o
hardware permitir, sem cooldown. A senha mínima aceita tem 8 caracteres
(`ottima_core/schemas/users.py:12`).

O que está do outro lado dessa senha: o papel `admin` pode ativar projeto, editar flow,
deployar e parar; o papel `operator` pode `POST /api/operate/{flow_id}/{block_id}/mv` —
**escrever MV na planta**. Comprometer uma senha aqui não é vazamento de dados, é
comando de processo.

Contexto que mantém isto dentro do escopo decidido: o ADR-023 decidiu HTTP na rede
interna e autenticação local por usuário/senha, e a RNF-04 exige hash Argon2/bcrypt e
JWT com expiração — nada disso trata de força bruta, então este plano não relitiga
decisão nenhuma; preenche uma lacuna.

Depois deste plano: um dicionário de 10 mil senhas deixa de ser uma questão de segundos
e passa a ser de horas, sem que nenhum operador legítimo possa ser trancado fora da HMI.

## Decisão de projeto já tomada (não a refaça)

**Teto por IP no nginx, não bloqueio por usuário na aplicação.** Duas razões, nesta
ordem:

1. **Segurança de processo.** Bloqueio por nome de usuário é um vetor de negação de
   serviço contra o operador: qualquer um que saiba o nome de login pode trancar a conta
   errando senha de propósito. Trancar o operador fora da tela de operação **durante um
   distúrbio de planta** é inaceitável neste domínio — o sistema falha para o lado
   seguro entregando a malha ao PLC, mas o operador ainda precisa da HMI para conduzir.
   Teto por IP degrada a velocidade do atacante sem nunca negar acesso a quem sabe a
   senha e tenta uma vez.
2. **Custo.** `limit_req` é módulo embutido do nginx (`ngx_http_limit_req_module`, já
   presente na imagem `nginx:1.27-alpine`) e o `api` **não publica porta de host** — só
   o serviço `frontend` publica (`deploy/docker-compose.yml:176-177`), então todo tráfego
   de API atravessa este nginx obrigatoriamente. É controle completo, com zero código
   novo, zero dependência nova e zero estado novo em Redis.

Um contador por usuário em Redis, com backoff exponencial em vez de tranca, é a versão
mais forte disto — e está deliberadamente deferida em "Notas de manutenção", porque
exige decisão de política (o que fazer com o operador na décima tentativa) que não cabe
a este plano.

## Estado atual

Arquivos e papéis:

- `frontend/nginx.conf` — o único `server{}` do sistema. Serve a SPA e faz proxy de
  `/api/` e `/ws` para o `api`. É o arquivo a mudar.
- `frontend/Dockerfile` — copia o arquivo acima para `/etc/nginx/conf.d/default.conf`.
- `services/api/src/ottima_api/routers/auth.py` — a rota de login. **Não muda.**
- `deploy/docker-compose.yml` — quem publica porta.

### `frontend/nginx.conf` (arquivo completo, 31 linhas)

```nginx
server {
  listen 80;
  # o healthcheck do compose usa `localhost`, que resolve para ::1 primeiro no Alpine
  listen [::]:80;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;

  # CSP básica (spec §8.5): mitiga XSS com token em localStorage
  add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'" always;

  location /api/ {
    proxy_pass http://api:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }

  # Sem barra final, ao contrário do /api/ acima: com `location /ws/` o nginx responde 301 a
  # `GET /ws` e o handshake nunca chega à API (RF-305, spec F3 §5.3).
  location /ws {
    proxy_pass http://api:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
  }

  location / {
    try_files $uri /index.html;
  }
}
```

Não há `limit_req_zone`, não há `limit_req`, não há `location` específico do login.

### `frontend/Dockerfile:8-10` — por que `limit_req_zone` é válido neste arquivo

```dockerfile
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

O `nginx.conf` stock da imagem inclui `/etc/nginx/conf.d/*.conf` **de dentro do bloco
`http{}`**. Logo, uma diretiva `limit_req_zone` escrita no topo deste arquivo, ANTES do
`server {`, está em contexto `http` e é válida. Escrevê-la dentro do `server{}` é erro de
configuração e o nginx recusa subir.

### `services/api/src/ottima_api/routers/auth.py:16-37` — a rota, para referência

```python
@router.post("/login", response_model=LoginOut)
async def login(
    body: LoginIn,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> LoginOut:
    user = await db.scalar(select(User).where(func.lower(User.username) == body.username.lower()))
    if user is None or not verify_password(body.password, user.password_hash) or not user.is_active:
        # mensagem única: não revelar se o usuário existe (spec §5.1)
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
```

A mensagem única (não revelar existência de usuário) já está correta — **não mude**.

### `deploy/docker-compose.yml:175-180` — quem publica porta

```yaml
    build:
      context: ../frontend
    ports:
      - "${OTTIMA_HTTP_PORT:-80}:80"
    depends_on:
      api:
        condition: service_healthy
```

O serviço `api` não tem `ports:` — confirme rodando
`grep -n "ports:" deploy/docker-compose.yml` e verificando que a única ocorrência
pertence ao `frontend`.

### Restrição dura: os gates de aceite passam por este nginx e logam muito

Um teto apertado quebra a suíte de aceite. Os pontos de login, todos contra
`http://localhost:8080` (o nginx), do mesmo IP:

- `deploy/smoke.sh:57` — L1, um login.
- `tests/e2e/conftest.py:361` — fixture da L2 (43 cenários).
- `tests/e2e/test_api_e2e.py:26` e `:65` — dois logins (admin e operador).
- `tests/e2e/test_f6_portabilidade.py:88` — login de operador.
- `frontend/e2e/fixtures.ts:16` — um login por contexto do Playwright, e o Playwright
  roda specs **em paralelo** (14 arquivos de spec).
- `frontend/e2e/login.spec.ts` — cenários que logam pela UI, incluindo E2E-06, que
  assere 401 com credencial errada.
- `frontend/e2e/settings-page.spec.ts:146` — login de operador.

Portanto a taxa escolhida precisa absorver uma rajada de dezenas de logins legítimos em
poucos segundos, e ainda assim limitar o atacante. `burst` com `nodelay` é o mecanismo
certo: rajada curta passa na hora, taxa sustentada fica limitada.

### Convenções do repositório que se aplicam aqui

- Comentários de configuração em **pt-BR**, explicando a razão no ponto exato — siga o
  estilo das linhas 3, 9 e 18-19 do próprio `nginx.conf`, que documentam por que cada
  escolha está ali.
- **Sem emoji**.
- Novas dependências fora da stack declarada exigem justificativa (`CLAUDE.md:71`). Este
  plano não acrescenta nenhuma: `limit_req` é módulo embutido.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Validar a sintaxe do nginx sem subir o stack | `docker run --rm --add-host api:127.0.0.1 -v "$PWD/frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t` | `syntax is ok` e `test is successful` |
| Rebuild só do frontend | `cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --no-deps frontend` | container sobe `healthy` |
| L1 do gate | `OTTIMA_E2E=1 bash deploy/smoke.sh` | todos os checks passam |
| L2 do gate | ver `CLAUDE.md:115` (exige credenciais inline) | 43 cenários passam |
| Playwright | `cd frontend && npm run e2e` | todos passam |

> **`--add-host api:127.0.0.1` é obrigatório e não é cosmético.** Sem ele o `nginx -t` falha
> com `host not found in upstream "api"` — e falha **também sem nenhuma edição**, porque o
> `location /api/` que já existia usa `proxy_pass http://api:8000;` e o hostname `api` só
> existe dentro da rede do compose. Um container solto não o resolve. O mapeamento
> descartável faz o nome resolver e o teste passa a medir o que interessa: a sintaxe e a
> validade do contexto das diretivas novas. Verificado em 2026-08-16: com `--add-host`, o
> arquivo editado e o original passam os dois; sem ele, os dois falham.

`deploy/.env` é **obrigatório e gitignored**, e não existe nesta worktree — qualquer
comando de `docker compose` exige criá-lo a partir de `deploy/.env.example` primeiro. Se
não puder, o comando de `nginx -t` acima ainda valida a sintaxe sem stack, e é o gate
mínimo deste plano.

**L2 e Playwright NÃO podem rodar juntos** (`CLAUDE.md:145-146`): o E2E-16 publica
`project_activated` duas vezes e derruba os cenários E2E-F3-03/04/08. Serialize.

## Escopo

**Em escopo** (os únicos arquivos que você deve modificar):
- `frontend/nginx.conf`

**Fora de escopo** (NÃO toque):
- `services/api/src/ottima_api/routers/auth.py` — a rota está correta, inclusive a
  mensagem de erro única. Não acrescente contador na aplicação (ver "Decisão de projeto").
- `packages/ottima_core/src/ottima_core/schemas/users.py` — o mínimo de 8 caracteres de
  senha é política de produto; endurecê-lo é outra decisão, não esta.
- `deploy/docker-compose.yml` e `deploy/docker-compose.e2e.yml` — nenhuma porta muda.
- A CSP da linha 10 — outros cabeçalhos de hardening faltam nesse mesmo arquivo
  (`X-Frame-Options`, `X-Content-Type-Options`, `frame-ancestors`), mas isso é um achado
  separado e um commit separado. **Não misture** com este.
- Qualquer `limit_req` em `location /api/` genérico ou em `/ws`: limitar o WebSocket ou
  o restante da API estrangularia dado cíclico e comando de operação. Só o login.

## Fluxo de git

- Branch: você já está em `improve`; commite nela (não faça push, não abra PR).
- **Conventional Commits com mensagem em pt-BR** (`CLAUDE.md:70`). Para este plano:
  `fix(deploy): teto de tentativas por IP no login, sem trancar usuário`

## Passos

### Passo 1: declarar a zona em contexto `http`

No topo de `frontend/nginx.conf`, **antes** da linha `server {`, declare a zona:

```nginx
# Teto de tentativas de login por IP (ngx_http_limit_req_module, embutido no nginx).
# Este arquivo é copiado para /etc/nginx/conf.d/default.conf, incluído de dentro do
# bloco http{} do nginx stock — por isso `limit_req_zone` pode morar aqui, e SÓ aqui:
# dentro do server{} o nginx recusa subir.
# Por IP e não por usuário de propósito: tranca por nome de login seria negação de
# serviço contra o operador, e operador sem HMI durante distúrbio de planta é
# inaceitável (ADR-009/010/017 fazem o processo falhar para o lado seguro, mas a
# condução continua sendo humana).
limit_req_zone $binary_remote_addr zone=login:10m rate=30r/m;
```

`10m` de zona compartilhada guarda na ordem de 160 mil estados de IP — folga enorme para
uma rede de planta.

**Verifique**:
`docker run --rm --add-host api:127.0.0.1 -v "$PWD/frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t`
→ `syntax is ok` / `test is successful`.

### Passo 2: aplicar o teto apenas ao caminho do login

Acrescente um `location` **exato** para o login, antes do `location /api/` (o nginx
resolve `=` com prioridade máxima, então a ordem no arquivo não é o que decide, mas
manter junto ajuda quem lê):

```nginx
  # Só o login é limitado. `burst=20 nodelay` absorve a rajada legítima das suítes de
  # aceite (fixture da L2 em tests/e2e/conftest.py, um login por contexto do Playwright
  # rodando specs em paralelo, smoke.sh) sem enfileirar; acima disso o excedente é
  # recusado com 429 e a taxa sustentada volta a 30/min por IP.
  location = /api/auth/login {
    limit_req zone=login burst=20 nodelay;
    limit_req_status 429;
    proxy_pass http://api:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
```

Repita as três diretivas de proxy: um `location` novo **não herda** o `proxy_pass` do
`location /api/`. Confirme que o `proxy_pass` não tem barra final, igual ao do
`location /api/` — com barra o nginx reescreve o caminho e a rota vira 404.

**Verifique**: `nginx -t` do Passo 1 novamente → `test is successful`.

### Passo 3: provar que o limite existe e que o gate sobrevive

Ver "Plano de teste".

## Plano de teste

Não há teste unitário possível: a mudança é de configuração de proxy, não de código.
A verificação é comportamental, em três níveis, do mais barato ao mais caro.

**Nível 1 — sintaxe (sempre executável, sem `deploy/.env`)**:
`nginx -t` contra a imagem, como nos passos acima.

**Nível 2 — o limite realmente dispara** (exige stack):
Depois de `up -d --build --no-deps frontend`, dispare mais que `burst` requisições de
login em série contra `http://localhost:8080/api/auth/login` com credencial ERRADA e
confirme que as primeiras respondem 401 e as excedentes respondem **429**. Um laço curto
de `curl -s -o /dev/null -w '%{http_code}\n'` basta. Use credencial errada de propósito:
o objetivo é provar o teto, não gerar sessão válida.

Registre o número observado de 401 antes do primeiro 429 — ele tem de ser compatível com
`burst=20`.

**Nível 3 — o gate de aceite não regride** (exige stack; serialize):
1. `OTTIMA_E2E=1 bash deploy/smoke.sh` → passa.
2. L2 conforme `CLAUDE.md:115` → 43 cenários passam.
3. `cd frontend && npm run e2e` → todos passam.

Se o Playwright falhar com 429 em fixture de login, **não relaxe o limite às cegas**:
conte quantos logins concorrentes a suíte faz de fato (`grep -c` nos pontos listados em
"Estado atual" mais o número de workers do `playwright.config.ts`) e ajuste `burst` para
esse número com folga, mantendo `rate` em 30r/m. Registre o número no comentário do
arquivo.

## Critérios de conclusão

Verificáveis por máquina. TODOS têm de valer:

- [ ] `docker run --rm --add-host api:127.0.0.1 -v "$PWD/frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t`
      diz `syntax is ok` e `test is successful`
- [ ] `grep -n "limit_req_zone" frontend/nginx.conf` mostra a diretiva ANTES da linha
      `server {`
- [ ] `grep -n "limit_req zone=login" frontend/nginx.conf` aparece exatamente uma vez,
      dentro do `location = /api/auth/login`
- [ ] `grep -c "limit_req " frontend/nginx.conf` retorna `1` (nenhum outro caminho
      limitado)
- [ ] Nível 2 do plano de teste: laço de login com credencial errada produz 401 nas
      primeiras e 429 nas excedentes
- [ ] Nível 3: `smoke.sh`, L2 e Playwright verdes (ou, se o stack não estiver
      disponível, PARE e relate em vez de declarar concluído)
- [ ] `git status --porcelain` lista apenas `frontend/nginx.conf`
- [ ] Linha de status deste plano atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- `nginx -t` recusar a configuração duas vezes seguidas.
- `grep -n "ports:" deploy/docker-compose.yml` mostrar que o serviço `api` publica porta
  de host. Nesse caso o nginx **não** é caminho obrigatório, o teto é contornável, e a
  premissa central deste plano cai — a decisão passa a ser contador na aplicação, que
  exige a política de "Notas de manutenção" e outra rodada de decisão.
- O Playwright falhar com 429 e o ajuste de `burst` calculado passar de ~50: um número
  desses indica que a suíte loga muito mais do que o levantamento previu, e vale rever se
  as fixtures deveriam reusar token em vez de relogar.
- Você não conseguir criar `deploy/.env` para subir o stack. Entregue o Nível 1
  verificado, relate que 2 e 3 não foram executados e **não** marque os critérios
  correspondentes.

## Notas de manutenção

- **Follow-up deliberadamente deferido**: contador por usuário em Redis com **backoff
  exponencial na resposta** (atrasar, nunca trancar), que endereça o caso do atacante
  que troca de IP. Ficou fora porque exige decisão de política de produto e porque
  introduz estado novo num caminho de autenticação — mudança que merece o processo de
  ADR, não um plano de conserto. A escolha de nunca trancar por usuário deve ser
  preservada em qualquer versão futura, pelo motivo de segurança de processo registrado
  acima.
- **O que um revisor deve escrutinar**: que `limit_req_zone` está em contexto `http`
  (fora do `server{}`); que só o `location` exato do login é limitado, nunca `/api/` nem
  `/ws`; e que o `location` novo repete as diretivas de `proxy_pass`/`proxy_set_header`,
  já que não herda nada.
- **Interação futura**: se algum dia entrar um proxy reverso ou TLS na frente deste nginx
  (o ADR-023 registra TLS como evolução possível), `$binary_remote_addr` passa a ver o IP
  do proxy, não do cliente, e o teto vira global. Nesse dia é preciso
  `real_ip_header X-Forwarded-For` + `set_real_ip_from` antes de o limite voltar a
  significar o que se quer.
- **Vizinho conhecido, deliberadamente fora**: o mesmo arquivo não define
  `X-Frame-Options`, `X-Content-Type-Options` nem `frame-ancestors` na CSP, com o token
  JWT em `localStorage`. É achado separado, listado no índice de `docs/reports/advisor/README.md`.
