# Revisão da spec F6 — verificação factual de âncoras de código

**Spec:** `docs/specs/F6-portabilidade-hardening.md` @ `da25cd6`
**Facet:** verificação factual de TODA afirmação de código (prefixo `FACT`)
**Veredito:** REQUEST CHANGES
**Achados:** 1 Critical, 4 Important, 8 Minor

> Materializado pelo agente coordenador: o subagente `scout` que produziu esta revisão não dispõe de ferramenta de escrita em disco. Conteúdo integral conforme entregue.

75 âncoras/afirmações de código foram extraídas da spec e verificadas uma a uma contra o repositório (branch `main`), sem amostragem.

## Tabela completa de verificação

| Ancora na spec | Secao | Veredito | Linha/fato correto |
|---|---|---|---|
| `routers/certificates.py:39-80` | §1 | OK | 39=/app/generate, 55=/app, 70-80=/app/export |
| `routers/connections.py:250-323` | §1 | OK | 250=POST server-certificate, 301-323=DELETE (EOF=323) |
| `ottima_core/certs.py` | §1 | OK | existe, contém toda lógica X.509 |
| `tests/e2e/test_f4_failure.py:1-7` | §1 | OK | docstring confirma config próprio, sem grafo_mpc_tfs |
| `tests/e2e/test_f4_ws.py:1-6` | §1 | OK | docstring confirma grafo próprio, sem grafo_mpc_tfs |
| `features/connections/useConnections.ts:14-20` | §1 | OK | exato — useActiveProject() completo |
| `ConnectionsPage.tsx:177` | §1 | OK | exato |
| `FlowsPage.tsx:294` | §1 | OK | exato |
| `TagsPage.tsx:54` | §1 | OK | exato |
| `OperateSelectorPage.tsx:48` | §1 | FALSA | ver FACT-01 |
| `flowgraph/parse.py:46-51` (TagConfig/tag_id) | §2.2-1 | OK | exato |
| `flowgraph/parse.py:19-25` (_CONFIG_KEYS) | §2.2-1/§4.1-3/§9.1 | OK | exato |
| `flowgraph/mpc_config.py:58-68` (PidBinding, 4 campos) | §2.2-1 | OK | exato — classe 58-68, campos em 63/65/66/67 |
| `opc-worker/security.py:115-125` (cert_mismatch) | §2.3 | OK | ramo cert_mismatch de map_connect_exception |
| `routers/certificates.py:76-80` (dup.) | §3.1-2 | OK | confirmado |
| `flows.py:55` (constante 404 a reusar) | §3.1-3 | FALSA | ver FACT-02 |
| `connections.py:42` (MAX_SERVER_CERT_BYTES) | §3.2-1 | OK | exato |
| `projects.py:77-108` (activate_project) | §3.2-3 | DESLOCADA | função vai até 112, não 108 |
| `app.py:60-67` (contrato de erro) | §3.2-5 | OK | função 59-68, núcleo em 60-67 |
| `projects.py:38-41` (409 create_project) | §3.2-6 | OK linha / ver FACT-13 | duplicado também em :62, não é constante nomeada |
| `connections.py:240-247` (auditoria) | §3.2-8 | OK | exato |
| `routers/health.py:17-19` (status fixo) | §3.3-1 | OK | exato |
| `opc-worker/main.py:108-135` | §3.3-1 | DESLOCADA | função termina em 128 |
| `flow-runtime/main.py:129-160` | §3.3-1 | OK linha / FALSA conteúdo | ver FACT-10 |
| `recorder/main.py:67-86` | §3.3-1 | OK | exato |
| `docker-compose.yml:43-48` | §3.3-3 | DESLOCADA | healthcheck real está em 46-51 |
| `models/tag.py:29` (eu) | §4.1-1 | DESLOCADA | eu está na linha 30 |
| `flowgraph/validate.py:99-111` (OUT1..OUTn/y1/y2) | §4.1-3 | OK | confirmado |
| `ottima_core/contracts_export.py` | §4.1-6 | OK | existe, fonte de contracts.gen.ts |
| `flowgraph/mpc_config.py:128-135` (DvVar) | §4.2-1 | OK | exato |
| `mpc_config.py:39-46` (Range) | §4.2-2 | OK | classe em 40, campos até 46 |
| `blocks/mpc.py:453-463` (mpc_overrun payload={}) | §5.1 | OK | exato — 453=def, 463=fecha chamada |
| `supervisor.py:172` (_lock) | §5.2-1 | OK | exato |
| `supervisor.py:259/477/494/517` (4 tomadas do lock) | §5.2-1 | OK | todas exatas |
| `supervisor_mpc.py:417` (shutdown_mpc) | §5.2-1 | OK | exato |
| `supervisor.py:338/548/597` (3 chamadores) | §5.2-1 | OK | todas exatas |
| `supervisor.py:643` (_teardown chama shutdown_mpc) | §5.2-1 | OK | exato |
| `supervisor.py:219-222` (stop chama _teardown) | §5.2-1 | OK | exato |
| `supervisor.py:644-649` (espera mpc_stop_tasks) | §5.2-1 | OK | exato |
| `supervisor_mpc.py:395` (revert_armed_mpc) | §5.2-2 | OK | não chama host.stop() |
| `supervisor_mpc.py:359` (stop_host_background) | §5.2-2 | linha OK / FALSA conteúdo | ver FACT-03 (Critical) |
| `supervisor.py:558/563` (_reconcile_flow) | §5.2-1 | OK | exatas |
| `app/router.tsx` | §6.1-1 | OK | rotas atuais conferem |
| `projects.py:67-75` (409 excluir ativo) | §6.1-3 | OK | função 67-74 |
| `schemas/certificates.py:8-14` (AppCertificateOut) | §6.2-1 | OK | exato |
| `certificates.py:28-31,52` (warning re-trust) | §6.2-1 | OK | exato, inclusive linha 52 |
| `certificates.py:33-36` (_MSG_ILEGIVEL) | §6.2-1 | OK | exato |
| `connections.py:292-298` (fingerprint) | §6.2-2 | OK | confirmado |
| `connections.py:259-263` (content-types) | §6.2-3 | OK | confirmado |
| ausência de type=file/multipart real | §6.2-3 | OK | zero ocorrências reais |
| uso de FormData só leitura de form | §6.2-3 | OK | confirmado |
| `schemas/connections.py:20,65` | §6.3-1 | OK | exato |
| `schemas/connections.py:30-41` (_coerencia) | §2.1-1 | OK | exato, 30=decorator, 41=return self |
| `tests/e2e/conftest.py:612-683` (grafo_mpc_tfs) | §7.2-2 | OK | função 612-681, único construtor com tfs |
| `test_f4_mpc.py:309/398` (E2E-F4-03/05) | §7.2-2 | OK | exatas, linha da própria def |
| `test_f4_failure.py:159` (E2E-F4-06) | §7.2-2 | OK | exata |
| `test_f4_ws.py:210` (E2E-F4-10) | §7.2-2 | OK | exata |
| `test_f4_failure.py:166` (solve consistente) | §7.2-4 | OK | citação verbatim confere |
| `test_scheduler.py:35-84` / `test_mpc_block.py:156-165` (FakeClock) | §7.2-5 | OK | interfaces incompatíveis confirmadas |
| `tests/e2e/conftest.py:14-16` (proibição up/down) | §1.2 | DESLOCADA | texto real está em 4-6 |
| `ottima_core/logging.py:9-22` (campo service) | §1.2 | FALSA | ver FACT-11 |
| `deploy/.env.example:18,21` | §8-1 | 18 OK / 21 DESLOCADA | FERNET_KEY está em 22 |
| `ottima_core/certs.py:34` (APPLICATION_URI) | §8-2 | OK | exato |
| `models/tag.py:33` (UniqueConstraint) | §2.1-5 | DESLOCADA | constraint está na linha 34 |
| seis campos de tag_ref, varredura por 7º | §2.2-1 | OK | nenhum 7º campo encontrado |
| auth_password_enc único segredo | §2.3 | OK | confirmado |
| orfãos Project/Connection/Tag/Flow | §2.1/§2.3 | OK | nenhum campo órfão |
| User não é filho de Project | §2.3 | OK | confirmado |

## Achados

### FACT-01 — OperateSelectorPage.tsx:48 não contém a mensagem citada [Important]

**Seção:** §1 e §6.1-7.
**Problema:** a spec afirma que quatro telas exibem "Nenhum projeto ativo: ative um projeto para…", citando `ConnectionsPage.tsx:177`, `FlowsPage.tsx:294`, `TagsPage.tsx:54` e `OperateSelectorPage.tsx:48`. As três primeiras conferem exatamente; a quarta não — linha 48 contém "Nenhum bloco MPC configurado no projeto ativo.", que aparece igual COM projeto ativo sem MPC configurado. Essa tela não distingue hoje "sem projeto ativo" de "projeto ativo sem MPC".
**Evidência:** `frontend/src/features/operate/OperateSelectorPage.tsx:46-49`.
**Consequência:** §6.1-7 pede link para `/engenharia/projetos` nas "quatro telas"; para a quarta isso exige lógica NOVA (checar `useActiveProject()===null`), não apenas trocar uma string existente — a spec não sinaliza esse trabalho extra.
**Correção:** corrigir §1 para "três telas" com os anchors certos, e adicionar nota em §6.1-7 de que `OperateSelectorPage` precisa de condição nova.

### FACT-02 — flows.py:55 é a constante errada para "projeto inexistente" [Important]

**Seção:** §3.1-3.
**Problema:** a spec manda reusar a "constante única com `flows.py:55`" para o 404 de projeto inexistente no export. `flows.py:55` usa `MSG_FLOW_NAO_ENCONTRADO="Flow não encontrado"` (definida em `messages.py:3`) — mensagem de outra entidade.
**Evidência:** `ottima_api/routers/flows.py:14,55`; `ottima_api/messages.py:3`.
**Consequência:** implementado ao pé da letra, o export de projeto inexistente responderia "Flow não encontrado". Além disso a mensagem certa ("Projeto não encontrado") não é constante nomeada — é literal duplicado em `projects.py:21` e `flows.py:134`.
**Correção:** trocar anchor para `projects.py:21`; considerar extrair `MSG_PROJETO_NAO_ENCONTRADO` para `messages.py`.

### FACT-03 — stop_host_background não remove o host do mapa [Critical]

**Seção:** §5.2-2.
**Problema:** a spec atribui a `stop_host_background` (`supervisor_mpc.py:359`) a ação de "remove o host do mapa e destaca o desmonte". Falso: só cria/registra a task de fundo. Quem remove do mapa é `detach_hosts` (`supervisor_mpc.py:347`), função separada — o próprio docstring de `stop_host_background` documenta que o host "já saiu do mapa (`detach_hosts`, responsabilidade de quem chama esta função, ANTES desta task nascer)".
**Evidência:** `supervisor_mpc.py:347-357` (`detach_hosts`) e `:359-393` (`stop_host_background`, nunca toca `runtime.hosts`); padrão correto já usado em `supervisor.py:352-353` dentro de `_stop`.
**Consequência:** a spec descreve a substituição normativa como só dois passos (`revert_armed_mpc` + `stop_host_background`), omitindo `detach_hosts`. Um implementador fiel ao texto deixaria o host antigo alcançável em `runtime.hosts` durante toda a janela de desmonte (até `_BOOT_TIMEOUT_S=30s`), abrindo espaço para um comando concorrente operar sobre um host em processo de morte — violação da invariante "nunca dois workers escrevendo na mesma malha" que a própria spec declara normativa. Risco de escrita indevida em planta.
**Correção:** reescrever §5.2-2 como sequência de três passos: `revert_armed_mpc` → `detach_hosts` (síncrono, sob o lock) → `stop_host_background`; mover o crédito de "remove do mapa" para `detach_hosts:347`.

### FACT-04 — projects.py:77-108 corta a função 4 linhas antes do fim [Minor]

`activate_project` vai até a linha 112 (`return project`), não 108. Trocar para `projects.py:77-112`.

### FACT-05 — opc-worker/main.py:108-135 estende 7 linhas além do fim [Minor]

`health()` termina em 128. Trocar para `opc-worker/main.py:108-128`.

### FACT-06 — docker-compose.yml:43-48 aponta para depends_on, não healthcheck [Minor]

O healthcheck do serviço `api` está em 46-51; 43-45 é o fim do bloco `depends_on`. Trocar para `docker-compose.yml:46-51`.

### FACT-07 — models/tag.py:29 não é o campo eu [Minor]

Linha 29 é `data_type`; `eu` está em 30. Trocar para `models/tag.py:30`.

### FACT-08 — models/tag.py:33 não é o UniqueConstraint [Minor]

Linha 33 é `__table_args__ = (`; o `UniqueConstraint` está em 34. Mesmo padrão de deslocamento de 1 linha do FACT-07 no mesmo arquivo — sugere viés sistemático na fonte das âncoras deste arquivo. Trocar para `models/tag.py:34`.

### FACT-09 — .env.example:21 não é OTTIMA_FERNET_KEY [Minor]

Linha 21 é comentário de como gerar a chave; a atribuição está em 22. Trocar para `.env.example:18,22`.

### FACT-10 — "os outros três… redis_ok and db_ok" é impreciso para o flow-runtime [Important]

**Seção:** §3.3-1. `opc-worker` e `recorder` derivam status só de `redis_ok and db_ok`, mas `flow-runtime` usa uma TERCEIRA condição: `"ok" if redis_ok and db_ok and runtime_up else "degraded"` (`flow-runtime/main.py:145`).
**Consequência:** não bloqueia o aceite, mas a alegação "mesmo contrato dos outros três" fica incompleta.
**Correção:** especificar que `flow-runtime` soma `runtime_up`.

### FACT-11 — logging.py:9-22 não expõe campo service [Important]

**Seção:** §1.2 (tabela "Fora da F6"). A spec justifica excluir "campo `service` nos logs" da v1 alegando que o JSON de `logging.py:9-22` "já cumpre" RNF-07 ("logs estruturados por serviço"). Falso: `JsonFormatter.format()` emite só `{ts, level, logger, message}` (+`exc` condicional) — sem chave `service`. `record.name` ("logger") é o caminho do logger Python, não o nome do serviço.
**Evidência:** `ottima_core/logging.py:12-21`.
**Consequência:** RNF-07 pode estar genuinamente descoberto; a decisão A-1 de deixá-lo fora da v1 se apoia em premissa de código incorreta.
**Correção:** reescrever a linha da tabela reconhecendo que a distinção por serviço hoje só vem do prefixo de container do `docker compose logs`, não do corpo JSON.

### FACT-12 — conftest.py:14-16 não é a proibição de up/down [Minor]

Linhas 14-16 são imports de stdlib sem relação com o assunto. O texto real ("`down` e `prune` são proibidos") está em `conftest.py:4-6`. Trocar anchor.

### FACT-13 — "constante única" em projects.py:38-41 é imprecisa [Minor]

O texto "Nome de projeto já em uso" não é constante nomeada — é literal duplicado em `projects.py:39` e `:62` (padrão diferente de `connections.py`/`flows.py`, que têm `MSG_*`/`_MSG_*` module-level). O valor final bate, mas não há símbolo para importar.

## Verificações positivas

1. Os seis campos de `tag_ref` (§2.2-1) são exatamente seis — varredura completa de `parse.py` e `mpc_config.py`, mais grep de `_tag_id`/`tag_ref` em todo o repo, não achou sétimo campo.
2. §4.1-3: handles `OUT1..OUTn`/`y1`/`y2` e `extra="forbid"` de Script/Tfs confirmados.
3. §5.2: a tabela dos três caminhos é 100% exata, inclusive as âncoras mais finas da spec inteira (`supervisor.py:338/548/597/643`, `:558`/`:563` dentro de `_reconcile_flow`, `:219-222`, `:644-649`). Único defeito da seção é conceitual (FACT-03), não de anchor.
4. §5.2-2: `revert_armed_mpc` de fato não espera processo nenhum (não chama `host.stop()`).
5. §6.3-1: os dois predicados de pendência são computáveis só com o que a API já devolve hoje (`has_password`/`server_cert_file` em `ConnectionOut`).
6. §3.3-1: `/api/health` da api é mesmo fixo hoje.
7. §6.2: as três rotas de certificado de aplicação e as duas de certificado de servidor existem exatamente como descrito, inclusive o warning de re-trust na linha exata 52.
8. §6.2-3: não existe `type="file"`/`accept=`/multipart real no frontend; todo `FormData` é leitura de campo local — confirma "primeiro upload do frontend".
9. §7.2: os quatro cenários E2E do RNF-09 apontam para a linha exata da `def` de cada teste; `grafo_mpc_tfs` é o único construtor com bloco `tfs` em `conftest.py`.
10. §7.2-5: as duas `FakeClock` são de fato homônimas e incompatíveis (interfaces sem sobreposição).
11. §2.3: `auth_password_enc` é mesmo o único campo-segredo de `OpcConnection`.
12. Nenhum campo órfão em Project/OpcConnection/Tag/Flow — todos exportados ou explicitamente excluídos.
13. `User` não é filho de Project, confirmado.
14. `certs.py:34` e `blocks/mpc.py:453-463` são âncoras exatas, sem ajuste necessário.
