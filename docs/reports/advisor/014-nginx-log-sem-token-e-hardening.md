# Plan 014: Proxy da SPA para de gravar JWT no access log e ganha cabeçalhos de hardening

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado antes de passar ao próximo. Se qualquer condição da seção "Condições de
> PARADA" ocorrer, pare e relate — não improvise. **Este plano são DOIS commits separados no mesmo
> arquivo** — não os misture (o advisor anterior registrou essa exigência para o plano 003, que
> tocava o mesmo `nginx.conf`). Ao terminar, atualize a sua linha na tabela de status de
> `docs/reports/advisor/README.md` — a menos que um revisor o tenha despachado e dito que ele
> mantém o índice.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 37b0caa..HEAD -- frontend/nginx.conf frontend/Dockerfile frontend/src/features/flows/canalPrimitivos.ts packages/ottima-mcp/src/ottima_mcp/confirmacao.py`
> Se qualquer arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; em caso de divergência, trate como
> condição de PARADA.

## Status

- **Prioridade**: P1
- **Esforço**: S
- **Risco**: LOW — resposta de proxy e formato de log; nenhuma rota de controle é tocada
- **Depende de**: nenhum. **Conflita em arquivo** com o plano 012? Não — 012 é `AppShell.tsx`. Mas
  se outro plano tocar `nginx.conf`, serialize.
- **Categoria**: security
- **Planejado em**: commit `37b0caa`, 2026-09-19

## Por que isso importa

Dois problemas independentes no mesmo arquivo, ambos de superfície pequena e consequência grande.

**1. O JWT é gravado em disco, em claro, indefinidamente.**

O cliente monta a URL do WebSocket com o token na query string —
`frontend/src/features/flows/canalPrimitivos.ts:65-68`:
```ts
export function urlDoWs(origem: Location, token: string): string {
  const protocolo = origem.protocol === "https:" ? "wss:" : "ws:";
  return `${protocolo}//${origem.host}/ws?token=${encodeURIComponent(token)}`;
}
```
E o `frontend/nginx.conf` **não define `access_log` nem `log_format` em lugar nenhum**. O container
é `nginx:1.27-alpine` stock (`frontend/Dockerfile:8`), cujo `/etc/nginx/nginx.conf` faz
`access_log /var/log/nginx/access.log combined;` com esse caminho **simlinkado para stdout**, e o
formato `combined` inclui `$request` — a linha de requisição **inteira, com a query string**. O
driver de log padrão do Docker (`json-file`) persiste isso em disco no host, sem rotação
configurada neste repo.

O token tem TTL de **1 ano** (`packages/ottima-core/src/ottima_core/config.py:30`,
`token_ttl_hours: int = 8760` — decisão deliberada de HMI de planta, documentada nas linhas 22-29;
**não é achado e não se muda aqui**).

O que agrava: o servidor MCP desta casa (`packages/ottima-mcp/src/ottima_mcp/confirmacao.py:47-50`,
`_url_ws`) faz **exatamente a mesma coisa**, e a conta `agente` do MCP tem papel **admin**
(`docs/adr/ADR-036-servidor-mcp-para-agentes.md`, decisão 2; o próprio ADR registra como contra:
*"(−) Token admin vive no env da máquina do agente"*). O tráfego do MCP também passa pelo nginx
(`OTTIMA_URL=http://localhost:8080` em `.mcp.json`). Então cada sessão de confirmação de comando de
um agente grava no log do host um token que dá acesso à REST inteira — criar usuário, reescrever
credencial de conexão OPC, importar e ativar projeto, mudar log level — não só às ~22 ferramentas
curadas do MCP.

Cada reconexão de WS (reload de aba, piscada de rede) escreve de novo.

**Delimitação importante, e é o que torna este plano pequeno**: a **forma** — token na query string —
é risco **aceito e registrado** em `docs/specs/F3-motor-canvas.md:193`:
> **Auth:** `?token=` na URL de conexão, papel operator. **[NOVA — implementação]** (forma; risco
> aceito coerente com HTTP interno, ADR-023)

Portanto **este plano NÃO troca o transporte do token**. Propor endpoint de ticket de curta duração
ou `Sec-WebSocket-Protocol` seria relitigar decisão normativa (`CLAUDE.md` item 1: "Nenhuma decisão
registrada em ADR pode ser relitigada"). O risco aceito era **exposição no fio, em rede interna**. O
que **não** estava coberto por essa aceitação, e é o achado real, é a **persistência indefinida em
disco** num log que qualquer pessoa com `docker logs` ou acesso ao log do host lê, somada ao fato de
que um token **admin** percorre o mesmo caminho. Isso se resolve no nginx, sem tocar na forma.

**2. A tela que escreve SP e MV na planta pode ser embutida em iframe de origem externa.**

`frontend/nginx.conf` define **apenas** `Content-Security-Policy` (`:20` e `:61`), e essa CSP **não
tem diretiva `frame-ancestors`**. Não há `X-Frame-Options` nem `X-Content-Type-Options` em nenhum
ponto do arquivo. A API também não acrescenta cabeçalho de segurança nenhum (confirmado: zero
ocorrências de `X-Frame-Options`/`X-Content-Type-Options`/`CORSMiddleware` em
`services/api/src/ottima_api`). O token fica em `localStorage`
(`frontend/src/lib/api.ts:33,37,41`).

`/operacao/:flowId/:blockId` é o faceplate que escreve SP e MV num MPC vivo. Clickjacking sobre ele
é o cenário de risco.

Este é o **carry-over #1** da auditoria de 2026-08-16, verificado **AINDA VALE** em `37b0caa`. O
nginx ganhou o rate-limit de login desde então (`:9`, `:26-32`, plano 003 do advisor anterior) —
melhoria real e não relacionada — mas os três cabeçalhos nomeados continuam ausentes.

## Estado atual

`frontend/nginx.conf` inteiro tem 68 linhas. Os pontos relevantes, verbatim em `37b0caa`:

**Topo do arquivo — o precedente de diretiva de nível `http{}` (`:1-9`)**:
```nginx
# Teto de tentativas de login por IP (ngx_http_limit_req_module, embutido no nginx).
# Este arquivo é copiado para /etc/nginx/conf.d/default.conf, incluído de dentro do
# bloco http{} do nginx stock — por isso `limit_req_zone` pode morar aqui, e SÓ aqui:
# dentro do server{} o nginx recusa subir.
limit_req_zone $binary_remote_addr zone=login:10m rate=30r/m;
```
> **Isto é load-bearing para o Passo 1**: `log_format` também é diretiva de nível `http{}`, então
> **pode morar neste mesmo topo**, exatamente como `limit_req_zone`. Não tente pôr `log_format`
> dentro de `server{}` — o nginx recusa subir, pelo mesmo motivo registrado no comentário.

**A CSP no nível `server{}` (`:19-20`)**:
```nginx
  # CSP básica (spec §8.5): mitiga XSS com token em localStorage
  add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'" always;
```

**O proxy de WS, hoje sem `access_log` (`:40-48`)**:
```nginx
  # Sem barra final, ao contrário do /api/ acima: com `location /ws/` o nginx responde 301 a
  # `GET /ws` e o handshake nunca chega à API (RF-305, spec F3 §5.3).
  location /ws {
    proxy_pass http://api:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
  }
```

**A armadilha de herança, documentada pelo próprio arquivo (`:56-63`)**:
```nginx
  # A CSP do server{} é REPETIDA aqui de propósito: `add_header` num location CANCELA a
  # herança do bloco pai, e sem esta linha o index.html — exatamente a resposta que a CSP
  # protege (spec §8.5, token em localStorage) — sairia sem ela. Nenhum outro location
  # define `add_header`, então todos continuam herdando.
  location = /index.html {
    add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'" always;
    add_header Cache-Control "no-store" always;
  }
```

> **ARMADILHA Nº 1 — `add_header` cancela herança.** Se você acrescentar os cabeçalhos novos só no
> `server{}`, o `location = /index.html` **continua definindo `add_header`** e portanto **cancela a
> herança** — o `index.html`, que é exatamente a resposta que os cabeçalhos mais precisam cobrir,
> sairia sem eles. O arquivo já sabe disso e registra o motivo. **Acrescente em ambos os blocos.**
> O comentário de `:59` ("Nenhum outro location define `add_header`, então todos continuam
> herdando") continua verdadeiro depois da sua edição — você não está criando `add_header` em
> location novo, está estendendo os dois que já existem.

> **ARMADILHA Nº 2 — `nginx -t` em container solto falha, e não é culpa sua.** Este arquivo faz
> `proxy_pass http://api:8000`. Num container nginx avulso o hostname `api` não resolve, então
> `nginx -t` **falha** — e falha **igualmente** com o arquivo original, sem nenhuma edição sua. O
> advisor anterior documentou isso no registro do plano 003: gastou-se tempo concluindo que o gate
> tinha passado quando não podia passar. A receita correta está no Passo 5 e exige anexar o
> container à rede do compose. **Não conclua que a sua edição quebrou o nginx** se vir
> `host not found in upstream "api"`.

## Convenções do repositório que se aplicam aqui

- **Comentários em pt-BR explicando o PORQUÊ**, no estilo denso que o arquivo já usa: cada bloco tem
  um comentário nomeando o incidente ou a spec que o motivou (`:5-8` rate-limit por IP e não por
  usuário; `:13-14` o `listen [::]` por causa do healthcheck; `:50-59` o `no-store` e a herança).
  **Siga esse padrão** — os seus dois blocos novos precisam de comentário próprio dizendo o que
  protegem.
- **Não criar segunda convenção.** O rate-limit já resolveu "diretiva de `http{}` mora no topo"; a
  CSP já resolveu "repetir no `location = /index.html`". Reuse as duas soluções.
- **Commits em Conventional Commits, mensagem pt-BR.** Exemplo real do plano 003:
  `fix(deploy): teto de tentativas por IP no login, sem trancar usuário`.
- **Rótulos e mensagens em pt-BR** (ADR-023). Isto é config, não UI, mas os comentários seguem a
  mesma regra.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Sintaxe do nginx | ver receita do Passo 5 | `syntax is ok` / `test is successful` |
| Log sem query string | `grep -cE '^ *log_format' frontend/nginx.conf` | `1` |
| `access_log` no /ws | `awk '/location \/ws/,/^  }/' frontend/nginx.conf \| grep -cE '^ +access_log'` | `1` |
| `frame-ancestors` | `grep -c "frame-ancestors 'none'" frontend/nginx.conf` | **`2`** (server + index.html) |
| `X-Frame-Options` | `grep -c 'X-Frame-Options' frontend/nginx.conf` | **`2`** |
| `nosniff` | `grep -c 'X-Content-Type-Options' frontend/nginx.conf` | **`2`** |
| Cabeçalhos nos DOIS blocos | `grep -cE '^ +add_header' frontend/nginx.conf` | **`7`** — é o check que pega a ARMADILHA Nº 1 (sem `^ +` conta os comentários e devolve `9`) |
| Rate-limit intacto | `grep -cE '^ *limit_req_zone' frontend/nginx.conf` | `1` (sem âncora dá **2**: o comentário de `:3` nomeia a diretiva) |
| Nada além do nginx | `git diff --name-only` | só `frontend/nginx.conf` |

> **ANCORE TODA CONTAGEM DE DIRETIVA.** Este arquivo documenta cada bloco citando o nome da
> diretiva **dentro do comentário** (`:3` nomeia `limit_req_zone`; `:56` e `:59` nomeiam
> `add_header`). Logo, `grep -c '<diretiva>'` conta comentário junto e devolve número inflado —
> `grep -c 'limit_req_zone'` já devolve **2** no arquivo **intocado**. Toda contagem de diretiva
> nesta tabela usa `^ *` ou `^ +` por isso. Se você acrescentar um comentário em estilo da casa
> (e o Passo 1 pede que acrescente), a forma sem âncora infla de novo. `grep -c 'limit_req '`
> (com espaço final) é exceção segura: casa só a diretiva `limit_req`, não o `limit_req_zone`.

**Sobre o stack**: o stack de 8 serviços do dono está no ar (`ottima-*-1`, planta simulada viva).

**NÃO rode**: `docker compose up/down/build/restart/start/stop` (nenhum), `deploy/smoke.sh`,
`uv run pytest` (em nenhum escopo), `pytest -m e2e`, `npx playwright test` sem `--list`,
`npm run e2e`, `scripts/setup-l3.py`. **NÃO invoque** nenhuma ferramenta do servidor MCP `ottima`
desta sessão — comandam a planta viva.

**O ÚNICO comando docker permitido** é o `docker run --rm` do Passo 5: container descartável, sem
publicar porta, sem tocar em nenhum serviço do compose. Ele **não** reconstrói nem reinicia nada.

**`curl -I http://localhost:8080/` NÃO é verificação válida da sua edição.** A porta 8080 serve o
container **do dono**, com o bundle e o `nginx.conf` da `main` — não o seu arquivo editado. Rodar
isso prova o estado antigo, e dá verde falso. A verificação de cabeçalho **em resposta real** é do
revisor, depois de reconstruir o container (runbook no plano 009).

## Escopo

**Em escopo** (único arquivo a modificar):
- `frontend/nginx.conf`

**Fora de escopo** (NÃO toque, mesmo parecendo relacionado):
- `frontend/src/features/flows/canalPrimitivos.ts` — **a forma `?token=` fica**. É risco aceito em
  `docs/specs/F3-motor-canvas.md:193` coerente com ADR-023. Mudar o transporte do token é relitigar
  decisão normativa.
- `packages/ottima-mcp/src/ottima_mcp/confirmacao.py` — mesma razão.
- `packages/ottima-core/src/ottima_core/config.py` — o TTL de 1 ano é decisão documentada nas linhas
  22-29. Não é achado.
- `frontend/src/lib/api.ts` — mover o token de `localStorage` para cookie `HttpOnly` mudaria o
  modelo de auth inteiro. Fora.
- `frontend/Dockerfile`, `deploy/docker-compose.yml`, `deploy/docker-compose.e2e.yml` — inclusive a
  configuração do driver de log. Se você achar que rotação de log do Docker deveria existir,
  **registre como sugestão no relato**, não edite.
- `services/api/` inteiro — nenhum middleware de cabeçalho lá; a SPA é servida pelo nginx.
- `docs/` inteiro, inclusive ADR-023, ADR-036 e a spec F3. A nota de ADR-036 sugerida no Passo 4 é
  **proposta no seu relato**, para o dono aplicar pelo processo do item 4 do `CLAUDE.md`.
- `frontend/src/app/AppShell.tsx` — plano 012.

## Fluxo de git

- Branch: `advisor/014-nginx-log-e-hardening`.
- **DOIS commits separados**, nesta ordem:
  1. `fix(deploy): access log do /ws deixa de gravar o token da query string` (Passos 1-2)
  2. `fix(deploy): SPA ganha frame-ancestors, X-Frame-Options e nosniff` (Passo 3)
  O passo 4 não produz commit (é proposta no relato). Misturar os dois num commit só dificulta
  reverter um sem o outro, e o advisor anterior registrou exatamente essa exigência para este
  arquivo.
- Sem push, sem PR, a menos que o operador peça.
- Em worktree: caminho **ABSOLUTO** em todo `read`/`write`/`edit`, `cwd` explícito em todo shell,
  confirmação por shell depois de cada escrita (`CLAUDE.md`, "Subagente em worktree").

## Passos

### Passo 1: definir um formato de log sem a query string (commit 1)

No **topo do arquivo**, ao lado do `limit_req_zone` existente (nível `http{}` — ver o comentário de
`:1-4`), acrescente um `log_format` que use **`$uri`** em vez de `$request`. `$uri` é o caminho
normalizado **sem** a query string; é isso que remove o token, e remove para qualquer parâmetro
futuro, não só para `token`.

Forma a produzir:
```nginx
# O access log do /ws NÃO pode conter a query string: o token de sessão viaja nela
# (canalPrimitivos.ts:65-68, forma aceita pela spec F3 §5.3 / ADR-023) e o log do container
# é persistido em disco no host. `$uri` é o caminho sem `$args` — mesmo formato `combined`,
# menos a parte que queima credencial.
log_format canal_sem_token '$remote_addr - $remote_user [$time_local] "$request_method $uri" '
                           '$status $body_bytes_sent "$http_referer" "$http_user_agent"';
```

Mantenha os mesmos campos do `combined`, trocando **só** `"$request"` por `"$request_method $uri"`.
Não invente formato próprio com campos extras.

**Verifique**: `grep -cE '^ *log_format' frontend/nginx.conf` → `1`. (Sem a âncora, o comentário
que você acabou de escrever nomeando `log_format` entraria na conta.)

### Passo 2: aplicar o formato só ao `/ws` (commit 1)

Dentro do `location /ws` existente (`:42-48`), acrescente **uma** linha `access_log`, mantendo todas
as diretivas de proxy intactas:

```nginx
  location /ws {
    access_log /dev/stdout canal_sem_token;
    proxy_pass http://api:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
  }
```

Decisões que este plano fixa, e por quê:
- **`/dev/stdout`, não `off`**: desligar o log do `/ws` perderia o registro de que houve handshake e
  qual o status — diagnóstico útil quando o operador relata "a tela congelou". O objetivo é remover
  o segredo, não a visibilidade.
- **Só no `/ws`**: os demais locations continuam herdando o `combined` do `http{}`. Nenhum outro
  endpoint recebe segredo na query string (a REST autentica por header `Authorization` —
  `frontend/src/lib/api.ts`). Não espalhe o formato novo pelo arquivo inteiro.
- **Não use `if` nem `map` para redigir `token=`**: substituição por regex no log é frágil e
  específica demais. Trocar `$request` por `$uri` resolve a classe inteira.

**Verifique**:
- `awk '/location \/ws/,/^  }/' frontend/nginx.conf | grep -cE '^ +access_log'` → `1`
- `grep -cE '^ *limit_req_zone' frontend/nginx.conf` → `1` (o rate-limit não foi tocado; sem âncora dá `2`)
- `grep -c 'proxy_read_timeout 3600s' frontend/nginx.conf` → `1` (o proxy de WS continua intacto)

### Passo 3: cabeçalhos de hardening, nos DOIS blocos (commit 2)

Acrescente `frame-ancestors 'none'` à CSP existente **e** os dois cabeçalhos novos, em **ambos** os
lugares que já têm `add_header` — ver ARMADILHA Nº 1.

No `server{}` (linha `:20` hoje), a CSP passa a ser:
```nginx
  add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'" always;
  add_header X-Frame-Options "DENY" always;
  add_header X-Content-Type-Options "nosniff" always;
```

E **a mesma tríade** dentro de `location = /index.html` (linha `:61` hoje), mantendo o
`Cache-Control: no-store` que já está lá:
```nginx
  location = /index.html {
    add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Cache-Control "no-store" always;
  }
```

Decisões que este plano fixa:
- **Não altere nenhuma outra diretiva da CSP existente.** `style-src 'unsafe-inline'` é necessário
  para o Tailwind/shadcn e não está em julgamento aqui. Você acrescenta **uma** diretiva
  (`frame-ancestors 'none'`), não reescreve a política.
- **`X-Frame-Options: DENY` apesar de `frame-ancestors 'none'` já cobrir**: redundância deliberada
  para clientes que não honram CSP2. Custo zero.
- **Não adicione `Strict-Transport-Security`**: o produto roda em **HTTP interno** (ADR-023; HTTPS é
  não-objetivo v1, `PRODUCT.md:41`). HSTS sobre HTTP é inócuo na melhor hipótese e confuso na pior.
- **Não adicione `add_header` em nenhum outro location.** O comentário de `:59` afirma que nenhum
  outro location define `add_header`, e essa afirmação tem de continuar verdadeira — é o que garante
  que `/api/`, `/ws` e `/` herdam a política do `server{}`.
- Atualize o comentário de `:56-59` apenas no que ele passar a dizer de errado (ele enumera "a CSP";
  agora são três cabeçalhos). **Não reescreva a explicação da herança** — ela continua correta e é o
  motivo de o bloco existir.

**Verifique**:
- `grep -c "frame-ancestors 'none'" frontend/nginx.conf` → **`2`**
- `grep -c 'X-Frame-Options' frontend/nginx.conf` → **`2`**
- `grep -c 'X-Content-Type-Options' frontend/nginx.conf` → **`2`**
- `grep -cE '^ +add_header' frontend/nginx.conf` → **`7`** (3 no `server{}` + 4 no `location = /index.html`).
  **Use a forma com âncora `^ +`.** Sem ela, `grep -c 'add_header'` devolve **`9`**, porque conta
  também as duas menções em comentário (`nginx.conf:56` e `:59`) — número errado, e o executor
  concluiria que a edição falhou.
- `grep -c 'unsafe-inline' frontend/nginx.conf` → `2` (a diretiva de style não foi removida)

### Passo 4: propor a nota de ADR — NÃO editar `docs/`

A ADR-036 registra como contra *"(−) Token admin vive no env da máquina do agente"*. A persistência
em log de acesso é uma segunda superfície para o mesmo token admin, e o ADR não a menciona.

**Não edite `docs/`** — é normativo e exige o processo do item 4 do `CLAUDE.md`. Em vez disso,
**escreva no seu relatório final** o texto proposto, pronto para o dono colar:

> *(proposta)* — **(−) O token admin do MCP também atravessa o proxy da SPA na query string do
> `/ws`, forma aceita pela spec F3 §5.3 / ADR-023. A exposição no fio é o risco já aceito; a
> persistência em access log do container foi eliminada no `frontend/nginx.conf` (formato
> `canal_sem_token`, que loga `$uri` em vez de `$request`). O resíduo que permanece é o de qualquer
> token de 1 ano em trânsito: revogação só por `is_active=False` da conta `agente`, o que desliga
> todo acesso de agente.**

Registre também, se quiser, a observação de que o `log_format` protege **este** proxy; um log
shipper centralizado na planta do cliente, ou um proxy corporativo à frente, ainda veria o token no
fio. Isso é consequência da forma aceita, não defeito novo.

### Passo 5: verificação de sintaxe — a receita que funciona

`nginx -t` em container **avulso** falha com `host not found in upstream "api"` — ver ARMADILHA Nº 2.
A receita correta anexa o container descartável à rede do compose, para `api` resolver. Isto **não
toca em nenhum serviço**: `--rm`, sem `-p`, sem `--name` fixo, sem restart.

```bash
docker run --rm --network ottima_default \
  -v "$PWD/frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:1.27-alpine nginx -t
```
Esperado: `nginx: the configuration file /etc/nginx/nginx.conf syntax is ok` e
`nginx: configuration file /etc/nginx/nginx.conf test is successful`.

**Antes de concluir que passou, rode a MESMA receita contra o arquivo original**, para ter certeza de
que o seu gate discrimina:
```bash
git show HEAD:frontend/nginx.conf > /tmp/nginx-original.conf
docker run --rm --network ottima_default \
  -v /tmp/nginx-original.conf:/etc/nginx/conf.d/default.conf:ro \
  nginx:1.27-alpine nginx -t
```
Ambos devem passar (a edição é aditiva). Se o **original passar e o seu falhar**, o erro é seu — leia
a mensagem, não force. Se **os dois falharem** com `host not found in upstream "api"`, a rede não é
`ottima_default`: descubra o nome real com `docker network ls` (leitura permitida) e repita. Registre
no relato qual dos dois cenários ocorreu — o advisor anterior perdeu tempo exatamente aqui.

Remova `/tmp/nginx-original.conf` ao final. **Não use `git checkout`, `git stash` nem `git reset`**
para obter o original; `git show` é leitura e não toca na sua árvore.

## Plano de teste

**Sem teste automatizado novo, deliberadamente.** Não existe harness de nginx no repo, e introduzir
um (testcontainers-nginx, ou um teste que suba o proxy) seria infraestrutura nova para validar quatro
diretivas — custo desproporcional, e o repo já decidiu manter validação de stack fora do CI
(ADR-035/TD-023).

A verificação é a do Passo 5 (sintaxe) mais os `grep` de contagem das tabelas, mais a conferência em
resposta real pelo **revisor**:

1. Reconstruir o container do frontend a partir da branch (runbook nos Passos 1-3 do plano 009):
   `docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --no-deps frontend`
2. `curl -sI http://localhost:8080/` → deve listar `Content-Security-Policy` **com**
   `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.
3. `curl -sI http://localhost:8080/index.html` → **os mesmos três**. Este é o passo que pega a
   ARMADILHA Nº 1; sem ele, um `add_header` só no `server{}` passaria despercebido.
4. `docker logs ottima-frontend-1 --tail 50` depois de abrir a SPA e forçar uma reconexão de WS →
   nenhuma linha contendo `token=`.

O revisor executa 1-4; o executor **não** (reconstruir o container do dono derruba a tela dele).

## Critérios de conclusão

Todos devem valer:

- [ ] `grep -cE '^ *log_format' frontend/nginx.conf` → `1`
- [ ] `awk '/location \/ws/,/^  }/' frontend/nginx.conf | grep -cE '^ +access_log'` → `1`
- [ ] `grep -c "frame-ancestors 'none'" frontend/nginx.conf` → `2`
- [ ] `grep -c 'X-Frame-Options' frontend/nginx.conf` → `2`
- [ ] `grep -c 'X-Content-Type-Options' frontend/nginx.conf` → `2`
- [ ] `grep -cE '^ +add_header' frontend/nginx.conf` → `7` (com âncora; sem ela conta comentários)
- [ ] `grep -cE '^ *limit_req_zone' frontend/nginx.conf` → `1` e `grep -c 'limit_req ' frontend/nginx.conf` → `1` (plano 003 intacto)
- [ ] `grep -c 'unsafe-inline' frontend/nginx.conf` → `2` (CSP existente preservada)
- [ ] `grep -c 'proxy_read_timeout 3600s' frontend/nginx.conf` → `1`
- [ ] `grep -c 'Strict-Transport-Security' frontend/nginx.conf` → `0` (HTTP interno, ADR-023)
- [ ] `git diff -- frontend/src packages services docs deploy` → **vazio** (só o nginx.conf mudou)
- [ ] `git diff --name-only` lista **só** `frontend/nginx.conf`
- [ ] A sintaxe foi validada pela receita do Passo 5, **comparando com o original**, e o resultado dos dois está no relato
- [ ] `/tmp/nginx-original.conf` foi removido
- [ ] **DOIS commits separados**, mensagens pt-BR
- [ ] A proposta de nota de ADR-036 está no relato (Passo 4), e `docs/` não foi editado
- [ ] Linha de status atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- O `frontend/nginx.conf` vivo não bater com os excertos de "Estado atual" (drift desde `37b0caa`) —
  em particular se alguém já tiver acrescentado `access_log`, `log_format` ou os cabeçalhos.
- O comentário de `:56-59` já não descrever a herança do `add_header`: significaria que o arquivo foi
  reestruturado e a ARMADILHA Nº 1 pode ter mudado de forma.
- O `location = /index.html` não existir mais.
- A sintaxe falhar **também no arquivo original** e `docker network ls` não mostrar rede do compose:
  relate, não force. Significa que o stack não está na configuração esperada.
- Você concluir que precisa mudar `canalPrimitivos.ts`, `confirmacao.py`, `config.py` (TTL) ou
  `api.ts` (localStorage): **não mude**. São as formas aceitas/documentadas; relatar é o caminho.
- Você concluir que precisa mexer em `deploy/docker-compose.yml` (driver de log, rotação): relate
  como sugestão. É mudança de deploy, não de proxy, e afeta os 8 serviços.
- Acrescentar `add_header` num location que não seja `server{}` ou `= /index.html`: **pare** — isso
  quebraria a herança dos outros locations, que é o que o comentário de `:59` garante.

## Notas de manutenção

- **O que interage com isto**: qualquer location novo que precise de `add_header`. Ao criá-lo, ele
  **cancela** a herança dos três cabeçalhos — tem de repeti-los. O comentário de `:56-59` é o aviso;
  mantenha-o atualizado se a lista de cabeçalhos crescer.
- **O que um revisor deve olhar no PR**: (1) os `grep` de contagem devolvendo **2** onde o plano pede
  2 — é isso que prova que a ARMADILHA Nº 1 foi respeitada; (2) `git diff` mostrando **só adição**,
  nenhuma diretiva existente removida ou reordenada; (3) os dois commits separados; (4) a receita do
  Passo 5 rodada contra original **e** editado, com os dois resultados no relato.
- **O que este plano NÃO fecha, e é bom que fique escrito**: o token continua viajando na query
  string (forma aceita, spec F3 §5.3 / ADR-023), continua tendo TTL de 1 ano (decisão documentada) e
  continua em `localStorage` (spec §8.5, com a CSP como mitigação). O que mudou é que ele **parou de
  ser gravado em disco pelo nosso proxy** e que a SPA **não pode mais ser emoldurada**. Qualquer
  afirmação de que "o problema do token foi resolvido" seria falsa.
- **Adiado de propósito**:
  - Rotação/limite do log do Docker (`json-file` sem `max-size` em `deploy/docker-compose.yml`). É
    higiene de deploy válida, mas afeta os 8 serviços e pertence a outro plano.
  - A nota na ADR-036 — proposta no Passo 4, aplicação pelo dono via processo do item 4.
  - Unificar os dois unions de estado de conexão (`EstadoConexao` em `useFlowStatus.ts:28` com
    `"aberta"` vs `EstadoConexaoCanal` em `CanalAoVivo.tsx:80` com `"aberto"`). Achado colateral
    desta auditoria, registrado no índice; sem relação com nginx, e transversal demais para entrar
    aqui.
