# Plano F6c — Suíte RNF-09, cenários de portabilidade e guia de implantação

> **Para executores agênticos:** execução tarefa a tarefa com subagente por tarefa + revisão independente (padrão F3/F4/F5, skill subagent-driven-development; ledger em `.superpowers/sdd/F6c-suite-e-guia/progress.md`). Checkboxes das tabelas rastreiam conclusão. **Pré-requisito: planos F6a e F6b concluídos** — os cenários de portabilidade exercitam as rotas do F6a, o critério de `E2E-F6-05` depende do contador de `overruns` de F6a §5.1, e o roteiro L3 exercita as telas do F6b. **O roteiro L3 e toda validação de browser são do controlador** (a tool `browser` é bloqueada a subagentes).

**Fase:** F6 (PRD §8) — **última fase da v1** · plano 3 de 3 (decisão A-1; mapa §12 da spec) · 2026-08-07
**Executa:** `docs/specs/F6-portabilidade-hardening.md` §7 (suíte RNF-09), §9.2 (E2E-F6-01/02/03/05/06 e o gate de 3 camadas), o roteiro L3 `docs/plans/tests-e2e-f6.md` e §8 (guia de implantação) — backend/schema são do F6a, superfícies do F6b
**Fontes normativas:** `docs/PRD.md` v1.4 (§8-F6 aceite, §9-5 guia) · `docs/adr/ADR-001…024` (prevalecem; ADR-003 retenção, ADR-009 watchdog, ADR-010 modos, ADR-011 hot-swap, ADR-016 predição volátil, ADR-018 escopo do Script, ADR-021 certificados, ADR-022 malha TFS) · `docs/GLOSSARY.md` · spec F6 · `CLAUDE.md` §Comandos
**Objetivo:** aceite da fase provado ponta a ponta — round-trip destrutivo de projeto verde, suíte RNF-09 verde sob marcador próprio com prova de dinâmica pela malha TFS, guia de implantação escrito, e **gate completo da fase (L1 + L2 + Playwright + L3) verde na mesma rodada**.
**Stack:** nenhuma dependência nova. `pytest` + `httpx` + `websockets` do conftest E2E existente; opcsim como origem OPC.

## Regras globais

Idênticas aos planos F6a/F6b (governança, worktree `ottimaSystemV3-f6`/branch `f6-portabilidade`, ciclo verde por etapa, **caminho absoluto em toda edição de subagente**, credenciais inline, lacuna ⇒ perguntar), mais:

1. **Precondições de ambiente (spec §9.3, herdadas de F3/F4/F5):** L2 e Playwright **serializados**, nunca simultâneos; credenciais **sempre inline** de `deploy/.env`; **sempre os DOIS arquivos compose**; `down -v` **só com autorização explícita do usuário e dump prévio**; **nunca** `prune`. A suíte E2E não sobe nem derruba o stack (`tests/e2e/conftest.py:1-6`) — o único serviço que ela mexe é o `opcsim`, e só com `stop`/`start`.
2. **Idempotência dos cenários novos:** convenção `RUN_ID` + sentinela de teardown já usada pela suíte (`tests/e2e/conftest.py:46-52`) — os cenários precisam ser re-executáveis na mesma stack, sem `down`.
3. **`grafo_mpc_tfs` e `_config_mpc_malha` (`conftest.py:620` e `:531`) NÃO são alteradas.** São usadas pelos cenários de aceite da F4 **e** por `scripts/setup-l3.py`; os cenários novos ajustam o dict devolvido, nunca a fixture (F6R-01 nasceu exatamente de propor o contrário).
4. **Critério de teste é comportamento normativo, nunca número escolhido para passar** (§7-5). Contingência declarada só onde a spec a declarou.
5. **DoD do plano = DoD da FASE:** §Aderência ao final; a fase só encerra com a rodada de gate inteira verde (Etapa 6).

## Interfaces consumidas (produzidas no F6a/F6b — não redefinir)

`GET /api/projects/{id}/export` · `POST /api/projects/import` (413/409/422 agregado com separador ` | `) · `ProjectImportOut.pending_secrets` com os 3 predicados · `GET /api/health` com `redis_ok`/`db_ok` · `mpc_overrun` com `payload["overruns"]` (F6a §5.1) · `DvOut.range` · `output_eu` em `script`/`tfs` · telas `/engenharia/projetos`, chapa de certificados, coluna de pendências, faceplate de DV com barra (F6b).

Fixtures E2E existentes reusadas sem alteração: `admin` (`conftest.py:284`), `redis_bus` (`:293`), `eventos` (`:303`), `opcsim_client` (`:313`), `congelar_watchdog` (`:318`), `parar_opcsim` (`:331`), `projeto_com_conexao` (`:369`), `ambiente_mpc` (`:461`), `criar_flow_mpc` (`:742`, já parametriza `ts_seconds` e `grafo`). Constantes: `TS_FLOW_MPC = 0.5`, `MULTIPLICADOR_MPC = 2`, `TS_MPC = 1.0`, `TSS_MALHA = 10.0`, `VALOR_DV = 2.0`, `SENTINELA` (`:52`).

---

## Etapa 1 — Marcador `rnf09` e composição da suíte (spec §7-1/4; ADR-022)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 1.1 | **Marcador `rnf09`** registrado em `[tool.pytest.ini_options].markers` (`pyproject.toml`, hoje só `e2e` e `slow`), com descrição "suíte MPC↔TFS do aceite RNF-09 (ADR-022)". Aplicado sobre os **quatro** cenários existentes que já provam os itens, **sem renomear nenhum id** (renumerar quebraria a rastreabilidade das fases anteriores, §7-4): `E2E-F4-03` (bumpless, `tests/e2e/test_f4_mpc.py:309`), `E2E-F4-05` (precedência de restrição, `test_f4_mpc.py:398`), `E2E-F4-06` (overrun/estresse do solver, `test_f4_failure.py:159`) e `E2E-F4-10` (hot-swap com irmão de controle, `test_f4_ws.py:210`). O marcador é **aditivo**: cada um mantém `@pytest.mark.e2e`. `uv run pytest -m rnf09` funciona porque o `-m` da linha de comando sobrescreve o `addopts` (`-m 'not e2e and not slow'`) | `pyproject.toml` · `tests/e2e/test_f4_mpc.py` · `tests/e2e/test_f4_failure.py` · `tests/e2e/test_f4_ws.py` | `uv run pytest -m rnf09 --collect-only -q` lista **exatamente 4** testes agora (6 ao fim da Etapa 3); `uv run pytest -m e2e tests/e2e --collect-only -q` continua listando os 41 cenários F1-F5; `uv run pytest --collect-only -q` (default) não coleta nenhum deles | RNF-09 · ADR-022 · A-8 · TST-07 |

**Conclusão:** coleta correta nos três modos; nenhum teste executado ainda muda de resultado.

---

## Etapa 2 — Cenários de portabilidade (spec §9.2-L2: E2E-F6-01/02/03)

> Arquivo novo `tests/e2e/test_f6_portabilidade.py`. **Não existe E2E-F6-04**: a versão anterior da spec listava um cenário de `/api/health` degradado que contradizia a própria §1.2 (derrubar `redis`/`timescaledb` está fora da fase e a suíte proíbe `down`) — a prova de degradação é unitária, feita no F6a tarefa 3.2 (F6R-07). A numeração pula de 03 para 05 **de propósito**.

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 2.1 | **Fixture de projeto portátil + `E2E-F6-01` (export)**: fixture de módulo que monta, dentro de um projeto `RUN_ID`-suffixado, o material que os três cenários compartilham — **(a)** a conexão real com o opcsim (anônima, é a única que precisa subir), **(b)** uma conexão segura (`security_policy: basic256sha256` + `security_mode: sign_and_encrypt`, `auth_mode: user_password` com senha), **(c)** uma conexão `auth_mode: certificate` com `security_policy: none` (o caso que motivou o terceiro predicado, F6R-14), **(d)** duas conexões com **tag homônima** (mesmo `name` em conexões diferentes — o caso que motivou `tag_ref` ser objeto, TST-01) e **(e)** um flow MPC↔TFS a partir de `grafo_mpc_tfs`. `E2E-F6-01` exporta e assere: 200; **nenhum** `auth_password_enc`, `server_cert_file`, `id`, `project_id`, `connection_id`, `is_active`, `created_at`, `updated_at` em varredura **recursiva** do JSON; `tag_ref` objeto `{connection, tag}` nos 6 lugares (`opc_read.tag_id` e os 4 campos do `pid` de cada MV); `schema_version: 1`; `exported_at` presente; header `Content-Disposition: attachment; filename="<slug>.ottima.json"`; evento `project_exported` no barramento; **operador ⇒ 403** | `tests/e2e/test_f6_portabilidade.py` (novo) | `uv run pytest -m e2e tests/e2e/test_f6_portabilidade.py -v` verde; re-execução na mesma stack verde (sem colisão de nome) | RF-102 · A-14 · SEC-05 · TST-01 |
| 2.2 | **`E2E-F6-02` — ACEITE PRD §8-F6 (round-trip destrutivo, decisão A-9)**: exporta o projeto da fixture ⇒ **ativa a `SENTINELA`** (o backend recusa excluir o projeto ativo, `projects.py:70-72`, e não existe endpoint de desativar — é por isso que RF-102 foi emendado, A-14) ⇒ `DELETE` do projeto ⇒ **importa** o arquivo com nome novo ⇒ assere `is_active: false` (RF-103) e `pending_secrets` listando **as três** pendências ⇒ **re-informa a senha** (`PATCH /api/connections/{id}` com `auth_password`) ⇒ **re-confia o certificado do servidor** (`POST /api/connections/{id}/server-certificate` com um DER válido — o `.der` do certificado de aplicação, obtido de `GET /api/certificates/app/export` após `POST /app/generate`, serve como material X.509 real) ⇒ **ativa** o projeto importado ⇒ **deploya** o flow ⇒ assere flow `running` e `mpc.state` publicado com `vars` da malha. Prova de "instalação nova" sem violar a proibição de `up`/`down`: **os ids das tags novas são necessariamente maiores que os exportados** — `Identity(always=True)` não reaproveita valor após `DELETE` (cadeia de evidência no Anexo B da spec). Teardown restaura a sentinela como ativa | `tests/e2e/test_f6_portabilidade.py` | cenário verde duas vezes seguidas na mesma stack; ao final, banco sem resíduo do `RUN_ID` além da sentinela | **PRD §8-F6** · RF-102/103 · A-9 |
| 2.3 | **`E2E-F6-03` — recusas, com banco inalterado**: uma asserção por linha, cada uma seguida de conferência de que **nada** foi criado (contagem de projetos/conexões/tags/flows antes e depois): `schema_version: 2` ⇒ 422; `tag_ref` órfã (conexão/tag que não existe no arquivo) ⇒ 422 citando o nó; `exec_order` não contíguo ⇒ 422 (camada 4, `validate_graph`); **nome duplicado dentro do bundle** ⇒ 422 sem `IntegrityError`/500 (TST-04); nome de projeto colidindo com existente ⇒ **409**; corpo **> 4 MiB** ⇒ **413** (payload inflado por um campo `description` grande, enviado como stream); **operador ⇒ 403**. Confere também que o `detail` de recusa múltipla é **string única** partida por ` | ` e que um `node_id` com `;` (`ns=2;s=TT101`) sai íntegro na mensagem | `tests/e2e/test_f6_portabilidade.py` | verde; nenhuma recusa deixa linha no banco; nenhum 500 em nenhum caminho | RF-103 · A-5 · UX-06 · TST-04 |

**Conclusão:** `uv run pytest -m e2e tests/e2e -v` verde com 44 cenários (41 + 3).

---

## Etapa 3 — RNF-09: prova de dinâmica pela malha TFS (spec §7-2/3/5; decisão A-8 revista)

> **Por que cenários novos e não reescrita** (F6R-01): `grafo_mpc_tfs` é hardcoded para `_config_mpc_malha` (2 MVs / 1 CV) e o bloco TFS é travado em exatamente 2×2 por regra de parse (`parse.py:322-332`); o config pesado que garante o overrun é 4 MVs × 6 linhas (`test_f4_failure.py:65-66`) e **não cabe** na malha. O hot-swap prova "troca só quem mudou" com **dois** blocos MPC, sendo `mpc2` o irmão de controle, e `grafo_mpc_tfs` produz um único nó `mpc`. Reescrever `E2E-F4-06`/`E2E-F4-10` destruiria as provas existentes. **Nenhum cenário atual é tocado; dois nascem.**

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 3.1 | **`E2E-F6-05` — overrun pela malha TFS** (`@pytest.mark.rnf09`): MPC pequeno de `grafo_mpc_tfs`, com o **orçamento estreitado** e o horizonte elevado **sem tocar a fixture** — o cenário parte do dict devolvido e sobrescreve `multiplier = 1` (⇒ `Ts_mpc = Ts = 0,5 s`, o mínimo) e o `tss` das linhas para elevar `Np` até perto do teto de 120; o flow é criado com `ts_seconds=0.5` (`criar_flow_mpc(..., ts_seconds=0.5, grafo=…)`). Arma até AUTO e mede uma janela de N varreduras. **Critério é o comportamento do RF-624, nunca um número inventado**: MV **inalterada entre execuções** enquanto a planta TFS **continua evoluindo** (é a dinâmica que o `NODE_SINE` do `E2E-F4-06` não mostra), `mpc_overrun` emitido, **contador `payload["overruns"]` somando** (F6a §5.1) e **sem acumular fila** (um solve em voo por vez). **Contingência declarada (§7-5):** se o overrun não for reproduzível de forma determinística na malha pequena — o solve lento arrasta o próprio flow, o que muda o regime —, o cenário **reduz o escopo para a asserção de dinâmica** (MV constante enquanto a planta evolui, medida ao longo de N varreduras) e a prova de orçamento/contador permanece integralmente em `E2E-F4-06`. **O que NÃO é aceitável é afrouxar a asserção do `E2E-F4-06`.** A decisão tomada (critério cheio ou contingência) é registrada no ledger com a evidência que a motivou | `tests/e2e/test_f6_rnf09.py` (novo) | `uv run pytest -m rnf09 -v` verde; a série de MV lida do `mpc.state` é constante na janela enquanto a série de CV varia (prova de planta viva); `grafo_mpc_tfs` e `_config_mpc_malha` **byte a byte inalteradas** (`git diff` vazio em `conftest.py` nessas funções) | RNF-09 · RF-624 · A-8 · F6R-01 |
| 3.2 | **`E2E-F6-06` — hot-swap pela malha TFS** (`@pytest.mark.rnf09`): flow MPC↔TFS rodando e armado; captura a série de CV (que é `planta.y1`, saída da TFS) por uma janela; **troca a config do MPC com a planta viva** (`PUT /api/flows/{id}` alterando só o bloco `mpc` — peso/limite, mantendo a TFS e o Script idênticos), o que dispara `_reload`/`reconcile_mpc_hosts`; captura a série depois. Prova: **o estado da planta sobrevive** — a CV continua a trajetória sem salto para o valor inicial (a TFS não foi reconstruída, ADR-011: só quem mudou ganha host novo) — e o MPC volta a publicar estado com a config nova. Complementa `E2E-F4-10`, que continua provando "só quem mudou" com o irmão de controle e **fica intacto** | `tests/e2e/test_f6_rnf09.py` | `uv run pytest -m rnf09 -v` verde com **6** testes (4 da F4 + 2 novos); a emenda das duas séries de CV não tem descontinuidade acima da variação natural da janela; `test_f4_ws.py` inalterado | RNF-09 · ADR-011 · A-8 |

**Conclusão:** `uv run pytest -m rnf09 -v` verde (6); `uv run pytest -m e2e tests/e2e -v` verde com **46** cenários (41 + 5).

---

## Etapa 4 — Ambiente L3 e roteiro de browser (spec §9.2-L3)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 4.1 | **`scripts/setup-l3.py` estendido**, mantendo a idempotência ponto a ponto ("busca por nome ⇒ cria se ausente") e **sem alterar** o que já entrega (projeto ativo `L3 F5 operacao`, conexão `opcsim-l3`, flow `L3-flow-operacao` com `mpc1`, usuário `operador_e2e`/`OperadorE2E#2026`): passa a criar também **(a)** um **projeto extra inativo** `L3 F6 portabilidade` para os cenários de export/import do roteiro (B-F6-05/06), **(b)** uma conexão `auth_mode: certificate` com `security_policy: none` e uma conexão **segura sem senha reinformada** (`basic256sha256` + `sign_and_encrypt` + `user_password` sem `auth_password`) apontando para o **mesmo endpoint do opcsim** (`OPCSIM_URL`, `tests/e2e/conftest.py`) — material das três pendências de B-F6-07 e da subida real de B-F6-04 depois do trust, **(c)** **duas conexões com tag homônima** (mesmo `name` de tag em conexões diferentes) e **(d)** um flow `L3-flow-arquivo` nesse projeto com **um bloco `opc_read` apontando para uma das tags homônimas** e **um bloco Script** com código conhecido (`OUT1 = 0.0`) — sem esse flow o roteiro não teria material determinístico nem para o `tag_ref` objeto do export (B-F6-05) nem para a lista de blocos Script da prévia do import (B-F6-06), e o cenário teria de improvisar setup pela UI. O flow nasce **parado** (`desired_state: stopped`, nunca deployado — o projeto é inativo e nada nele deve escrever em planta). O projeto ativo ao final **continua sendo** `L3 F5 operacao` (o roteiro começa na operação). O JSON de resumo em stdout ganha os ids novos | `scripts/setup-l3.py` | `uv run python scripts/setup-l3.py` duas vezes seguidas ⇒ mesmo resumo, zero duplicata; `GET /api/projects` mostra os dois projetos com o de F5 ativo; `GET /api/flows?project_id=<L3 F6>` mostra `L3-flow-arquivo` parado, com `opc_read` e `script` no grafo |
| 4.2 | **Roteiro L3 `docs/plans/tests-e2e-f6.md`** — os **13** cenários B-F6-01..13 da tabela §9.2-L3, escritos no formato dos roteiros F4/F5 (precondições de ambiente, regras da tool `browser` herdadas de `docs/plans/tests-e2e-f4.md` §2 **integralmente**, diretório de evidências, um screenshot por passo, seção "o que este roteiro NÃO cobre", ordem de gate). Redigido por agente especialista em E2E a partir **destes três planos** e da spec, e **revisado e aceito pelo controlador** antes de virar normativo — mesmo rito do roteiro da F5 | `docs/plans/tests-e2e-f6.md` (novo) | cada cenário B-F6-nn cita a tarefa do F6a/F6b que o entrega e os `data-testid` da convenção da fase (`proj-*`, `import-*`, `cert-*`, `conn-pendencia*`); nenhum passo delegável a subagente | §9.2-L3 |

**Conclusão:** ambiente L3 reprodutível por um comando; roteiro aceito.

---

## Etapa 5 — Guia de implantação e comissionamento (spec §8; PRD §9-5; decisão A-12)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 5.1 | **`docs/IMPLANTACAO.md`**, público-alvo: o engenheiro de APC que implanta o OttimaSystem numa planta de cliente. Cada passo ancorado no RF/ADR que o governa. **Seis seções, verbatim de §8:** (1) **Instalação e primeiro boot** — pré-requisitos de host, `deploy/.env` a partir de `deploy/.env.example`, **geração manual** de `OTTIMA_SECRET_KEY` e `OTTIMA_FERNET_KEY` (`.env.example:18,22`, com os comandos que o próprio arquivo já documenta), `docker compose up -d --build`, 7 serviços, admin do seed, verificação por `/api/health` (agora com `redis_ok`/`db_ok`, F6a §3.3) e pela Home; registra que a geração dos segredos é manual **por decisão** (§1.2), não pendência. (2) **Identidade e confiança** — gerar o certificado de aplicação pela chapa nova (F6b §6.2), exportar o `.der` para a trust list do servidor OPC, confiar no certificado do servidor pela UI, o que cada modo de segurança exige, e a exigência de o `applicationUri` casar com `urn:ottima:opc-worker` (`ottima_core/certs.py`). (3) **Pré-requisitos do PID por malha** — o coração do §9-5: por modo-alvo, **RCAS/CAS exigem SP-tracking** e **ROUT exige OUT-tracking**; tags obrigatórias por MV (escrita, comando de modo, readback) e a opcional (leitura de modo), os valores de `mode_values`, e a consequência de cada uma faltar; explicita o que o sistema **não** faz — em LOCAL não escreve MV, no boot não reassume malha, em falha de comunicação cessa escrita e para o flow. (4) **Comissionamento passo a passo até AUTO** — projeto, conexão, tags, flow, blocos, `exec_order`, TSS e horizontes, deploy, LOCAL (tracking observado), REMOTO, MAN, AUTO; checklist por etapa com o que olhar na tela de operação e em `/eventos`. (5) **Transporte de engenharia entre plantas** — export/import, o que o arquivo **não** carrega e por quê (§2.3, os três motivos: segredo, ambiente-específico, id), o procedimento de re-informar segredos, e uma seção sobre **proveniência**: arquivo de origem desconhecida traz código Python que **executará no servidor**; conferir os blocos Script na prévia do import antes de confirmar (§2.3 nota, §6.1-6). (6) **Operação contínua e limites conhecidos** — retenção de 1 mês (ADR-003), backup do Postgres como **procedimento manual** (`pg_dump` do volume `pgdata`, sem prometer automação — §1.2), não-objetivos da v1 (PRD §1). Vocabulário do GLOSSARY: **"arquivo de projeto"**, nunca "bundle"; sem emojis | `docs/IMPLANTACAO.md` (novo) | todo comando do guia executado ao menos uma vez contra o stack real durante a redação (nenhum passo "provável"); toda tela citada existe no bundle atual do frontend; `grep -in "bundle" docs/IMPLANTACAO.md` ⇒ nada | PRD §9-5 · A-12 · A-15 |

**Conclusão:** guia completo, com todos os comandos conferidos.

---

## Etapa 6 — Gate final da fase F6 (spec §9.2/§9.3)

| # | Tarefa | Verificar | Governança |
|---|---|---|---|
| 6.1 | **Rodada de gate completa**, na ordem abaixo, **na mesma rodada**. Qualquer vermelho em qualquer linha interrompe a rodada: corrigir e **reiniciar a rodada inteira** (nunca re-executar só o que falhou; `down -v` **só com autorização explícita + dump prévio**) | tudo verde; evidências em `.superpowers/sdd/F6-portabilidade/evidencias-gate/` | spec §9.3 |
| | 1. `uv run pytest` (workspace, incluindo `-m slow` uma vez) + `uv run ruff check . && uv run ruff format --check .` | 100% verde, zero warning de lint | |
| | 2. `cd frontend && npm run build && npm run test:unit` | build sem erro de tipo; checks puros verdes (predicados de pendência, partição do `detail`, primitivos de arquivo, `output_eu`, faceplate de DV, paleta de 8, chaves invalidadas, tique de TTL) | |
| | 3. **L1** — `OTTIMA_E2E=1 bash deploy/smoke.sh` (flow-runtime recém-subido; se a L2 já rodou, `docker compose … restart flow-runtime` antes) | smoke completo, incluindo `/api/health` com `redis_ok`/`db_ok` e `status: ok` | |
| | 4. **L2** — `E2E_ADMIN_USERNAME=… E2E_ADMIN_PASSWORD=… uv run pytest -m e2e tests/e2e -v` (credenciais inline de `deploy/.env`) | **46/46** verdes (41 herdados de F1-F5 + `E2E-F6-01/02/03/05/06`) | |
| | 5. **Suíte RNF-09** — `uv run pytest -m rnf09 -v` | **6/6** verdes (`E2E-F4-03/05/06/10` + `E2E-F6-05/06`) — prova que o marcador seleciona a suíte inteira do aceite | |
| | 6. **Playwright F1** — `cd frontend && npm run e2e` (credenciais inline; **serializado** com a L2) | regressão F1 verde | |
| | 7. **L3** — roteiro `docs/plans/tests-e2e-f6.md` **inteiro**, executado pelo **controlador** com a tool `browser`, screenshot por passo | B-F6-01..13 verdes, evidências completas | |
| 6.2 | **Encerramento da fase e da v1**: CLAUDE.md §Comandos atualizado (L2 = 46 cenários; `uv run pytest -m rnf09`; rotas e telas novas); relatório de gate `.superpowers/sdd/F6-portabilidade/RELATORIO-GATE-F6.md` (template F3/F4/F5); **revisão ampla da branch** (leitura de conjunto além do gate, padrão F3/F5); débitos que sobrevivem à v1 registrados como tal no `docs/reports/_tech-debt.md` (**TD-001** segredos do `.env` no processo que executa Script — impacto reduzido por F6a §3.3, sandbox forte fora da v1; **TD-002** validação CPU-bound do import bloqueando o worker uvicorn que também serve `/ws`); merge `--no-ff` na `main` **após aceite explícito do usuário** | relatório completo; revisão sem Critical/Important aberto; débitos registrados | CLAUDE.md §Workflow |

---

## Aderência ao aceite F6 (PRD §8) — Definition of Done da FASE

| Critério de aceite | Onde é provado |
|---|---|
| Export em JSON com `schema_version`, sem histórico e sem segredos (RF-102 emendado) | `E2E-F6-01` (2.1) · B-F6-05 · F6a 1.1/1.3/2.2 |
| Import com validação, criando projeto **inativo** (RF-103) | `E2E-F6-03` (2.3) · B-F6-06/08 · F6a 2.3 |
| **Projeto exportado importa limpo em instalação nova** | **`E2E-F6-02` (2.2)** — round-trip destrutivo, ids de destino necessariamente maiores (A-9) · B-F6-01/02/06 (sem a tela de Projetos o aceite é inatingível pela UI) |
| **Re-informando segredos** | `E2E-F6-02` (2.2, as 3 pendências resolvidas) · B-F6-07 · F6b 1.4/4.1 |
| Gestão de certificados (RF-202) | B-F6-03/04 · F6b 3.1/3.2 |
| Health/heartbeats (RNF-07) | L1 (6.1 linha 3) · F6a 3.1/3.2 e seus testes unitários |
| **Suíte MPC↔TFS verde** (RNF-09) | 1.1 (marcador) · 3.1/3.2 (prova de dinâmica pela TFS) · 6.1 linha 5 (`-m rnf09` 6/6) |
| Guia de integração (PRD §9-5) | 5.1 |

**A fase — e a v1 — só encerram com a rodada de gate da Etapa 6 inteira verde**, incluindo o roteiro browser completo de `docs/plans/tests-e2e-f6.md`.

## Rastreabilidade (RF/decisão por tarefa)

| Norma | Tarefas |
|---|---|
| RF-102 / RF-103 (portabilidade) | 2.1, 2.2, 2.3 |
| RF-202 (certificados) | 4.2 (B-F6-03/04), 5.1 §2 |
| RF-624 (overrun do MPC) | 3.1 |
| RNF-07 (observabilidade) | 6.1 linha 3 |
| RNF-09 (validação MPC↔TFS) | 1.1, 3.1, 3.2, 6.1 linha 5 |
| PRD §8-F6 (aceite) | 2.2, 6.1 |
| PRD §9-5 (guia) | 5.1 |
| ADR-003 · ADR-011 · ADR-018 · ADR-022 | 5.1 §6 · 3.2 · 5.1 §5 · 1.1, 3.1, 3.2 |
| Decisões A-5/A-8/A-9/A-12/A-13/A-14/A-15 | 2.3 / 1.1+3.1+3.2 / 2.2 / 5.1 / 4.1 / 2.2 / 5.1 §5 |
| F6R-01/07/14 · TST-01/04/07 · SEC-05 · UX-06 | 3.1 / 2.x (nota da Etapa 2) / 2.1 · 2.1 / 2.3 / 1.1 · 2.1 · 2.3 |
