# Spec F2 — Aquisição

**Fase:** F2 (PRD §8) · **Status:** aprovado seção a seção em sessão de brainstorm · 2026-08-03
**Fontes normativas:** `docs/PRD.md` (RF/RNF, contratos §7, fases §8) · `docs/adr/ADR-001…023` (prevalecem em conflito) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (frontend) · `docs/specs/F1-fundacao.md` (vinculante)
**Convenção de rastreabilidade:** cada decisão cita o RF-xxx/ADR-nnn/spec-F1 que a governa; decisões sem cobertura nos documentos estão marcadas **[NOVA — implementação]** e foram aprovadas pelo usuário nesta sessão (Anexo A).

Este documento especifica **implementação**. Ele não redefine produto, arquitetura nem visual; onde repete conteúdo normativo, é citação.

---

## 1. Escopo da F2

**Entrega (PRD §8-F2):** opc-worker (3 modos de segurança), barramento, recorder, watchdog.
**Aceite (PRD §8-F2):** leituras de servidor real chegam ao trend · bit de watchdog alternando · queda ⇒ alarme em <12 s e bloqueio de escrita.

### 1.1 Dentro da F2

| Item | Governança |
|---|---|
| opc-worker completo: sessões asyncua (≤5), reconciliação de config (banco + dica via `events`), subscriptions com heartbeat de valor, reconexão com backoff, semântica de desconexão (quality=bad) | RF-201/204 · ADR-002/006 · §2 |
| Watchdog por conexão (toggle NOT, congelamento >10 s), gate de escrita, eventos `comm_failure`/`comm_restored`, contrato de parada de flows para a F3 | RF-206/207 · ADR-009 · RNF-03 · §3 |
| Consumo de `opc.writes` + evento de auditoria por escrita | RF-205 · ADR-020 · §4 |
| Certificados via API: gerar/exportar certificado de aplicação, trust do certificado do servidor (pinning) — UI fica na F6 | RF-202 · ADR-021 · spec F1 §1.2 · §5 |
| recorder: `samples` + `events` na hypertable, batching/backpressure | RF-801 · ADR-003 · §6 |
| Publisher do canal `events` + auditoria da API (ativação de projeto, CRUD de conexão/tag) — pendência herdada | spec F1 §6.3 · ADR-020 · §7 |
| `GET /api/events` (metade API do RF-803; UI do log fica na F5) | RF-803 · **[NOVA — implementação]** · §7.4 |
| `GET /api/history` com downsampling (bruto ≤2 h; agregado acima) | RF-802 · §8 |
| Frontend: telas CRUD de **conexões/tags** ("comissionamento", herança vinculante) + **trend mínimo de engenharia** (uPlot) + paleta de penas | spec F1 §1.2/§8.1 · §9 |
| Simulador OPC-UA próprio (`opcsim`) + gate E2E em 3 camadas | CLAUDE.md §Testes · §10/§11 |
| **Validação E2E dirigida pelo agente via tool `browser` do harness**: o plano `docs/plans/F2-aquisicao.md` DEVE conter tarefas explícitas de teste E2E executadas com a tool `browser`, com evidência visual por tarefa de UI | **[NOVA — implementação]** exigência do usuário (2026-08-03) · §11 |
| Compose: `OTTIMA_DATABASE_URL` no opc-worker; dependência nova única: `asyncua` (stack declarada, PRD §10) | ADR-023 · §10 |

**Zero migration nova:** o DDL da F1 já cobre a F2 (`samples`, `events`, CAgg, colunas de watchdog/segurança em `opc_connections`).

**Nota metodológica:** cada tarefa do plano que entrega superfície de UI ou comportamento observável fim-a-fim termina com passo de validação via tool `browser` contra o stack composto — não apenas na rodada final de gate. Na F2, a tool `browser` **substitui** o Playwright para as superfícies novas (decisão do usuário; a suíte Playwright da F1 permanece como regressão — §11).

### 1.2 Fora da F2 — com destino registrado

| Item | Destino | Governança |
|---|---|---|
| Consumo de `opc.values.*`/`flow.commands` pelo flow-runtime; parada efetiva de flows em falha | F3 (contrato do evento fixado em §3.7) | RF-207 · ADR-006 |
| WebSocket `/ws` (valores ao vivo, eventos → faixa anunciadora com dados reais) | F5 | PRD §7.3 · spec F1 §8.4 |
| UI de gestão de certificados | F6 | PRD §8 |
| UI do log de eventos (filtros RF-803) | F5 | RF-803 |
| Browse do address space | Adiado; segue "desejável" (reavaliar na F3) | RF-203 |
| `/operate`, tela de operação | F5 | PRD §8 |
| Heartbeat de workers visível na UI | F5 | RNF-07 |
| Produtores de `opc.writes` em produção (flow-runtime, api `/operate`) | F3/F5 — na F2 o lado consumidor é exercitado via barramento nos testes | PRD §7.1 |

A tela de trend da F2 consome `GET /api/history` por **polling** (sem WS); "ao vivo" de verdade chega com o WS na F5. **[NOVA — implementação]**

---

## 2. opc-worker — arquitetura interna

### 2.1 Mapa de módulos (referência; caminhos exatos no plano)

```
services/opc-worker/src/ottima_opc_worker/
  main.py           # FastAPI /health + lifespan: sobe o Supervisor
  supervisor.py     # reconciliação banco→sessões; 1 ConnectionRuntime por conexão ativa
  connection.py     # ConnectionRuntime: sessão asyncua, máquina de estados, backoff
  subscriptions.py  # monitored items (tags R) → publica opc.values.<conn_id>
  heartbeat.py      # republicação periódica de valor (10 s)
  watchdog.py       # task do watchdog por conexão (§3)
  writes.py         # consumidor de opc.writes (§4)
  security.py       # montagem de set_security / identidade de usuário (§5)
  state.py          # snapshot em memória: últimos valores, estados p/ health
```

### 2.2 Decisões

1. **Supervisor/reconciliação:** fonte da verdade = banco via `ottima-core`. A cada **10 s**, watermark (`max(updated_at)` + `count`) de `projects`/`opc_connections`/`tags` do **projeto ativo** (ADR-017; sem projeto ativo ⇒ zero sessões); diff ⇒ criar/derrubar/reconfigurar runtimes. Granularidade: mudança em campos da **conexão** ⇒ recria a sessão; mudança só no conjunto de **tags** ⇒ recria apenas a subscription. Assina `events` e usa os kinds de auditoria da API (§7.2) como gatilho imediato do mesmo reconcile — dica; perda de mensagem é inofensiva (poll corrige). **[NOVA — implementação]**
2. **Máquina de estados por conexão:** `connecting → up → failed → connecting…`; backoff exponencial **1→2→4→…→30 s (teto) + full jitter**; falha dura (connect recusado, timeout, exceção de sessão) ⇒ `failed` imediato + evento (§3.6) — os 10 s do watchdog são só para congelamento silencioso. **[NOVA — implementação]** (parâmetros) · ADR-009/RF-207 (semântica)
3. **Sessão asyncua:** 1 `Client` por conexão (≤5, RF-201); senha decifrada (Fernet) só em memória no connect (spec F1 §5.4).
4. **Mapeamento tag→node_id:** monitored items **apenas para `direction='r'`** (RF-204 publica *leituras*; readback de MV é tag R própria — RF-604). Node inexistente/inválido ⇒ quality=bad para essa tag + evento warning `tag_subscribe_error` (1ª ocorrência), **sem** derrubar a conexão. **[NOVA — implementação]**
5. **Subscription:** 1 por conexão; `publishing_interval = sampling = 250 ms`, `queue_size = 1` (dado cíclico: o mais recente vence; 250 ms = metade do menor Ts da F3). Handler: StatusCode OPC → quality `0/1/2` (Good/Uncertain/Bad — spec F1 §3.4-4); publica `OpcValue` (payload §7.1 verbatim, tipado em `ottima_core.bus`) e atualiza o snapshot. **[NOVA — implementação]** (parâmetros)
6. **Heartbeat de valor:** a cada 10 s republica cada tag sem publicação há ≥10 s (mesmo valor/qualidade, ts novo) — padrão report-by-exception + heartbeat; piso ≈864k linhas/dia no teto do RNF-01 (folgado). Conexão em falha ⇒ heartbeat segue com `quality=2` para todas as tags dela (valor = último conhecido; sem último ⇒ `0.0`, irrelevante sob bad). Na detecção da falha, rajada imediata de quality=bad para todas as tags da conexão. Na reconexão, o datachange inicial da subscription restaura os valores. **[NOVA — implementação]**
7. **Timestamps/serialização:** `ts` = SourceTimestamp do servidor → ServerTimestamp → `now()` UTC, nessa ordem; ISO-8601 UTC no JSON; `value` float (bool→0/1, int→float — `samples.value` é DOUBLE PRECISION, spec F1 §3.2). **[NOVA — implementação]**
8. **`/health` (RNF-07):** `{status, service, version, connections:{<id>:{name, state, watchdog_alive, session_up_since, last_publish_ts, tags_subscribed, monitored_errors, write_errors}}}`. **`status` reflete só as dependências do serviço (Redis/banco)** — conexão OPC caída é condição operacional (alarme), **não** unhealth do serviço: o healthcheck do compose não pode reiniciar o worker porque um PLC está desligado. **[NOVA — implementação]**

---

## 3. Watchdog e política de falha

1. **Task por conexão** (só quando o par de node_ids está configurado), cadência = `watchdog_period_ms` (500–5000 ms, default 1500 — DDL F1). Ciclo: `read` **explícito** do bit de leitura → se mudou, registra transição → escreve `NOT(valor lido)` no bit de escrita. Leitura explícita, não subscription: congelamento medido deterministicamente. (ADR-009, RF-206)
2. **Detecção de congelamento:** `now − última_transição > 10 s` ⇒ falha `watchdog_timeout`. Limiar **fixo** (ADR-009); só o período de toggle é configurável. Exceção no read/write do próprio watchdog = falha dura ⇒ imediata (§2.2-2).
3. **`watchdog_alive`** começa `false` e só vira `true` na **1ª alternância observada** após (re)conexão — sessão zumbi nunca escreve.
4. **Gate de escrita stateless** (RNF-03 decomposto: deploy → flow-runtime · watchdog vivo → gate do worker · REMOTO → bloco MPC): escrita de `opc.writes` executa ⇔ sessão `up` ∧ `watchdog_alive`. Reabre sozinho na recuperação; **não trava em latch** — o latch de retomada é dos flows (deploy manual, RF-207/F3); se o worker também travasse, um flow re-deployado teria escritas silenciosamente descartadas. Escritas do próprio watchdog **bypassam o gate** (senão deadlock). **[NOVA — implementação]** (decomposição)
5. **Conexão sem watchdog** (par vazio): `watchdog_alive` permanece `false` ⇒ read-only de fato; `opc.writes` para ela ⇒ **drop + evento warning**, deduplicado (1ª ocorrência por conexão, re-armado em reconfiguração). Enforcement só no runtime — CRUD não interfere; a tela de conexões apenas avisa (§9.1). **[NOVA — implementação]**
6. **Eventos de transição** (edge-triggered; `origin="conn:<id>"`, campo `kind` no payload — **[NOVA — implementação]**):
   - `comm_failure` — severity=`alarm`, payload `{kind:"comm_failure", conn_id, reason:"watchdog_timeout"|"session_lost"|"connect_failed"|"cert_mismatch"|"cert_missing", detail}`. Emitido **na transição** para `failed`; tentativas de reconexão em backoff **não** re-emitem. (`cert_*`: §5.6)
   - `comm_restored` — severity=`info`, payload `{kind:"comm_restored", conn_id}`. Emitido quando sessão volta **e** watchdog alterna de novo (conexão sem watchdog: sessão `up` basta).
7. **Contrato para a F3** (registrado aqui, consumido lá): flow-runtime assina `events`; `kind=comm_failure` ⇒ para os flows que usam tags da conexão; retomada exige deploy manual (RF-207). Perda do evento é coberta por: gate do worker (segurança absoluta — nenhuma escrita passa) + boot-parado (ADR-017).
8. **Orçamento do aceite:** `watchdog_timeout` detectado em ≤10 s + emissão imediata ⇒ alarme **<12 s** com folga; falhas duras alarmam em ~0 s. Bloqueio de escrita é simultâneo à detecção (mesma transição de estado).

---

## 4. Escritas (`opc.writes`) e auditoria

1. **Consumidor:** o worker assina `opc.writes` (canal fixo §7.1); payload `OpcWrite` `{conn_id, tag_id, value, source, ts}` — tipado em `ottima_core.bus` (F1), verbatim do PRD. Roteia por `conn_id` para o runtime da conexão.
2. **Pipeline de validação** (nesta ordem; reprovado ⇒ descarte, nunca exceção no loop):
   a. `conn_id` pertence ao projeto ativo e tem runtime? não ⇒ drop + warning `write_rejected` (dedupe);
   b. `tag_id` existe, pertence à conexão e `direction='w'`? não ⇒ drop + warning `write_rejected`;
   c. **gate §3.4** (sessão `up` ∧ `watchdog_alive`)? não ⇒ drop + evento warning `write_blocked` — **deduplicado por conexão por período de falha** (senão flood na cadência do MPC); cumpre o "cessam imediatamente" do RF-207;
   d. executa a escrita no node.
3. **Coerção de tipo:** no setup da conexão o worker lê o atributo `DataType` de cada node de tag `w` (1×, cacheado) e converte o `value` float do payload para o **VariantType real do servidor** (Int16/Int32/Float/Double/Boolean…) — escrever Int64 num node Int32 dá `BadTypeMismatch`. `tags.data_type` valida a intenção do engenheiro; o VariantType do servidor decide a codificação. Fallback (DataType ilegível): float→Double, int→Int32, bool→Boolean. Bool: `value != 0.0`. **[NOVA — implementação]**
4. **Auditoria (RF-205 verbatim — toda escrita gera evento):**
   - sucesso ⇒ `info`, origin = `source` do payload (ex.: `flow:3/block:opcw1`, `user:2`), payload `{kind:"opc_write", conn_id, tag_id, value, status:"ok"}`;
   - falha de execução (timeout, `BadTypeMismatch`, node não escrevível) ⇒ `warning`, `{status:"error", detail}`, contada em `write_errors` no `/health`.
   - Volume registrado como consequência aceita: com OPC-Write a cada varredura (RF-502, Ts mínimo 0,5 s), o teto teórico é ~10 ev/s ⇒ ~26 M linhas/mês — dentro do que a hypertable `events` (chunk 7 d, retenção 1 mês) suporta; RF-803 filtra por severidade/origem. Reduzir isso tocaria o RF-205 — não se faz.
5. **Na F2 não há produtor de `opc.writes` em produção** (flows→F3, `/operate`→F5); o consumidor é exercitado nos testes publicando no canal — a interface contratual (§1.2).

---

## 5. Segurança OPC-UA e certificados (RF-201/202, ADR-021)

1. **Mapeamento dos 3 modos** (por conexão, colunas F1):

   | `security_policy`/`security_mode` | asyncua |
   |---|---|
   | `none`/`none` | sem `set_security` |
   | `basic256sha256`/`sign` | `set_security(Basic256Sha256, app.pem, app.key, server_certificate=trusted, mode=Sign)` |
   | `basic256sha256`/`sign_and_encrypt` | idem, `mode=SignAndEncrypt` |

2. **Identidade de usuário** (independente do canal): `anonymous` (default) · `user_password` (senha Fernet decifrada em memória — spec F1 §5.4) · `certificate` = **reutiliza o par do app** como user token X.509 (certs de usuário por conexão não compram nada na v1). Combinações que o servidor recusar viram `connect_failed` com `detail` — sem validação extra nossa. **[NOVA — implementação]**
3. **Certificado de instância de aplicação** (único — ADR-021: "seu certificado", singular) — gerado pela **api** (volume `certs` RW; worker RO — compose F1) com `cryptography` (dep existente do core): RSA 2048 · SHA-256 · validade **10 anos** · `CN=OttimaSystem opc-worker` · **SAN URI `urn:ottima:opc-worker` = ApplicationUri do Client asyncua** (obrigatório casar, senão `BadCertificateUriInvalid`) · keyUsage digitalSignature/nonRepudiation/keyEncipherment/dataEncipherment · extKeyUsage clientAuth+serverAuth (praxe de interoperabilidade OPC-UA). Chave PEM sem passphrase no volume (risco aceito coerente com HTTP interno, ADR-023). **[NOVA — implementação]** (parâmetros)
4. **Layout do volume:** `/certs/app/ottima.pem` + `ottima.key` + `ottima.der` (export) · `/certs/trusted/conn-<id>.der` (coluna `server_cert_file` guarda o nome do arquivo — DDL F1). Chaves privadas **nunca** no banco (ADR-021/spec F1 §5.4).
5. **Endpoints (admin):**
   - `POST /api/certificates/app/generate` — body `{force: bool=false}`; existe e sem force ⇒ `409`; retorna metadados;
   - `GET /api/certificates/app` — `{exists, subject, fingerprint_sha256, not_before, not_after, application_uri}`;
   - `GET /api/certificates/app/export` — download do `.der` (para trust list do servidor);
   - `POST /api/connections/{id}/server-certificate` — upload DER/PEM (normaliza p/ DER), grava `trusted/conn-<id>.der`, seta `server_cert_file`; `DELETE` remove arquivo + limpa coluna.
6. **Pinning obrigatório:** `policy≠none` sem `server_cert_file` ⇒ conexão **não sobe**: estado `failed`, evento `comm_failure` com `reason="cert_missing"` (upload só é possível após criar a conexão — exigência é de runtime, não do CRUD). Handshake com certificado divergente do pinado ⇒ `cert_mismatch` (asyncua falha o handshake; a exceção é mapeada).
7. **Regeneração do app cert** invalida trusts existentes nos servidores — o response do `generate` com `force=true` retorna aviso explícito (re-trust manual nos servidores). **[NOVA — implementação]**

---

## 6. recorder (RF-801, ADR-003)

1. **Assinaturas:** `psubscribe opc.values.*` + `subscribe events` (ADR-002: adicionar consumidor = assinar canal). O recorder é *dumb pipe*: não interpreta nem filtra — grava o que chega. Amostra de tag órfã grava mesmo assim (`samples.tag_id` sem FK — spec F1 §3.4-2; órfãos expiram pela retenção).
2. **Pipeline de samples:** parse `OpcValue` → linha `(ts, tag_id, value, quality)`; buffer em memória; **flush a cada 1 s ou 1000 linhas** (o que vier antes) via `insert().values(batch)` (executemany asyncpg). Teto RNF-01 com heartbeats ≈ 200–400 msg/s — folga ampla. **[NOVA — implementação]** (parâmetros)
3. **Pipeline de eventos:** parse `EventMessage` → linha da hypertable `events`; **buffer separado** (10k) com flush no mesmo ciclo, **antes** das samples (auditoria tem prioridade). **[NOVA — implementação]**
4. **Backpressure:** fila de samples limitada a **100k**; overflow ⇒ **drop-oldest** (dado cíclico: fresco > velho; bloquear estouraria o buffer de saída do Redis e derrubaria a subscription) + contador. Log estruturado imediato; evento `recorder_backpressure` (warning, total descartado) emitido **na recuperação do flush** — emitir durante a indisponibilidade só encheria o outro buffer. Overflow do buffer de eventos (patológico): drop-oldest + log crítico. **[NOVA — implementação]**
5. **Resiliência:** banco indisponível ⇒ retry do flush com backoff (1→30 s), buffers seguram; payload malformado ⇒ log + descarte (contador); Redis caiu ⇒ reconecta, perda aceita (RNF-05).
6. **`/health`:** `{status, buffered_samples, buffered_events, dropped_total, last_flush_ts, db_ok}` — `status` segue a semântica §2.2-8 (dependências do serviço).

---

## 7. Canal `events`: publisher e auditoria da API

1. **Publisher canônico em `ottima-core`** (`bus.py` ganha `publish_event(...)`): única forma de emitir; todos os serviços usam. **[NOVA — implementação]**
2. **Emissões da API na F2** (pendência herdada do spec F1 §6.3; todas `info`, `origin="user:<id>"`): `project_activated` — payload `{kind, project_id, name}` · `connection_created|updated|deleted` — `{kind, conn_id, project_id, name}` · `tag_created|updated|deleted` — `{kind, tag_id, conn_id, name}`. São simultaneamente a **dica de reconciliação** do worker (§2.2-1) — um mecanismo só. CRUD de users e de projects sem efeito operacional: sem evento.
3. **Vocabulário `kind` consolidado da F2** (tabela normativa; consumidores fazem match por `kind`, nunca por `message`; mensagens em pt-BR, para humanos — RNF-08): **[NOVA — implementação]**

   | `kind` | severity | origem | ref |
   |---|---|---|---|
   | `comm_failure` / `comm_restored` | alarm / info | opc-worker | §3.6 |
   | `opc_write` | info (ok) / warning (erro) | opc-worker | §4.4 |
   | `write_blocked` / `write_rejected` | warning | opc-worker | §4.2 |
   | `tag_subscribe_error` | warning | opc-worker | §2.2-4 |
   | `recorder_backpressure` | warning | recorder | §6.4 |
   | `project_activated` · `connection_*` · `tag_*` | info | api | §7.2 |

4. **`GET /api/events`** **[NOVA — implementação; adição de escopo aprovada]:** o aceite "queda ⇒ alarme <12 s" precisa ser *consultável* e o gate L2 precisa de superfície limpa (sem SQL nos testes). Entrega a metade API do RF-803 (a UI do log fica na F5): `GET /api/events?severity=&origin=&start=&end=&limit=` (default 100, máx 1000, ts desc), papel `require_operator` (ADR-015: operador enxerga tudo).

---

## 8. API de histórico (RF-802)

- `GET /api/history?tag_ids=1,2&start=<iso>&end=<iso>` — papel `require_operator`; defaults `end=now`, `start=now−1h`; validações: `start<end`, janela ≤ 31 d (retenção), **≤ 6 tags** por chamada (= penas do trend, §9.3); erros 422 pt-BR (padrões F1 §6.1, sem paginação). **[NOVA — implementação]** (forma)
- **Downsampling automático (RF-802):** janela ≤ 2 h ⇒ bruto de `samples`; > 2 h ⇒ CAgg `samples_1m` (`avg/min/max/worst_quality` — spec F1 §3.3).
- **Resposta colunar** (uPlot-friendly) **[NOVA — implementação]**:

```json
{"mode": "raw",
 "start": "…", "end": "…",
 "series": [{"tag_id": 1,
             "t": ["…"], "v": [0.0], "q": [0]}]}
```
`mode="1m"` acrescenta `"v_min": []` e `"v_max": []` por série (`v` = avg, `q` = worst_quality).

---

## 9. Frontend (autoridade: PRODUCT.md/DESIGN.md)

### 9.1 Telas de comissionamento (herança spec F1 §1.2)

- **`/engenharia/conexoes`** — tabela em chapa (nome, endpoint, policy/mode/auth, watchdog, `has_password`); coluna **"Último estado"** derivada de `GET /api/events` (evento `comm_failure`/`comm_restored` mais recente por `origin=conn:<id>`; sem evento ⇒ "—"), polling 5 s — estado vivo de verdade chega com WS na F5. Form (criar/editar) espelha as validações do DDL/schemas F1: coerência policy×mode, campos de auth condicionais, watchdog par-completo-ou-vazio, período 500–5000 ms; senha write-only (`has_password`); aviso fixo *"sem watchdog ⇒ conexão somente leitura"* (§3.5). **[NOVA — implementação]** (forma)
- **`/engenharia/tags`** — tabela filtrável por conexão/direção (`GET /api/tags`), form com entrada **manual** de node_id (RF-203; browse adiado — §1.2), tipo, EU, descrição.
- **RBAC na UI:** operador vê as telas (ADR-015 "enxerga tudo"); botões/forms de mutação só para admin (PRD §2). **[NOVA — implementação]** (forma)
- Navegação: header do shell F1 ganha links "Conexões · Tags · Trend" em estilo plaqueta (Regra da Plaqueta). **[NOVA — implementação]**
- Strings 100% pt-BR (RNF-08), termos do GLOSSARY, sem emojis (DESIGN §Don'ts).

### 9.2 Trend mínimo (`/engenharia/trend`)

Seletor de tags (≤6) + janela (30 min · 2 h · 8 h · 24 h · 7 d) + uPlot **re-vestido** (DESIGN §Do's): fundo Poço, grade Linha, valores em mono tabular com EU na legenda (Regra do Número Tabular); polling de `/api/history` a 5 s. **Qualidade ruim sem depender de cor** (Regra do Canal Redundante): pontos `quality=2` viram *gap* na pena; legenda exibe rótulo `BAD` quando o último ponto da série é bad. Predição/linha-agora ("tinta que não secou") é assinatura da tela de operação — F5, fora do trend de engenharia. **[NOVA — implementação]** (forma)

### 9.3 Paleta de penas — resolve o `[a resolver]` do DESIGN §Colors

Faixas normativas atendidas: dessaturada (C ≤ 0.10), distinguível, matiz ≥30° das severidades (vermelho ~27, âmbar ~80, verde ~150) e fora da banda do azul único (230–250; o cinza C 0.02 não lê como azul):

```css
/* styles/tokens.css — acréscimo F2 */
--pen-1: oklch(0.78 0.10 190);  /* ciano-petróleo */
--pen-2: oklch(0.78 0.09 300);  /* violeta        */
--pen-3: oklch(0.78 0.10 110);  /* oliva          */
--pen-4: oklch(0.78 0.09 330);  /* magenta        */
--pen-5: oklch(0.75 0.06 55);   /* castanho       */
--pen-6: oklch(0.80 0.02 250);  /* cinza neutro   */
```

L 0.75–0.80 sobre Poço (0.21) garante contraste de valor de processo; a pena de **SP** (F5) já é o Azul Industrial por norma (DESIGN §Primary). Máx. 6 séries/gráfico ⇔ limite do `/api/history` (§8). **[NOVA — implementação]** (valores; faixas são do DESIGN.md)

---

## 10. Compose, dependências e opcsim

1. **Compose:** `opc-worker` ganha `OTTIMA_DATABASE_URL` (mesmo padrão api/recorder). Produção continua com **7 serviços** intocados (ADR-023); nenhuma var nova no `.env.example`. Tunables do worker (poll 10 s, heartbeat 10 s, teto de backoff 30 s) são **constantes de código** documentadas, não knobs de env — o que importa já é fixado por ADR-009/DDL. **[NOVA — implementação]**
2. **Dependência nova única:** `asyncua` em `services/opc-worker` (stack declarada, PRD §10). `opcsim` também a usa (escopo dev/test).
3. **opcsim:** pacote **`tests/opcsim/`** — `tests/` raiz é o lugar de infra cross-service (CLAUDE.md); entra no workspace (`members += "tests/opcsim"`), **dev-only, nunca dependência de produção**. Conteúdo: servidor asyncua com namespace fixo — vars float (senoide), int (contador), bool (onda quadrada), espelhos R de tags W (p/ verificar escrita), **rung do watchdog** (lê o bit escrito pelo sistema, escreve NOT no bit lido — espelho do PLC, ADR-009) e nodes de controle da simulação (`sim/control/freeze_watchdog` etc.) para os testes congelarem o rung em runtime. Modos None e Basic256Sha256 (gera certificado próprio no boot). **[NOVA — implementação]**
4. **E2E:** `deploy/docker-compose.e2e.yml` (override) adiciona o container opcsim à rede do compose (`opc.tcp://opcsim:4840`); testes locais/unit usam o mesmo opcsim **in-process**. Um código, dois usos. **[NOVA — implementação]**

---

## 11. Testes e gate E2E

### 11.1 Unit/integração (padrão spec F1 §9)

- **opc-worker contra servidor asyncua in-process** (CLAUDE.md §Testes): subscription→`OpcValue` · heartbeat 10 s · transição de quality · escrita + auditoria · gate (sem watchdog / em falha / reabertura pós 1ª alternância) · congelamento >10 s · reconexão com backoff · reconciliação (tag set ⇒ recria subscription; conexão ⇒ recria sessão) · `cert_missing`/`cert_mismatch` · 3 modos de segurança (certs de fixture).
- **Threshold de 10 s injetável nos testes** (default de produção fixo em 10.0 — ADR-009; não é knob de usuário). **[NOVA — implementação]**
- **recorder:** flush por tempo/tamanho, drop-oldest, retry de DB (testcontainers Timescale — fixtures F1), persistência de `events`.
- **api:** history (raw/1m, validações), events, certificados (generate/export/upload em volume temporário), eventos de auditoria publicados.

### 11.2 Gate E2E (3 camadas)

Rodada a partir de `down -v` + override e2e; setup via API (projeto + conexão → opcsim + tags).

| Camada | O quê |
|---|---|
| **L1 — smoke** | `deploy/smoke.sh` estendido: 7 serviços + opcsim healthy; `/health` do worker com conexão `up` e **`watchdog_alive=true`** (aceite "bit alternando") |
| **L2 — API** (`pytest -m e2e`) | cenários E2E-F2-01…09 abaixo |
| **L3 — roteiro browser-tool** | executado pelo agente com a tool `browser` do harness; **evidência = screenshot por passo** |

**L2 — cenários:**

| ID | Cenário | Cobre |
|---|---|---|
| E2E-F2-01 | Samples crescendo via `/api/history` (duas leituras espaçadas) | RF-204/801 · aceite "chegam ao trend" (dado consultável) |
| E2E-F2-02 | `/api/history` raw (≤2 h) vs 1m (>2 h) | RF-802 |
| E2E-F2-03 | Publicar em `opc.writes` ⇒ valor muda no opcsim (espelho R) + evento `opc_write` | RF-205 |
| E2E-F2-04 | Congelar watchdog ⇒ `comm_failure(watchdog_timeout)` com **Δt medido <12 s**; escrita durante falha ⇒ `write_blocked`, valor não muda | RF-206/207 · aceite |
| E2E-F2-05 | Descongelar ⇒ `comm_restored`; escrita volta (gate stateless, 1ª alternância) | §3.3/§3.4 |
| E2E-F2-06 | `docker stop opcsim` ⇒ falha dura; religar ⇒ restored | §2.2-2 |
| E2E-F2-07 | Sign e SignAndEncrypt sobem; `cert_missing` sem upload; ok após upload | RF-201/202 · ADR-021 |
| E2E-F2-08 | Tag estática: ≥1 amostra/min (heartbeat); em falha ⇒ amostras `quality=2` | §2.2-6 |
| E2E-F2-09 | Editar conexão ⇒ evento de auditoria + worker reconcilia (health reflete) | §2.2-1/§7.2 |

**L3 — roteiro browser-tool** (substitui Playwright nas superfícies novas da F2 — §1.1):

| ID | Passo |
|---|---|
| B-01 | Login admin → navegação Engenharia visível |
| B-02 | Criar conexão (form completo, validações) → aparece na lista |
| B-03 | Criar tags R/W |
| B-04 | Trend: ≥2 penas desenhando dados do opcsim (screenshot com valores) |
| B-05 | Congelar watchdog → "Último estado" em falha + BAD/gap no trend |
| B-06 | Restaurar → estado volta |
| B-07 | Operador: telas visíveis, mutações ocultas |

**Regra do plano (exigência do usuário, 2026-08-03):** toda tarefa do plano que entrega UI ou comportamento fim-a-fim termina com validação browser-tool — não só na rodada final.

**Regressão F1:** a suíte Playwright da F1 **continua rodando** no gate (o shell ganha nav); ajustes mínimos nos specs existentes são permitidos, specs novas não.

**Passa:** L1+L2 verdes na mesma rodada partindo de `down -v` + roteiro L3 completo com evidências anexadas ao PR da fase.

---

## 12. Aderência ao aceite F2 (PRD §8)

| Critério | Evidência no spec |
|---|---|
| **Leituras de servidor real chegam ao trend** | cadeia §2 (subscriptions) → §6 (recorder) → §8 (history) → §9 (trend); E2E-F2-01/02 + B-04 |
| **Bit de watchdog alternando** | §3.1 + rung do opcsim §10.3; L1 smoke (`watchdog_alive=true`) |
| **Queda ⇒ alarme em <12 s** | §3.2/§3.8; E2E-F2-04/06 (Δt medido) |
| **Queda ⇒ bloqueio de escrita** | §3.4 (gate); E2E-F2-04 |
| Entrega: opc-worker (3 modos de segurança) | §2 + §5; E2E-F2-07 |
| Entrega: barramento | §2.2-5/§4.1 — canais e payloads §7.1 verbatim via `ottima_core.bus` (F1) |
| Entrega: recorder | §6; E2E-F2-01/08 |
| Entrega: watchdog | §3 |

---

## Anexo A — Decisões do brainstorm (2026-08-03)

| # | Lacuna | Decisão aprovada |
|---|---|---|
| 1 | Aceite "chegam ao trend" sem UI da F5 | Trend mínimo de engenharia na F2: `GET /api/history` (RF-802) + página uPlot + paleta de penas (pendência F1 §8.1 resolvida) |
| 2 | Config do opc-worker | Reconciliação com banco (watermark 10 s) como fonte da verdade + dica imediata via assinatura de `events` |
| 3 | Política de publicação | Subscription 250 ms/queue 1 + heartbeat de valor a cada 10 s (report-by-exception + heartbeat) |
| 4 | Semântica de desconexão | Rajada quality=bad + heartbeat bad contínuo durante a falha |
| 5 | Conexão sem watchdog | Read-only de fato; enforcement só no runtime (drop + warning deduplicado) |
| 6 | Evento de falha | Pares edge-triggered `comm_failure`/`comm_restored`; discriminador `kind` no payload |
| 7 | Trust do servidor | Pinning obrigatório com `policy≠none`; app cert único (RSA 2048/SHA-256/10 anos/URI `urn:ottima:opc-worker`), reutilizado como user token X.509 |
| 8 | Persistência de `events` | recorder é o único escritor barramento→banco; API emite auditoria de ativação/conexão/tag |
| 9 | recorder | Batch 1 s/1000 linhas; fila 100k drop-oldest; buffer de eventos separado com prioridade |
| 10 | Gate de verificação | opcsim próprio (unit in-process + container e2e) + gate 3 camadas. **Emenda (usuário):** L3 = roteiro com a tool `browser` do harness, substituindo Playwright nas superfícies novas da F2; o plano DEVE conter tarefas E2E browser-tool com evidência visual |
| 11 | Consulta de eventos | `GET /api/events` entra na F2 (metade API do RF-803) — aceite consultável + superfície limpa para o gate L2 |
