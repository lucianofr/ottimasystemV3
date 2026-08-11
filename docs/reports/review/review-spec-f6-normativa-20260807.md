# Revisão da spec F6 — coerência normativa, escopo e aderência ao aceite

**Spec:** docs/specs/F6-portabilidade-hardening.md @ da25cd6
**Veredito:** REQUEST CHANGES
**Achados:** 4 Critical, 6 Important, 6 Minor

## Achados

### RFC-01 — A camada 2 do import reprova o próprio bundle normativo da spec [Critical]

**Seção:** §2.1-1 · §2.1-2 · §3.2-4 (camada 2) · §2.3

**Problema:** A spec fixa que "cada entidade do bundle é o schema `Create` correspondente menos os segredos e menos os ids" e que a camada 2 de validação é "Forma (Pydantic, schemas `Create` reusados) … `_coerencia` de conexão", citando explicitamente a regra "usuário/senha juntos". Essa regra é incompatível com o bundle: o bundle **nunca** carrega senha (§2.3), mas carrega `auth_mode: "user_password"` e `auth_username` — é literalmente o exemplo normativo de §2.1-2.

Três defeitos no mesmo ponto:

1. `ConnectionCreate._coerencia` levanta `ValueError` quando `auth_mode == "user_password"` e `auth_password` está ausente. Validar o bundle de §2.1-2 com `ConnectionCreate` devolve **422 "Autenticação usuário/senha exige usuário e senha"**.
2. `ConnectionCreate` exige `project_id`; `TagCreate` exige `connection_id`; `FlowCreate` exige `project_id`. Nenhum existe no bundle, por decisão (§2.3). O reuso literal dos schemas `Create` como camada 2 é impossível sem injetar ids sintéticos, e a spec não diz como.
3. Na direção oposta, `auth_password` e `server_cert_file` **são** campos aceitos de `ConnectionCreate`/`_ConnectionFields`, e `_ConnectionFields` não declara `extra="forbid"`. Um bundle que carregue `auth_password` em claro é aceito e a senha é persistida; um bundle que carregue `server_cert_file` é aceito e cria um pinning pendurado num arquivo que não existe no destino — e a coluna de pendências de §6.3 não acusa nada, porque `server_cert_file` é não-nulo. É exatamente o modo de falha que A-3 quis evitar (`cert_missing`/`cert_mismatch` silencioso), reintroduzido pela porta do import.

**Evidência:**
- `packages/ottima-core/src/ottima_core/schemas/connections.py:37-38` — `if self.auth_mode == "user_password" and (not self.auth_username or not self.auth_password): raise ValueError("Autenticação usuário/senha exige usuário e senha")`
- `packages/ottima-core/src/ottima_core/schemas/connections.py:27-28` — `project_id: int` e `auth_password: str | None = None` dentro de `ConnectionCreate`
- `packages/ottima-core/src/ottima_core/schemas/connections.py:13,20` — `_ConnectionFields` sem `extra="forbid"`, com `server_cert_file`
- `packages/ottima-core/src/ottima_core/schemas/tags.py` — `TagCreate.connection_id`; `packages/ottima-core/src/ottima_core/schemas/flows.py` — `FlowCreate.project_id`
- Spec §2.1-1 ("reusa `ConnectionCreate._coerencia` (`schemas/connections.py:30-41`: … usuário/senha juntos) como **camada 2 de validação**, de graça") vs. §2.1-2 (bundle com `auth_mode: "user_password"` e sem senha)
- Contraprova de que o estado "user_password sem senha" é legítimo no resto do sistema: o PATCH de conexão checa a coerência de estado final **sem** a regra do par usuário/senha — `services/api/src/ottima_api/routers/connections.py:210-215` só valida policy×mode e watchdog em par

**Consequência:** ameaça o critério de aceite **"Projeto exportado importa limpo em instalação nova (re-informando segredos)"**. Implementado como escrito, o import recusa com 422 todo bundle cuja conexão use usuário/senha — isto é, precisamente o caso que a cláusula "re-informando segredos" descreve. E2E-F6-02 fica vermelho na primeira camada e o aceite da fase não é atingível. O item 3 é, além disso, caminho de vazamento de segredo em arquivo que circula entre plantas.

**Correção sugerida:** troque §2.1-1 e a camada 2 de §3.2-4 por: "as entidades do bundle têm schemas próprios (`ConnectionBundle`, `TagBundle`, `FlowBundle`) em `ottima_core/schemas/bundle.py`, todos com `extra="forbid"` e **sem** `project_id`/`connection_id`/`auth_password`/`server_cert_file`. As três checagens de `ConnectionCreate._coerencia` são extraídas para funções livres reusadas pelos dois lados (`checar_policy_mode`, `checar_watchdog_par`); a terceira é substituída, no bundle, por **`auth_mode == "user_password"` exige `auth_username`** — a senha é re-informada no destino (§6.3), regra idêntica à coerência de estado final que o PATCH já aplica (`routers/connections.py:210-215`)". Acrescente a §2.3 uma frase normativa: "estes campos, se presentes no bundle, são **reprovados** na camada 2 (`extra="forbid"`), nunca ignorados nem consumidos".

---

### RFC-02 — E2E-F6-04 é inexecutável e contradiz o próprio §1.2 [Critical]

**Seção:** §1.2 (linha "Cenário E2E que derruba `redis`/`timescaledb`") · §9.2-L2 (E2E-F6-04) · §11 (linha Health/heartbeats)

**Problema:** §1.2 põe **fora da v1** o "Cenário E2E que derruba `redis`/`timescaledb` como container real", justificando com a proibição de manipular containers na suíte. §9.2 então lista `E2E-F6-04 | GET /api/health da api degradando: com dependência fora responde 200 com status: degraded` — que só é possível derrubando `redis` ou `timescaledb`. E §11 cita E2E-F6-04 como evidência do critério de health/heartbeats. A mesma spec exclui e exige o mesmo cenário.

**Evidência:**
- Spec §1.2: "Cenário E2E que derruba `redis`/`timescaledb` como container real | fora da v1 … a suíte E2E tem proibição explícita de `up`/`down`"
- Spec §9.2, tabela L2, linha E2E-F6-04; spec §11, linha "Health/heartbeats (RNF-07) | … E2E-F6-04"
- `tests/e2e/conftest.py:3-5` — "Nada aqui sobe ou derruba o stack … O único serviço que os testes mexem é o `opcsim`, e só com `stop`/`start` — `down` e `prune` são proibidos"
- A prova equivalente já existe em nível unitário na própria spec: §9.1 (api) — "`/api/health` com Redis fora ⇒ `degraded` e 200"

**Consequência:** torna uma tarefa do plano F6c inexecutável como escrita (duas leituras possíveis, ambas erradas: violar §1.2 ou entregar o gate incompleto) e deixa a linha RNF-07 de §11 sem evidência válida — evidência citada que não pode ser produzida é igual a evidência ausente no fechamento da última fase da v1.

**Correção sugerida:** remova E2E-F6-04 da tabela L2 e troque a evidência da linha "Health/heartbeats (RNF-07)" de §11 por "§3.3 · **§9.1 (unit: Redis fora ⇒ `degraded` + 200)** · agregador e lâmpadas da F5 em regressão · L1". Se o cenário de container real for desejado, então mova a linha de §1.2 para dentro da fase e escreva o protocolo explícito no §9.3: `docker compose stop redis` → asserção → `start` no `finally`, com `down`/`prune` seguindo proibidos.

---

### RFC-03 — §3.1-3 amplia RF-102 sem emenda, e o aceite depende dessa ampliação [Critical]

**Seção:** §3.1-3 · §1.3 (emendas) · §9.2 (E2E-F6-02)

**Problema:** RF-102 diz **"Export do projeto ativo"**. §3.1-3 decide "Exporta **qualquer** projeto por id, não só o ativo", sem marca `[NOVA — implementação]` e — o que importa mais — **sem linha de emenda em §1.3**, que é o rito que a própria spec institui para corrigir o PRD. Pela precedência declarada no cabeçalho da spec e no PRD ("ADR prevalece … o PRD deve ser corrigido"), o PRD vence a spec enquanto não for emendado: um implementador ou revisor de gate que aplique a precedência restringe o export ao projeto ativo.

Isso não é academismo: o cenário de aceite E2E-F6-02 faz `DELETE` do projeto exportado, e o backend recusa excluir o projeto ativo com 409. Não existe endpoint de desativação — só ativar outro. Logo o cenário só fecha exportando um projeto **inativo**, ou seja, apoiado exatamente na ampliação não emendada.

**Evidência:**
- `docs/PRD.md:82` — "**RF-102** **Export** do projeto ativo em **JSON** …"
- Spec §3.1-3 — "Exporta **qualquer** projeto por id, não só o ativo"
- `services/api/src/ottima_api/routers/projects.py:70-72` — `if project.is_active: raise HTTPException(409, "Desative o projeto antes de excluí-lo")`
- `services/api/src/ottima_api/routers/projects.py:77-99` — `activate_project` é a única transição de `is_active`; não há rota de desativar
- Spec §9.2 E2E-F6-02 — "exporta ⇒ `DELETE` do projeto (CASCADE) ⇒ importa"

**Consequência:** ameaça o critério **"Projeto exportado importa limpo em instalação nova"**. Sob a letra do RF-102, o único cenário que prova o aceite é inexecutável (não se exclui o que se exportou). Sob a letra da spec, o PRD sai da v1 contradizendo a API entregue — no documento que o cliente e o próximo mantenedor leem como fonte de RF.

**Correção sugerida:** acrescente linha em §1.3: "| 7 | PRD §5.2, RF-102 | 'Export do projeto ativo' passa a 'Export de **qualquer projeto** por id (arquivar engenharia antes de ativar outra é caso real); permanece admin-only, sem histórico e sem segredos' — v1.4 |". E em §3.1-3 acrescente a frase "o cenário de aceite E2E-F6-02 depende disso: o `DELETE` exige projeto inativo (`projects.py:70-72`)".

---

### RFC-04 — O modelo de pendências é cego ao estado da instalação; `auth_mode = certificate` não gera pendência nenhuma [Critical]

**Seção:** §3.2-7 · §6.3-1 · §2.3 · §11 (linha "Re-informando segredos")

**Problema:** A spec fixa duas pendências deriváveis: `needs_password := auth_mode == "user_password"` e `needs_server_certificate := security_policy != "none"`, e afirma que "a pendência é 100% derivável". Faltam dois casos, ambos exatamente no cenário do aceite ("instalação nova"):

1. **`auth_mode == "certificate"`** existe desde a v1 (RF-201, ADR-021: "anônimo · usuário/senha · **certificado X.509** — tudo disponível desde a v1"). Uma conexão importada com `auth_mode: "certificate"` e `security_policy: "none"` produz `pending_secrets = {needs_password: false, needs_server_certificate: false}` — o import declara "nada pendente" — e a coluna Pendências de §6.3 fica neutra. Mas a identidade X.509 de usuário reusa o par do certificado de aplicação, que na instalação nova não existe: a conexão falha em `cert_missing`, sem nenhum aviso prévio na tela.
2. **Certificado de aplicação ausente** é pendência de **instalação**, não de conexão, e nenhuma das duas derivações a vê. Numa instalação nova, toda conexão com `security_policy != "none"` falha em `cert_missing` por falta do certificado de aplicação **mesmo depois** de o engenheiro confiar no certificado do servidor e a pendência de §6.3 apagar. O `title` prescrito em §6.3-2 ("a conexão falhará em `cert_missing` até confiar no certificado do servidor") passa a ser falso nesse estado: confiar no servidor não resolve.

E2E-F6-02 nunca pega nenhum dos dois: roda na mesma instalação, onde o certificado de aplicação já existe, e usa usuário/senha.

**Evidência:**
- `packages/ottima-core/src/ottima_core/schemas/connections.py:10` — `AuthMode = Literal["anonymous", "user_password", "certificate"]`
- `services/opc-worker/src/ottima_opc_worker/security.py:167-176` — em `AUTH_CERTIFICATE`, "o token X.509 de usuário reusa o par do app" → `_require_app_certificate(certs_dir)`
- `services/opc-worker/src/ottima_opc_worker/security.py:177-187` — `_require_app_certificate` levanta `CertMissingError("certificado de aplicação não foi gerado: gere-o antes de usar canal seguro ou identidade por certificado")`
- `services/opc-worker/src/ottima_opc_worker/security.py:143` — o canal seguro também exige o certificado de aplicação, antes do pinado
- `services/api/src/ottima_api/routers/certificates.py` / `schemas/certificates.py:8-14` — `AppCertificateOut.exists` já entrega o dado necessário (a spec já o consome em §6.2-1)

**Consequência:** ameaça o critério **"…importa limpo em instalação nova (re-informando segredos)"**. O engenheiro na planta do cliente importa, lê "nada pendente" (ou resolve a pendência exibida) e a conexão continua muda — o buraco que A-4 existe para fechar, deixado aberto para 1 dos 3 modos de autenticação da v1 e para o primeiro boot de toda instalação nova.

**Correção sugerida:** em §6.3-1 e §3.2-7, passe a **três** pendências deriváveis, sem campo novo:
- `needs_password ⇔ auth_mode == "user_password" && !has_password`
- `needs_server_certificate ⇔ security_policy != "none" && !server_cert_file`
- `needs_app_certificate ⇔ (security_policy != "none" || auth_mode == "certificate") && !appCert.exists` — lido de `GET /api/certificates/app` (`exists`) no cliente e da mesma fonte no import
Acrescente em §6.3-2 que a pendência de certificado de aplicação é **de instalação**, exibida na chapa de §6.2-1 e replicada por linha, com `title` "gere o certificado de aplicação: a conexão falhará em `cert_missing` mesmo com o certificado do servidor confiado". Acrescente em E2E-F6-01/02 uma conexão `auth_mode: "certificate"` no projeto exportado, para o predicado ficar coberto.

---

### RFC-05 — A emenda ao PRD §7.2 (§1.3-1) não lista tudo que muda [Important]

**Seção:** §1.3-1 · §2.1-2

**Problema:** A linha de emenda enumera: campos planos `security_*`/`watchdog_*`, `direction`/`data_type`/`description` no lugar de `dir`, mais `exported_at`, `desired_state` e `tag_ref`. Ficaram de fora mudanças reais do exemplo:
- **`ts` → `ts_seconds`**: o PRD §7.2 traz `"ts": 1` e o bundle traz `"ts_seconds": 1.0`, que é o nome do schema (`FlowCreate.ts_seconds`). Renomeação de campo do contrato, não citada.
- `auth_mode` / `auth_username`: campos novos no exemplo, não cobertos pela enumeração "campos planos `security_*`/`watchdog_*`".
- Valor de `direction`: o PRD escreve `"dir": "R"` (maiúscula) e o schema usa `Literal["r", "w"]` — muda o **valor**, não só o nome.
- O cabeçalho do PRD: a emenda fala de "changelog v1.4", mas a linha "**Versão do documento:** 1.3 · 2026-08-06 · **Status:** aprovado para implementação (F1 e F2 concluídas)" também precisa mudar — e "F1 e F2 concluídas" está obsoleto desde a F3.

**Evidência:** `docs/PRD.md:186` (`"flows": [{"name": "...", "ts": 1, …}]`), `docs/PRD.md:185` (`"dir": "R"`), `docs/PRD.md:4` (linha de versão/status); `packages/ottima-core/src/ottima_core/schemas/flows.py` (`FlowCreate.ts_seconds`), `schemas/tags.py` (`Direction = Literal["r", "w"]`); spec §2.1-2.

**Consequência:** a emenda é o ato normativo; o que não está na linha não entra na Etapa 0 do plano F6a. O PRD §7.2 sai da v1 anunciando `ts` e `"R"` num contrato cujo código usa `ts_seconds` e `"r"` — e a próxima pessoa a implementar um importador externo lê o PRD, não a spec.

**Correção sugerida:** reescreva a célula "O que muda" de §1.3-1 como: "O exemplo passa a espelhar os schemas `Create`: campos planos `security_policy`/`security_mode`/`auth_mode`/`auth_username`/`watchdog_*`; `direction` (valores `"r"`/`"w"`), `data_type` e `description` no lugar de `dir`; `ts` → `ts_seconds`; ganha `exported_at`, `desired_state` e `tag_ref` dentro do `graph` (§2). Atualiza a linha de versão para **v1.4 · 2026-08-07** e o Status para 'aprovado para implementação (F1–F5 concluídas)'."

---

### RFC-06 — `opc.values` vira "nunca" sem emendar o PRD §7.1 e §7.3 [Important]

**Seção:** §1.2 (linha `opc.values`) · §1.3-4 · §10

**Problema:** A decisão de encerrar o registro como "nunca" está tecnicamente correta (conferi: não há consumidor). Mas §1.3-4 emenda apenas as specs F2/F3/F5. O **PRD** lista `api(WS)` como consumidor normativo de `opc.values.<conn_id>` em §7.1 e descreve `/ws` como "(valores, mpc.state, flow.status, events)" em §7.3. Pela precedência declarada, uma spec não revoga o PRD; e esta é a última fase da v1, então o registro fecha com o PRD prometendo um consumidor que nunca existirá.

**Evidência:** `docs/PRD.md:172` — "| `opc.values.<conn_id>` | opc-worker | flow-runtime, recorder, **api(WS)** | …"; `docs/PRD.md:192` — "`/ws` (valores, mpc.state, flow.status, events)". Fato conferido: `services/api/src/ottima_api/ws.py:120-127` tem dois `PatternListener` (`flow.status.*`, `mpc.state.*`) e um `ChannelListener("events")`, sem `opc.values`; `frontend/src/app/canalAoVivo.check.ts:167` afirma por teste que envelope de `opc.values.3` é ignorado.

**Consequência:** contrato §7 do PRD permanentemente divergente do sistema entregue, sem rastro de decisão no documento normativo — o inverso do que o rito de §1.3 existe para evitar. Quem for planejar a v2 lerá §7.1 como requisito vigente.

**Correção sugerida:** acrescente à emenda §1.3-1 (mesma bala de v1.4) ou como linha nova: "PRD §7.1 (linha `opc.values.<conn_id>`) e §7.3: remover `api(WS)` da lista de consumidores e `valores` da descrição do `/ws` — decidido **nunca** na F6 (§1.2); o canvas ao vivo usa `flow.status.ports` (RF-404, PRD v1.2) e o trend de engenharia usa REST de histórico (RF-802)".

---

### RFC-07 — A emenda §1.3-6 descreve um trecho que a F5 §8 não contém, e omite o caminho que a F5 de fato perdeu [Important]

**Seção:** §1.3-6 · §5.2-1

**Problema:** A emenda diz que a última linha da F5 §8 é corrigida porque "são **3** caminhos, não 4 — `_teardown` não roda sob o lock". A linha citada da F5 não fala em quatro caminhos nem menciona `_teardown`: ela enumera **três** contextos (`_force_stop` via `on_project_activated`, `_pass`/`_reconcile_flow`, `_handback_failed_mpc`). Ou seja, a "correção do inventário" corrige uma afirmação que o documento citado não faz.

Pior: a correção real que §5.2 traz — o caminho `_deploy` sobre o `old_runtime` do redeploy — **está ausente** da linha da F5, e a emenda não registra isso. O ledger da F5 continuará dizendo que o débito são aqueles três contextos, sem o redeploy.

**Evidência:** `docs/specs/F5-operacao.md:245` — "`shutdown_mpc` síncrono sob o lock em `_force_stop` (`on_project_activated`), `_pass`/`_reconcile_flow` e `_handback_failed_mpc`" (sem `_teardown`, sem contagem "4"); spec F6 §5.2-1, linha 1 da tabela — `_deploy`, `supervisor.py:338`, confirmado em `services/flow-runtime/src/ottima_flow_runtime/supervisor.py:328-338`.

**Consequência:** a nota de remissão que entra na F5 §8 na Etapa 0 do plano F6a vai contradizer o texto que anota, e a única informação nova de verdade (o quarto ponto de chamada, no redeploy) não fica registrada em nenhum dos dois documentos como achado.

**Correção sugerida:** troque a célula por: "Fecha em §5.2. Correção do inventário: além dos três contextos que a F5 listou, existe um quarto ponto de chamada não registrado — `_deploy` sobre o `old_runtime` do redeploy (`supervisor.py:338`). São **3 pontos de chamada** de `shutdown_mpc` sob o lock (`_deploy`, `_handback_failed_mpc`, `_force_stop`, este último alcançado por `on_project_activated` e por `_reconcile_flow`). `_teardown` (`supervisor.py:643`) não roda sob o lock e fica como está."

---

### RFC-08 — Duas linhas da tabela §11 citam evidência que não prova o critério [Important]

**Seção:** §11

**Problema:**
1. Linha "Import com validação de schema, **criando projeto inativo** (RF-103)" cita §3.2, E2E-F6-03 e B-F6-06/08. E2E-F6-03 só testa recusas; B-F6-06 checa nome pré-preenchido, resumo de pendências e navegação; B-F6-08 checa recusa. Nenhum deles observa `is_active == false`. A prova existe — está em §9.1 (api: "`is_active` sempre false") — e não é citada. Note que E2E-F6-02 também não prova: ele **ativa** o projeto em seguida, então passaria igual se o import nascesse ativo.
2. Linha "**Projeto exportado importa limpo em instalação nova**" cita §2.2 e E2E-F6-02, e nada de UI — apesar de a própria spec afirmar em §1-3 que "sem essa tela o próprio aceite da F6 é inatingível pela UI: o import cria projeto inativo (RF-103) e ninguém consegue ativá-lo".

**Evidência:** spec §11 (linhas 2 e 3); spec §9.1 (bullet "api", item "`is_active` sempre false"); spec §9.2 (E2E-F6-03 = "Recusas do import"); spec §1-3.

**Consequência:** a tabela de aderência é o instrumento de fechamento da fase. Linha com evidência que não prova o critério passa no gate por leitura, não por prova — e o critério de RF-103 mais fácil de regredir em refactor (nascer ativo) fica sem apontamento de teste no fechamento da última fase da v1.

**Correção sugerida:** linha 2 → "§3.2 (4 camadas, transação única) · **§9.1 (api: `is_active` sempre false)** · E2E-F6-03 (recusas) · B-F6-06/08". Linha 3 → "§2.2 · **§6.1 (página de Projetos: sem ela o projeto importado é inativável — §1-3)** · **E2E-F6-02** · **B-F6-01/02/06**".

---

### RFC-09 — Os 3 planos são anunciados sem mapa de seções; §4, §5 e §6.6 ficam sem dono [Important]

**Seção:** cabeçalho ("Execução: 1 spec + 3 planos — F6a/F6b/F6c") · §1.3-Aplicação

**Problema:** A spec nomeia F6a (portabilidade & dados), F6b (superfícies) e F6c (suíte RNF-09 & guia), e o único vínculo explícito seção→plano no documento inteiro é "Etapa 0 do plano F6a" para as emendas. Não há mapa. Consequências concretas de ambiguidade:
- §5 (débitos de runtime: payload de `mpc_overrun`, `shutdown_mpc` fora do lock) é cirurgia no `flow-runtime` — não é "portabilidade & dados" nem "superfícies" nem "suíte".
- §4.1/§4.2 são schema em `ottima-core` **mais** projeção de API (`/api/operate/mpcs`) **mais** superfícies (§6.4/§6.5), atravessando F6a e F6b.
- §6.6 (débitos de frontend) é superfície, mas não é entrega de fase nenhuma listada no PRD §8.
- Há dependência de ordem entre planos que ninguém declarou: §7.4 fixa que o critério do overrun reescrito inclui "contador somando", cujo dado vem do payload novo de §5.1. Se §5 cair em F6a e §7 em F6c, F6c depende de F6a; se §5 cair em outro plano, a ordem muda.

**Evidência:** spec, linha 5 do cabeçalho; §1.3 ("Aplicação: **Etapa 0 do plano F6a**"); §5.1; §7.4; ausência de qualquer outra menção a F6a/F6b/F6c no corpo.

**Consequência:** retrabalho e colisão na execução: dois planos podem reclamar §4/§6.6, ou nenhum, e o ordering F6a→F6c fica implícito. Numa fase que já mistura backend, schema, runtime, frontend e testes, a divisão precisa estar escrita.

**Correção sugerida:** acrescente ao fim de §1.1 uma tabela de 3 linhas: "**F6a** — §1.3 (Etapa 0), §2, §3, §4.1/§4.2 (schema + projeção), §5; **F6b** — §6 inteiro (incl. §6.4/§6.5/§6.6); **F6c** — §7, §8, §9.2-L2/L3. F6c depende de F6a por §5.1 (contador de `overruns` no payload) e por §3 (endpoints de export/import)."

---

### RFC-10 — §7.4 exige recalibração sem critério de saída nem decisão de contingência [Important]

**Seção:** §7.4 · §11 (linha "Suíte MPC↔TFS verde")

**Problema:** §7.4 determina que as tolerâncias e timeouts dos dois cenários reescritos "**precisam ser recalibrados**" e proíbe — corretamente — "um valor numérico novo inventado para fazer o teste passar". O que não existe é o critério de saída: nada diz o que é uma calibração **aceitável**, nem o que fazer se o overrun deixar de ser reprodutível com a TFS na malha (com solve de 13-17 s contra orçamento de ~0,35 s, a planta TFS integra por dezenas de varreduras e o flow acumula `flow_overrun` junto do `mpc_overrun`). O executor de F6c fica entre violar a proibição e não fechar o aceite.

**Evidência:** spec §7.4 (incl. a citação do docstring de `test_f4_failure.py:166`, "solve consistente em ~13-17 s, ~40-50× o orçamento"); spec §11, última linha, cuja única evidência é "§7".

**Consequência:** ameaça o critério de aceite **"suíte MPC↔TFS verde"** por decisão não tomada: o plano F6c tem uma tarefa cujo sucesso depende de uma escolha que a spec proíbe e não substitui. É a definição de tarefa que dois executores resolveriam de formas incompatíveis (um afrouxa tolerância, outro muda o grafo).

**Correção sugerida:** acrescente a §7.4: "Critério de calibração: (a) o `Ts_flow` e o multiplicador do cenário podem ser aumentados para que o **flow** não entre em overrun junto com o MPC — só o orçamento do solver deve estourar; (b) as asserções permanecem qualitativas (MV byte a byte inalterada entre execuções, `mpc_overrun` emitido, contador monotônico, fila nunca acumulada), sem limiar numérico novo; (c) se, com (a), o overrun deixar de ser reprodutível em 3 execuções consecutivas, **o cenário dummy `_grafo_overrun` é mantido como cenário adicional** e o item 'overrun' do RNF-09 é declarado coberto pela dupla (dummy determinístico + TFS qualitativo), registrado em §10."

---

### RFC-11 — Três âncoras erradas (§1.2, §8-1, §3.3-3) [Minor]

**Seção:** §1.2 (linha do cenário E2E de queda de dependência) · §8-1 · §3.3-3

**Problema:**
1. §1.2 cita `tests/e2e/conftest.py:14-16` como "proibição explícita de `up`/`down`". Aquelas linhas são `import subprocess`, `import time` e `from collections.abc import Callable, Iterator`. A proibição está no docstring, em `:3-5`, e é sobre **`down` e `prune`** — `stop`/`start` do `opcsim` é explicitamente permitido, o que enfraquece a justificativa usada para excluir o cenário (ver RFC-02).
2. §8-1 cita `deploy/.env.example:18,21` para as duas chaves geradas à mão. `OTTIMA_SECRET_KEY=` está em `:18`, mas `OTTIMA_FERNET_KEY=` está em **`:22`** — `:21` é a linha de comentário "# Gerar: python -c …".
3. §3.3-3 cita `docker-compose.yml:43-48` para o healthcheck do serviço `api`. O bloco `healthcheck` que bate em `/api/health` está em **`:46-50`**; `:43-45` é o `depends_on` do `redis`.

**Evidência:** `tests/e2e/conftest.py:3-5` — "Nada aqui sobe ou derruba o stack … `down` e `prune` são proibidos porque a máquina hospeda outros projetos"; `tests/e2e/conftest.py:14-16` — imports. `deploy/.env.example:22` — `OTTIMA_FERNET_KEY=`. `deploy/docker-compose.yml:46-50` — `healthcheck: test: [… urllib.request.urlopen('http://localhost:8000/api/health' …)]`.

**Consequência:** revisor de gate que abra as âncoras não encontra a regra citada; no caso 1 a justificativa de escopo perde lastro (e a regra real permite `stop`/`start`, o que contradiz o uso que §1.2 faz dela).

**Correção sugerida:** §1.2 → "(`tests/e2e/conftest.py:3-5`: `down` e `prune` proibidos; só o `opcsim` é manipulado, com `stop`/`start`)". §8-1 → "`deploy/.env.example:18,22`". §3.3-3 → "`docker-compose.yml:46-50`".

---

### RFC-12 — "logs estruturados por serviço já cumpre" apoia-se em interpretação não declarada [Minor]

**Seção:** §1.2 (linha do campo `service` nos logs)

**Problema:** A spec descarta o campo `service` afirmando que "o JSON de `ottima_core/logging.py:9-22` já cumpre" RNF-07. O JSON emitido tem `ts`, `level`, `logger`, `message` (+ `exc`) — nenhum discriminador de serviço. A leitura defensável é "cada serviço emite log estruturado, e o serviço é identificado pelo container no `docker compose logs`", mas isso é uma interpretação de RNF-07 e precisa estar escrita, já que é a última chance da v1 de fechar o requisito.

**Evidência:** `packages/ottima-core/src/ottima_core/logging.py:13-22` — `entry = {"ts": …, "level": …, "logger": record.name, "message": …}`; `docs/PRD.md:162` — RNF-07 "logs estruturados por serviço".

**Consequência:** RNF-07 fecha por afirmação, não por leitura verificável; um auditor lê "por serviço" como campo e reabre o item.

**Correção sugerida:** troque a justificativa por: "fora da v1 — RNF-07 é lido como 'cada serviço emite log estruturado', satisfeito por `ottima_core/logging.py:13-22`; a atribuição ao serviço vem do nome do container (`docker compose logs <svc>`) e do `logger` do registro. Correlação por `request_id` fica fora."

---

### RFC-13 — §3.2-7 e §6.3-1 não são "o mesmo predicado" [Minor]

**Seção:** §3.2-7 · §6.3-1

**Problema:** §3.2-7 define `needs_password := auth_mode == "user_password"` e diz que é "o mesmo predicado que a página de Conexões avalia continuamente (§6.3)". §6.3-1 define `falta senha ⇔ auth_mode == "user_password" && !has_password`. Coincidem apenas no instante do import (quando `has_password` é sempre falso). São dois predicados na spec para uma coisa que ela declara única.

**Evidência:** spec §3.2-7 e §6.3-1, verbatim.

**Consequência:** o teste de §9.1 ("predicado de pendência de segredo (4 combinações)") não diz qual dos dois cobre; e uma futura reutilização de `pending_secrets` fora do import (ex.: resumo por projeto) passaria a mentir.

**Correção sugerida:** em §3.2-7, escreva os dois predicados completos, com `&& !has_password` e `&& !server_cert_file`, e a nota "no import ambos os termos negativos são sempre verdadeiros; a forma completa é escrita para o predicado ser literalmente único (§6.3-1)".

---

### RFC-14 — GLOSSARY não é emendado, mas a fase introduz vocabulário [Minor]

**Seção:** §1.3 · §2 · §6.3

**Problema:** O `GLOSSARY.md` é normativo para vocabulário e §6 manda usar "o vocabulário do `GLOSSARY.md`". A F6 introduz dois termos que não estão lá: **bundle** (termo central de §2/§3, em inglês, enquanto o PRD chama "JSON de projeto") e **pendência (de segredo)**, que vira rótulo de coluna visível ao usuário em §6.3-2. §1.3 não tem linha de emenda ao glossário.

**Evidência:** `docs/GLOSSARY.md` (verbete "Projeto": "Exportável/importável em JSON"; sem "bundle", sem "pendência"); spec §2.1 título ("O bundle espelha…"), §6.3-2 ("Coluna **Pendências**").

**Consequência:** vocabulário de UI e de spec divergindo do glossário no fim da v1; e "bundle" em documento cuja UI é obrigatoriamente pt-BR convida a vazar o termo para a tela.

**Correção sugerida:** acrescente linha em §1.3: "| 8 | `GLOSSARY.md` | Dois verbetes novos: **Bundle de projeto** ('arquivo JSON de export/import de um projeto, sem histórico e sem segredos; `schema_version` 1') e **Pendência de segredo** ('estado derivado de uma conexão importada que ainda não teve senha e/ou certificados re-informados'). Em texto de UI o termo é 'arquivo de projeto', nunca 'bundle'."

---

### RFC-15 — §3.3-3 mantém `/api/health` sem autenticação e amplia o corpo público, sem registrar a exceção a RF-003 [Minor]

**Seção:** §3.3-2/3

**Problema:** RF-003 diz "**Toda rota é protegida**; autorização por dependência de papel". `/api/health` é público desde a F1 — exceção legítima e necessária (healthcheck do compose), mas não registrada em nenhum documento normativo. A F6 é a fase que **amplia** o corpo dessa rota pública, acrescentando `redis_ok` e `db_ok`, e a spec trata a publicidade como fato herdado, sem marca nem nota.

**Evidência:** `docs/PRD.md:78` — RF-003; `services/api/src/ottima_api/routers/health.py:1` — "Health check público (sem autenticação)"; `services/api/src/ottima_api/routers/health.py:36` — `/health/workers` com `require_operator`; spec §3.3-2/3.

**Consequência:** exceção a RF-003 fica sem lastro documental no fecho da v1, e a ampliação do corpo público (estado das dependências de infraestrutura, em rede HTTP sem TLS por ADR-023) passa sem decisão escrita.

**Correção sugerida:** em §3.3-3, escreva: "A rota segue pública — **exceção a RF-003 herdada da F1** (`routers/health.py:1`), necessária ao healthcheck do compose (`docker-compose.yml:43-48`) e ao passo E2E-01a. Nesta fase o corpo público ganha `redis_ok`/`db_ok`: dois booleanos de dependência, sem endpoint, host nem versão de dependência **[NOVA — implementação]**. O agregador `/health/workers`, que expõe detalhe por worker, permanece autenticado."

---

### RFC-16 — RF-702 ("com EU e limites") continua estruturalmente descoberto para DV sem `range` [Minor]

**Seção:** §4.2-2 · §6.5

**Problema:** `DvVar.range` é opcional e nenhum config existente é migrado; §6.5 diz que sem `range` o faceplate fica sem barra. Portanto, todo projeto vindo da F5 continua exibindo DV sem faixa, e RF-702 ("faceplates … DV (somente leitura) — com EU e limites") segue parcialmente descoberto sem que nada na UI diga ao engenheiro que existe um campo a preencher. A decisão A-11 (opcional, sem migration) não é o problema; a lacuna é a ausência de sinalização.

**Evidência:** spec §4.2-2 ("opcional: nenhum config existente quebra"), §6.5 ("Sem `range`, permanece como a F5 entregou"); `docs/PRD.md:144` — RF-702.

**Consequência:** o requisito fecha "por opção do usuário", sem caminho de descoberta: o engenheiro que nunca abrir a aba Variáveis não sabe que a barra do DV depende dele.

**Correção sugerida:** acrescente a §4.2-5/§6.5: "Na aba **Variáveis**, DV sem `range` exibe dica inline 'sem faixa: o faceplate mostra valor e EU, sem barra' (Texto Secundário, sem cor de severidade — a ausência não é anormal). O faceplate sem barra é estado válido e final, não erro."

---

## Verificações positivas

Conferido e **correto** — não precisa de nova revisão:

1. **§2.2, os seis campos de tradução.** Confirmados: `opc_read.config.tag_id` e `opc_write.config.tag_id` (`flowgraph/parse.py:20-21`, `TagConfig` em `:49-51`) + `write_tag_id`, `mode_cmd_tag_id`, `mode_read_tag_id`, `readback_tag_id` (`flowgraph/mpc_config.py:63-67`, `PidBinding`). Âncora `_CONFIG_KEYS` em `parse.py:19-25` está certa. A recusa da varredura heurística (§2.2-3) é coerente com `TagConfig`/`PidBinding` serem `extra="forbid"`.
2. **§2.1-4 e RF-104/RNF-03: import não auto-aplica nada.** Verificado no código, não só na spec: `_pass` "por construção nunca inicia flow nenhum (contrato 1 / ADR-017): não existe caminho daqui para `start()`" (`supervisor.py:507-516`) e `on_project_activated` só para flows (`supervisor.py:491-496`). Exportar `desired_state` verbatim não cria caminho de escrita em planta sem ação humana.
3. **§5.2, inventário e âncoras.** Todas conferem: lock tomado em `:259`/`:477`/`:494`/`:517`; `shutdown_mpc` em `_deploy` (`:338`, sobre `old_runtime`, com o comentário de origem do achado da revisão F4), em `_handback_failed_mpc` (`:548`) e em `_force_stop` (`:597`, alcançado por `on_project_activated` e por `_reconcile_flow` `:558`/`:563`); `_teardown` fora do lock. O par prescrito em §5.2-2 é o mesmo padrão que `_stop` já usa (`supervisor.py:346`), e a preocupação de §5.2-3 com a posse das tasks destacadas é real (`self._state.track` substitui o runtime antes do `shutdown_mpc` do redeploy).
4. **§1.2, `opc.values` sem consumidor — fato verdadeiro.** `ws.py:120-127` tem só `flow.status.*`, `mpc.state.*` e `events`; `frontend/src/app/canalAoVivo.check.ts:167` afirma por teste que envelope de `opc.values.*` é ignorado. A decisão "nunca" é factualmente sustentada; falta só a emenda ao PRD (RFC-06).
5. **§3.1-1, RBAC do export.** PRD §2 põe "Export/import de projeto" na linha admin-only (`PRD.md:32`). `require_admin` está correto, e B-F6-13 cobre.
6. **§3.2-6, 409 de nome.** `create_project` responde 409 "Nome de projeto já em uso" (`projects.py:37-39`); a âncora `projects.py:38-41` é boa e a reutilização da constante é a convenção do sistema. A-6 (sem sufixo automático) é coerente com ADR-017.
7. **§8, o guia.** PRD §9-5 é de fato o item "Bumpless dependente do PLC … documentar pré-requisitos de comissionamento por malha (guia de integração, F6)" (`PRD.md:212`) — a citação está certa apesar da numeração fora de ordem do PRD §9 (…4, 6, 5). O sumário de §8 cobre os pré-requisitos de PID por modo-alvo, que é o coração do risco.
8. **Escopo: bootstrap de segredos do `.env` fora da v1 NÃO é pré-requisito do aceite.** Os "segredos" do aceite são os da conexão OPC (RF-102/103); as chaves de instalação são passo de instalação, documentado em §8-1 com âncora (`deploy/.env.example:18,21`). Excluir é legítimo.
9. **§1.3-2/3/5 apontam trechos que existem.** F2 §1.2 "UI de gestão de certificados | F6" (`F2-aquisicao.md:43`); F4 §1.2 "Suíte completa de malha fechada RNF-09 … | F6" (`F4-mpc.md:37`) e F5 §1.2 (`F5-operacao.md:43`); F5 §1.2 "EU nas portas de Script/TFS … | F6" (`F5-operacao.md:42`). Só a linha 6 está mal descrita (RFC-07).
10. **RF-202 coberto nas três capacidades** por §6.2 (gerar / baixar `.der` / confiar no certificado do servidor + deixar de confiar), com o aviso de re-trust exibido verbatim. RF-101 coberto por §6.1 (CRUD + ativar com o efeito escrito, ADR-017). RNF-09 coberto nos quatro itens por §7.
11. **§2.3 é coerente com as fontes** nas linhas de `id`/`project_id`/`connection_id`, `is_active` (RF-103), `User` (PRD §4 — não é filho de Project) e `samples`/`events`/`mpc_samples` (RF-102/ADR-012 "nunca dados históricos").
12. **§5.2-3 como grau de liberdade é aceitável**: a forma ("conjunto no `Supervisor` ou transferência para o runtime novo") está marcada `[NOVA — implementação] (forma)` e a invariante fica guardada pelo teste de §9.1 ("`_teardown` continua esperando … inclusive as dos caminhos novos"). Não é decisão pendente, é liberdade delimitada.
