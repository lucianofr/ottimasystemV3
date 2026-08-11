# Revisão da spec F6 — contratos de API, validação, transação e schemas

**Spec:** docs/specs/F6-portabilidade-hardening.md @ da25cd6
**Veredito:** REQUEST CHANGES
**Achados:** 3 Critical, 4 Important, 3 Minor

## Achados

### API-01 — Reuso de `ConnectionCreate._coerencia` reprova todo bundle com `auth_mode: user_password` [Critical]

**Seção:** §2.1-1, §2.1-2

**Problema:** A spec vende o reuso de `ConnectionCreate._coerencia` como a "economia central" da camada 2: "policy×mode coerentes, watchdog em par, usuário/senha juntos... de graça, sem uma segunda cópia das mesmas regras" (§2.1-1). Mas `_coerencia` (`schemas/connections.py:30-41`) contém, na linha 35:

```python
if self.auth_mode == "user_password" and (not self.auth_username or not self.auth_password):
    raise ValueError("Autenticação usuário/senha exige usuário e senha")
```

O bundle nunca carrega `auth_password` — é segredo, excluído por tabela explícita em §2.3 ("`auth_password_enc` — re-informado no destino"). O próprio exemplo normativo do bundle em §2.1-2 tem `"auth_mode": "user_password"`, `"auth_username": "ottima"` e nenhum campo `auth_password`. Se a camada 2 chamar `ConnectionCreate(**entry)` literalmente sobre esse dicionário, `_coerencia` levanta `ValueError` e o import é recusado com 422 — para o **exemplo que a própria spec define como forma normativa**, e para qualquer bundle real com conexão segura por usuário/senha, que é exatamente o cenário que "re-informando segredos" (aceite da fase) precisa suportar.

**Evidência:** `schemas/connections.py:27` (`project_id: int`, sem default) e `:30-41` (`_coerencia`, condição da linha 35); bundle normativo em §2.1-2 do próprio arquivo da spec, sem `auth_password`.

**Consequência:** Todo import de projeto com pelo menos uma conexão `user_password` falha sempre, incondicionalmente, com 422 — não é um caso de borda, é o caminho principal do E2E-F6-02 (round-trip com "conexão segura"). O aceite da fase ("projeto exportado importa limpo... re-informando segredos") fica inatingível para esse tipo de conexão exatamente como a spec descreve a implementação.

**Correção sugerida:** A camada 2 não pode instanciar `ConnectionCreate` sobre o dicionário cru do bundle. Duas saídas concretas, escolher uma e escrevê-la na spec: (a) validar a entrada do bundle com um schema **derivado** que reafirma policy×mode e watchdog-em-par mas **não** exige `auth_password` (ex.: reusar `_ConnectionFields` + validação de coerência parcial, deixando de fora a regra de usuário/senha, que só faz sentido quando a senha é fornecida); ou (b) injetar um valor de senha sentinela não-persistido só para satisfazer o validador antes de descartá-lo, documentando isso explicitamente como parte do contrato de import. A opção (a) é mais limpa e não finge que a regra "usuário/senha juntos" foi verificada quando não foi. De qualquer forma, `_coerencia` não pode ser citada como reuso "de graça" enquanto a regra de senha permanecer ativa sobre um payload que nunca tem senha.

---

### API-02 — Todo `*Create` reusado na camada 2 exige o id do pai, que o bundle não carrega e que não existe antes do insert [Important]

**Seção:** §2.1-1, §3.2-4 (camada 2)

**Problema:** `ConnectionCreate.project_id: int` (`schemas/connections.py:27`), `TagCreate.connection_id: int` (`schemas/tags.py:15`) e `FlowCreate.project_id: int = Field(ge=1, le=MAX_BIGINT)` (`schemas/flows.py:18`) são campos obrigatórios sem default. O bundle exclui explicitamente `id`, `project_id` e `connection_id` (§2.3: "ids internos; substituídos por nome lógico"). Não há Project/Connection ainda gravados quando a camada 2 (forma) deveria rodar — por definição da própria tabela de camadas (§3.2-4), a camada 2 é "Pydantic, schemas Create reusados" e roda antes de qualquer coisa ser materializada. A spec não diz como a validação de forma de cada entidade filha recebe um `project_id`/`connection_id` válido nesse ponto.

**Evidência:** `schemas/connections.py:27`, `schemas/tags.py:15`, `schemas/flows.py:18`; tabela §2.3 excluindo esses três campos do bundle.

**Consequência:** Sem essa peça, dois implementadores resolvem de formas incompatíveis: um usa um placeholder (`project_id=0`) só para passar pela validação de tipo e depois ignora o valor; outro decide inverter a ordem e gravar o pai primeiro, então validar a forma do filho já com o id real — o que muda a ordem das camadas descrita em §3.2-4 (forma deixa de ser 100% pré-escrita). Sem essa decisão escrita, o comportamento do import diante de um bundle malformado (ex.: `project_id` de tipo errado dentro do bundle, que não deveria nem existir) é imprevisível.

**Correção sugerida:** Documentar explicitamente que a camada 2 usa placeholders inertes (`project_id=0`, `connection_id=0`) apenas para satisfazer a tipagem do schema, e que o valor nunca é lido de volta do objeto validado — o insert real usa o id do pai obtido no flush anterior. Isso mantém "camada 2 pura de forma, antes de qualquer escrita" como está implícito em §3.2-4.

---

### API-03 — `Flow.desired_state` do bundle não passa por nenhum schema Pydantic; só o CHECK do banco o protege [Critical]

**Seção:** §2.1-2, §2.1-4, §3.2-4 (camada 2/4)

**Problema:** O bundle exporta `desired_state` verbatim em cada flow (§2.1-2 exemplo, §2.1-4). Mas `FlowCreate` — o schema que §2.1-1 diz ser reusado "menos os segredos e menos os ids" — **não tem campo `desired_state`**:

```python
class FlowCreate(BaseModel):
    project_id: int = Field(ge=1, le=MAX_BIGINT)
    name: str = Field(min_length=1)
    ts_seconds: TsSeconds
```

(`schemas/flows.py:17-20`). Não existe também em `FlowUpdate` nem em nenhum outro schema de escrita — o único lugar do código onde `desired_state` é atribuído a partir de uma string vinda de fora é `routers/flows.py:240,249` (`_comandar`), e ali o valor é sempre um literal fixo (`"running"`/`"stopped"`) passado pelos próprios `deploy_flow`/`stop_flow`, nunca texto de cliente. A única barreira contra um `desired_state` inválido no banco é o CHECK `ck_flows_desired_state` (`models/flow.py:40`: `desired_state IN ('running','stopped')`).

**Evidência:** `schemas/flows.py:17-20` (ausência do campo); `models/flow.py:30-32,40` (coluna e CHECK); `routers/flows.py:240,249` (único setter existente, sem validação de valor).

**Consequência:** Se a camada 2 não inventar uma checagem extra para `desired_state` (o que contraria a premissa "reusa os schemas Create, sem segunda cópia das regras" de §2.1-1, já que essa checagem não está em nenhum Create), um bundle com `"desired_state": "rodando"` (erro de digitação, versão antiga, edição manual) só falha no `flush()` do Flow, como violação do CHECK constraint — um `IntegrityError` do driver. Nenhum dos handlers de import mostrados na spec prevê captura desse `IntegrityError` especificamente (o único padrão de captura existente no repo, em `create_project`/`create_connection`/`create_flow`, é genérico e assume que qualquer `IntegrityError` é colisão de nome, respondendo 409 com a mensagem errada). Sem captura dedicada, a exceção sobe crua e vira 500 — exatamente o cenário que o axis 1 desta revisão pergunta, e que o aceite da fase (transação limpa, sempre 422 agregado) promete não acontecer.

**Correção sugerida:** Adicionar `desired_state: DesiredState` (o mesmo `Literal["running","stopped"]` de `schemas/flows.py:12`) como checagem explícita da camada 2 para a entidade Flow do bundle — via um schema de import dedicado (`FlowImport(FlowCreate)` acrescentando o campo, ou uma validação de camada 2 que list as regras extras por entidade). Registrar isso na tabela de §3.2-4 para que não fique implícito.

---

### API-04 — `GET /api/health` da API não herda o mecanismo de heartbeat dos outros três serviços; a spec só especifica o formato JSON [Critical]

**Seção:** §3.3

**Problema:** Nos três outros serviços, `redis_ok`/`db_ok` **não** são calculados dentro do handler `/health` — são estado já computado por um `_heartbeat_loop` em background, que roda `client.ping()`/`SELECT 1` a cada `HEARTBEAT_INTERVAL_S` segundos e grava em `app.state.redis_ok`/`app.state.db_ok` com captura ampla de exceção:

```python
# opc-worker/main.py:33-49 (idêntico em flow-runtime e recorder)
async def check_redis(client, app): ...
    app.state.redis_ok = True/False
async def check_database(session_factory, app): ...
    app.state.db_ok = True/False
async def _heartbeat_loop(client, session_factory, app):
    while True:
        await check_redis(...); ...
```

O handler `/health` em si é só leitura: `redis_ok = getattr(app.state, "redis_ok", False)` (`opc-worker/main.py:115`, `flow-runtime/main.py:136`, `recorder/main.py:72`) — **zero I/O por requisição**.

A `api` (`ottima_api/app.py`, `lifespan`, linhas 63-79 lidas nesta revisão) não tem nenhum `_heartbeat_loop`, nenhum `check_redis`/`check_database`, e nenhuma inicialização de `app.state.redis_ok`/`db_ok`. A spec (§3.3-1/2) diz apenas: "os outros três serviços derivam `status` de `redis_ok and db_ok`... [a api] passa a devolver {status, service, version, redis_ok, db_ok}, sempre 200 — mesmo contrato dos outros três". Isso especifica o **formato JSON**, não o **mecanismo de coleta**.

**Evidência:** `services/opc-worker/src/ottima_opc_worker/main.py:33-49,108-119`; `services/flow-runtime/src/ottima_flow_runtime/main.py:44-60,136-140`; `services/recorder/src/ottima_recorder/main.py:25-30,71-77` (mecanismo de heartbeat em background); `services/api/src/ottima_api/app.py:63-79` (lifespan da api, sem equivalente); `services/api/src/ottima_api/routers/health.py:17-19` (handler atual, fixo).

**Consequência:** `/api/health` é rota pública, sem autenticação, é o healthcheck do `docker-compose.yml:43-48` e é consultada pelo smoke L1 — precisa responder rápido e nunca travar. Se a implementação seguir só a frase literal da spec ("consulta Redis/Postgres e devolve redis_ok/db_ok") sem replicar o mecanismo de heartbeat em background, o caminho óbvio é fazer `await redis_client.ping()` e `await db.execute(text("SELECT 1"))` **dentro do próprio handler**, a cada requisição, sem timeout explícito — ao contrário de `_fetch_worker_health` (`health.py:20-30`), que já usa `timeout=1` para o mesmo tipo de checagem dependente de rede. Com Postgres ou Redis lentos/travados, cada chamada a `/api/health` trava junto, exatamente na hora em que o operador mais precisa que o healthcheck responda rápido para diferenciar "api viva, dependência fora" de "api travada". Isso é RNF-07, entrega literal da F6 (aceite da fase).

**Correção sugerida:** Espelhar literalmente o padrão dos três serviços: adicionar `check_redis`/`check_db` + `_heartbeat_loop` ao `lifespan` de `ottima_api/app.py`, inicializando `app.state.redis_ok`/`db_ok` e atualizando-os periodicamente; `routers/health.py:health()` passa a fazer só `getattr`, sem nenhum I/O de rede/banco por requisição. Registrar isso explicitamente na spec (hoje só a forma do JSON está descrita).

---

### API-05 — Ordem camada 3 / camada 4 para `tag_ref`: a spec descreve a tradução como pós-flush mas classifica a falha como camada 3; os modelos de `parse.py` não aceitam `tag_ref` [Important]

**Seção:** §2.2-3/4/5, §3.2-4

**Problema:** Dois pontos concretos:

1. `TagConfig` (`flowgraph/parse.py:49-51`) é `model_config = ConfigDict(extra="forbid")` com `tag_id: int` obrigatório; `PidBinding` (`mpc_config.py:58-68`, conforme a própria spec cita) tem `write_tag_id: int` etc., também tipados como inteiro. Isso significa que `parse_graph`/`validate_graph` — "o mesmo validador que o editor e o deploy usam, sem segunda implementação" (§3.2-4 item 4) — **não aceita** um `graph` no formato do bundle (com objetos `tag_ref`) sem uma reescrita prévia que troque os seis campos `tag_ref`→`tag_id`. Essa reescrita não está atribuída a nenhuma camada na tabela de §3.2-4: não é "forma" (camada 2, que não conhece o grafo), não é claramente "referências" (camada 3, que a spec define como comparação bundle-interno) e tecnicamente precisa acontecer **entre** o flush() e a chamada a `parse_graph`.
2. §2.2-5 diz textualmente: "`tag_ref` → busca no mapa `{(connection_name, tag_name): novo_id}` construído **após o flush()** das tags na mesma transação → `tag_id`. Referência órfã é erro de **camada 3**." Isso descreve o lookup como acontecendo depois do flush (ou seja, depois que Connections e Tags já foram inseridas, ainda que não commitadas) mas rotula uma falha ali como pertencente à camada 3 — que, pela tabela de §3.2-4, é a camada que roda **antes** da 4, e a 4 é quem "já tem o mapa de tags materializado pelo flush()". As duas descrições não fecham: se a checagem de órfão só é feita no mapa pós-flush, ela não pode "rodar antes" da etapa que faz o flush.

**Evidência:** `flowgraph/parse.py:49-51` (`TagConfig`, `extra="forbid"`, `tag_id: int`); `flowgraph/mpc_config.py:58-68` (citado também pela própria spec); §2.2-5 e §3.2-4 do documento revisado.

**Consequência:** Sem uma ordem explícita, dois implementadores decidem coisas diferentes: um faz a checagem de "tag_ref não casa com nenhuma tag do bundle" **puramente em memória**, comparando o bundle contra ele mesmo (nomes de conexão/tag declarados vs. referenciados), antes de qualquer insert — o que é possível e mais seguro, porque não depende do banco. Outro segue a letra de §2.2-5 e só descobre a referência órfã depois de já ter inserido Connections/Tags (na mesma transação, sem commit) — nesse caminho, se a checagem de nome duplicado (a outra metade da camada 3, "nome duplicado dentro do próprio bundle") também for adiada para esse mesmo ponto em vez de ser feita em memória primeiro, um bundle com duas conexões de mesmo nome dispara `IntegrityError` em `uq_opc_connections_project_name` no flush — e, se capturado pelo mesmo `except IntegrityError` genérico usado em `create_connection` (`routers/connections.py:~180`), o import responderia **409** com "Nome de conexão já em uso" em vez do 422 agregado que §3.2-4/§3.2-5 prometem para esse tipo de problema (a spec reserva 409 exclusivamente para nome de **projeto** duplicado, §3.2-6).

**Correção sugerida:** Fixar na spec que a checagem de "tag_ref casa com alguma tag do bundle" e "nome duplicado dentro do bundle" (as duas metades de camada 3 que não dependem de id real) rodam **inteiramente em memória, contra o próprio bundle, antes de qualquer `db.add()`**. Só depois disso — com camada 3 já aprovada — a transação insere Project/Connections/Tags, dá flush, e usa o mapa resultante **apenas para traduzir** (não para validar existência, que já foi provada) tag_ref→tag_id antes de reescrever o `graph_json` e chamar `parse_graph`/`validate_graph` (camada 4). Isso elimina a dependência circular e garante que nenhum `IntegrityError` de unicidade escapa da camada 3.

---

### API-06 — Teto de 4 MiB não é aplicável a um corpo JSON tipado sem abrir mão da amarração automática do FastAPI [Important]

**Seção:** §3.2-1

**Problema:** O precedente citado pela própria spec (`_ler_certificado`, `connections.py:42` e a função em si) só funciona porque o endpoint de certificado recebe o corpo como **bytes crus via `Request.stream()`**, nunca como parâmetro Pydantic tipado — o próprio docstring da função explica por quê: `await request.body()` "bufferiza o corpo inteiro ANTES de qualquer comparação". Todo outro endpoint de escrita do router (`ConnectionCreate`, `FlowCreate`, `ProjectCreate` etc.) usa um parâmetro tipado (`body: ConnectionCreate`), que é exatamente o padrão `await request.body()` internamente — o FastAPI lê e desserializa o corpo inteiro antes do handler rodar, e antes de qualquer código de aplicação ter chance de medir o tamanho.

**Evidência:** `routers/connections.py` (`_ler_certificado`, docstring citando a bufferização de `request.body()`); `routers/connections.py:42` (`MAX_SERVER_CERT_BYTES`); todos os outros endpoints do router usando `body: XCreate` como parâmetro tipado.

**Consequência:** Para impor os 4 MiB **antes de materializar o corpo**, o endpoint de import precisa abandonar o padrão `body: ImportRequest` usado em todo o resto do router e replicar o padrão de `_ler_certificado` (receber `request: Request` cru, ler em streaming com corte no primeiro chunk que ultrapassa o teto, só então fazer `json.loads` + validação manual). Isso tem duas consequências que a spec não menciona: (1) o corpo de `POST /api/projects/import` deixa de aparecer documentado no `openapi.json` gerado (o mesmo efeito que `certificates.py:70-80` já produz do lado da resposta, ver API-10) — o `npm run generate:api` do frontend perde a tipagem exatamente do endpoint com o payload mais complexo da fase; (2) se a implementação optar por manter `body: ImportRequest` tipado (mais simples, consistente com o resto do router) e só checar `Content-Length` como faz `_excede_o_declarado`, um cliente com corpo *chunked* ou `Content-Length` mentindo baixo já terá o corpo inteiro materializado em memória antes do 413 sair — a mesma falha que o docstring de `_ler_certificado` describe como inaceitável para 64 KiB, aqui potencialmente sobre um payload N vezes maior.

**Correção sugerida:** Decidir e escrever qual dos dois caminhos vale: (a) endpoint sem `response_model`/`body` tipado, streaming manual como `_ler_certificado`, teto garantido antes da materialização, custo de perder o corpo documentado no OpenAPI; ou (b) `body: ImportRequest` tipado, teto garantido só por `Content-Length` (best-effort, não impermeável a cliente adversarial), documentado como limitação aceita porque o endpoint é admin-only. Qualquer um dos dois é aceitável; o que não é aceitável é a spec atual, que cita o precedente errado (bytes crus) para justificar uma garantia que só vale para o padrão que o import não vai poder usar se quiser continuar com `body` tipado.

---

### API-07 — Predicado de `pending_secrets` (§3.2-7) não é o mesmo de §6.3-1, apesar da spec afirmar que é [Important]

**Seção:** §3.2-7, §6.3-1

**Problema:** §3.2-7 define: `needs_password := auth_mode == "user_password"`, `needs_server_certificate := security_policy != "none"`, e afirma: "É o mesmo predicado que a página de Conexões avalia continuamente (§6.3)". Mas §6.3-1 define o predicado da página de Conexões como:

- "falta senha ⇔ `auth_mode == "user_password" && !has_password`"
- "falta certificado confiado ⇔ `security_policy != "none" && !server_cert_file`"

As fórmulas de §3.2-7 **omitem** o termo `&& !has_password` / `&& !server_cert_file` que §6.3-1 tem. No instante exato do import elas coincidem (uma conexão recém-importada sempre tem `has_password=false` e `server_cert_file=null`, porque o bundle nunca carrega esses dois campos — §2.3), mas são fórmulas diferentes.

**Evidência:** Citação verbatim de §3.2-7 e §6.3-1 do documento revisado; `schemas/connections.py` mostra `has_password: bool` e `server_cert_file: str | None` como campos existentes de `ConnectionOut` usados por §6.3-1.

**Consequência:** A própria spec convida ao reuso ("a mesma verdade, calculada no mesmo lugar conceitual" — §3.2-7). Se um implementador extrair essa lógica para uma função única e reusá-la tanto no resumo do import quanto na coluna "Pendências" de Conexões (exatamente como a spec sugere), usando a fórmula de §3.2-7 (sem o termo de "já resolvido"), a pendência de senha/certificado nunca mais desaparece da tela depois que o engenheiro resolve — porque a fórmula reduzida não olha se o segredo já foi informado. É "duas verdades para a mesma coisa" com uma delas incompleta.

**Correção sugerida:** Corrigir §3.2-7 para a fórmula completa de §6.3-1 (`needs_password := auth_mode == "user_password" and not has_password`, `needs_server_certificate := security_policy != "none" and not server_cert_file`) — no import, os dois termos adicionais são sempre verdadeiros por construção, então o resultado não muda para o caso do import, mas a função fica correta se reusada em qualquer outro contexto.

---

### API-08 — Kind novo `project_imported` não é adicionado ao vocabulário de `bus.py` [Minor]

**Seção:** §3.2-8

**Problema:** `ottima_core/bus.py` documenta o vocabulário de `kind` do canal `events` como uma lista de constantes `KIND_X = "x"`, agrupadas por fase em comentários (`# Vocabulário kind novo da F3`, `... do MPC`, `... da F5`). `kind` em si é tipado só como `str` em `publish_event` (sem `Literal`/enum reforçado em runtime) — nada quebra tecnicamente se o import emitir `kind="project_imported"` como string solta. Mas a spec (§3.2-8) não menciona adicionar `KIND_PROJECT_IMPORTED = "project_imported"` a essa lista, quebrando a convenção que toda fase anterior seguiu sem exceção.

**Evidência:** `packages/ottima-core/src/ottima_core/bus.py` (lista de `KIND_*` com banners por fase; `publish_event(kind: str, ...)` sem `Literal`).

**Consequência:** Nenhuma quebra funcional; perda de rastreabilidade/greppabilidade — o próximo engenheiro que procurar "quais kinds existem" por `grep KIND_` em `bus.py` não encontra `project_imported`.

**Correção sugerida:** Adicionar `KIND_PROJECT_IMPORTED = "project_imported"` sob um banner `# Vocabulário kind novo da F6` em `bus.py`, e citar esse arquivo/linha em §3.2-8 como os outros itens do §1.1 já fazem.

---

### API-09 — Dois formatos concorrentes para agregar múltiplos erros de domínio em uma string [Minor]

**Seção:** §3.2-5

**Problema:** `routers/flows.py` já tem uma convenção para juntar várias reprovações de grafo em um único `detail`: `SEPARADOR_REPROVACOES = " | "`, com o comentário explícito de que foi escolhido para não colidir com o "; " que as próprias mensagens do flowgraph já usam. A spec F6 introduz um segundo formato para o mesmo problema (agregar N erros em um `detail`): `"Import recusado (N problemas): msg1; msg2; ...; e mais N"`, com "; " como separador entre mensagens.

**Evidência:** `routers/flows.py` (`SEPARADOR_REPROVACOES = " | "`, comentário sobre a escolha do separador); §3.2-5 do documento revisado (formato novo com "; ").

**Consequência:** Nenhuma quebra técnica — são endpoints diferentes, cada `detail` é renderizado isoladamente na UI. Mas são duas convenções visuais distintas para "vários problemas em uma string" convivendo no mesmo produto, o que um engenheiro lendo os dois trechos de código vai estranhar sem saber se é intencional.

**Correção sugerida:** Não é bloqueante; registrar na spec que o formato de §3.2-5 é deliberadamente diferente do de `flows.py` porque precisa do contador/teto que `SEPARADOR_REPROVACOES` não tem, para que a divergência não pareça descuido em code review.

---

### API-10 — `GET /export` com `Response` cru funciona no `generate:api`, mas gera tipo enganoso no OpenAPI [Minor]

**Seção:** §3.1-2

**Problema:** Confirmado por evidência direta: `export_app_cert` (`certificates.py:70-80`) devolve `Response(content=..., media_type="application/pkix-cert", headers={"Content-Disposition": ...})` sem `response_model`. O `openapi.json` gerado documenta essa rota como devolvendo `content: {"application/json": unknown}` (verificado em `frontend/src/lib/api-types.ts:2543-2564`, operação `export_app_cert_api_certificates_app_export_get`) — o tipo gerado mente sobre o `Content-Type` real. Isso **não quebra** `npm run generate:api` (o precedente já roda em produção), mas é uma armadilha: qualquer código novo que use o cliente tipado do `openapi-fetch` para consumir essa resposta esperando JSON vai falhar silenciosamente ou precisar de cast manual.

**Evidência:** `services/api/src/ottima_api/routers/certificates.py:70-80`; `frontend/src/lib/api-types.ts:2543-2564` (tipo gerado real, `content: {"application/json": unknown}` para uma resposta `application/pkix-cert`).

**Consequência:** Nenhuma para o backend. Para `GET /api/projects/{id}/export` (que a spec manda seguir "mesmo padrão"), o consumo no frontend (§6.1-5, "dispara `GET /api/projects/{id}/export` e salva o arquivo pelo `Content-Disposition`") precisa ser feito por `fetch` cru + `.blob()`, nunca pelo cliente tipado gerado — a spec não escreve essa restrição explicitamente, e fica implícita só porque o precedente de certificado já existe.

**Correção sugerida:** Nenhuma mudança de código necessária; adicionar uma frase em §3.1-2 dizendo que o consumo no frontend é por `fetch` bruto (como o download do certificado já faz), não pelo cliente OpenAPI tipado, para que a UI de exportação (§6.1-5) não tente usá-lo por engano.

---

## Verificações positivas

- **`flush()` com `BigInteger Identity` funciona como a spec descreve.** SQLAlchemy 2.0 async + asyncpg (`ottima_core/db.py`: `create_async_engine`, `async_sessionmaker(..., expire_on_commit=False)`) usa `INSERT ... RETURNING` para popular a PK `Identity` no objeto Python logo após `flush()`, sem precisar de `commit()`. O padrão "insere pai, flush, insere filhos com o id do pai, flush, valida, comita ou dá rollback" é tecnicamente sólido nesta stack.
- **`project_tags()` (`ottima_core/tags.py`) é diretamente reusável pela camada 4 do import.** A consulta enxerga as linhas de `Tag` já inseridas (flush, sem commit) na mesma sessão/transação — visibilidade MVCC padrão do Postgres para a própria transação. Não há problema técnico em reusar essa função tal como está.
- **`TagCreate.direction`/`data_type`, `FlowCreate.ts_seconds` e os `Literal` de `ConnectionCreate` (`security_policy`, `security_mode`, `auth_mode`) cobrem 100% do domínio dos respectivos `CHECK` constraints** (`ck_tags_direction`, `ck_tags_data_type`, `ck_flows_ts`, `ck_opc_connections_policy/mode/auth`). Não há risco de reprovação de banco escapando da camada 2 para esses campos especificamente — o único escape concreto encontrado foi `desired_state` (API-03).
- **O contrato de erro global não colide com o `detail` agregado do import.** `app.py:19-67` registra `_validation_exception_handler` só para `RequestValidationError` (validação automática do FastAPI sobre um `body` tipado). Um `HTTPException(422, detail=<string agregada>)` levantado manualmente no router **não passa** por esse handler — cai no tratamento default do FastAPI para `HTTPException`, que já devolve `{"detail": ...}` como string. Não há conflito de formato.
- **RBAC de export/import está correto.** PRD §2, linha 32: "Export/import de projeto; gestão de usuários | admin ✅ | operador ❌" — `require_admin` nas duas rotas (§3.1-1, §3.2 header) é exatamente o que o PRD manda, sem ambiguidade.
- **`docstring`/precedente de `_ler_certificado` está corretamente descrito pela spec como base para o teto de tamanho** — a técnica (contagem de bytes em streaming, corte no primeiro chunk que ultrapassa o teto) é sólida; o problema identificado em API-06 é só sobre a incompatibilidade dela com um `body` Pydantic tipado, não sobre a técnica em si.
