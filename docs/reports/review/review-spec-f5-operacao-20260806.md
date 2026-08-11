# Revisão de spec — F5 (tela de operação)

**Data:** 2026-08-06
**Objeto:** `docs/specs/F5-operacao.md` (294 linhas, commit `7899a6f`)
**Revisor:** agente RFC, modo *review*
**Base de comparação:** `docs/PRD.md` v1.2 · `docs/adr/ADR-001…024` · `PRODUCT.md` · `DESIGN.md` · `docs/GLOSSARY.md` · specs F1/F2/F3/F4 · código em `main` (`f53d244` + commit da spec)
**Precedência aplicada:** ADR > PRD > spec > plano

---

## Veredito

**APPROVE WITH CHANGES** — condicionado.

A arquitetura da fase está correta e bem lastreada: `mpc_samples` fecha a lacuna real do RF-703 (nem CV, nem SP, nem MV têm passado em `samples`), a emenda `ts` é necessária e segue o rito da emenda `ports` da F3, a semântica de `prediction.mv` está confirmada no código, e o veredito sobre dívidas F4 é defensável item por item. Nenhum item da spec contraria a **letra** de um ADR — inclusive o ponto mais exposto (`mpc_samples` × ADR-016), cuja argumentação se sustenta (ver F5R-A no apêndice).

Mas há **6 achados Critical** que precisam ser corrigidos **no texto da spec antes de escrever os planos**, três deles porque produzem comportamento errado no exato critério de aceite da fase:

- **F5R-01** — o overlay de predição fica adiantado **1×Ts_mpc**: a âncora proposta (`ts` do quadro) não é o instante do solve que gerou a predição. Isso é literalmente o aceite "predição sobreposta ao histórico" saindo errado, e afeta a emenda PRD v1.3 (§2.1), logo precisa ser resolvido **antes da submissão da emenda**, não no plano.
- **F5R-02** — a família TTL da tabela de cessação contradiz o produtor: o "dedupe" do runtime é **latch de condição**, não repetição periódica. Para 4 dos 5 kinds, a faixa anunciadora declara "cessou" segundos depois enquanto a condição continua ativa — falso *all clear* num painel anunciador.
- **F5R-03** — o bootstrap da faixa (`severity=warning|alarm`) **nunca busca os eventos de cessação** (`comm_restored` e `flow_deployed` são `info`): após um F5 do browser, todo `comm_failure`/`flow_failed` do último mês aparece como alarme ativo.
- **F5R-04** — a família "estado publicado" exige `mpc.state`/`flow.status` que o shell não assina fora da tela de operação.
- **F5R-05** — `building` continua inalcançável no deploy mesmo depois do F-1; o cenário E2E-F5-05 do gate, como escrito, não pode passar.
- **F5R-06** — o F-1 não fecha o head-of-line blocking: o caminho de `reload` e o `stop` do próprio flow em build seguem serializando o lock global.

Nenhum desses exige repensar a fase; todos são correções localizadas de §2.1/§3, §6 e §7.2. Recomendação de rito: aplicar os 6 Critical + os 10 Important na spec, e só então abrir F5a/F5b. Os Minor podem ir direto para os planos.

---

## Achados

Severidade: **Critical** = corrigir na spec antes dos planos (contradiz norma, contradiz o código, ou entrega comportamento errado no aceite) · **Important** = corrigir na spec ou travará/desviará um plano · **Minor** = precisão, consistência ou economia.

---

### Critical

---

#### F5R-01 — A âncora da predição está adiantada exatamente 1×Ts_mpc

**Seções afetadas:** §2.1 (emenda PRD v1.3), §3.1, §7.4-6, §9.1, §10 (linha do aceite)

**Evidência.** O bloco MPC consome o resultado do solve **na fronteira seguinte** à do disparo e publica o quadro nessa mesma fronteira:

- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:277-283` — `_run_frontier()` faz `result = self._host.poll()` **antes** de `dispatch()`: o resultado consumido na fronteira *n* é o do pedido despachado na fronteira *n−1*.
- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:268-274` — a publicação do quadro acontece na fronteira *n*, depois de `_mv_last` atualizado.
- `docs/specs/F4-mpc.md` §4.2 — "o `step()` **dispara** o solve na fronteira e **nunca espera**; o resultado aplica na primeira fronteira de varredura após concluir".
- Deadline = 70% × Ts_mpc medido do disparo (`mpc/host.py:174` — `self._deadline_s = 0.7 * horizons.ts_mpc`), então no caso normal o atraso é de **exatamente uma** fronteira.

Consequência: a predição publicada no quadro com `ts` = fronteira *n* foi calculada com as medições da fronteira *n−1*, e seu `t[0] = 0` corresponde a *n−1*. A regra da spec (`t_abs[k] = ts + prediction.t[k]`, §2.1) desloca a trajetória inteira **um Ts_mpc para o futuro**. Também torna `mv[0] = u_prev` inconsistente com o `vars.<mv_id>.v` do mesmo quadro (é o `u_prev` do ciclo anterior). Ironia: a spec discute meticulosamente o alinhamento de meio passo em §3.3 e erra um passo inteiro na âncora.

**Correção proposta.** A emenda §2.1 ganha um segundo campo, no mesmo rito (é a mesma submissão v1.3, mesmo `contracts.gen.ts`). Texto sugerido para §2.1, ao final:

> `MpcPrediction` ganha `ts: datetime` (UTC) — o instante da fronteira em que o solve **que produziu esta predição** foi despachado, carimbado pelo bloco em `_run_frontier()` no momento do `dispatch()` e devolvido junto com o resultado. `MpcState.ts` é o instante do quadro (âncora do recorder, §2.3); `prediction.ts` é a âncora do overlay: `t_abs[k] = prediction.ts + prediction.t[k]`. Os dois divergem porque o resultado de um solve é aplicado e publicado na fronteira seguinte à do disparo (spec F4 §4.2; `blocks/mpc.py:277-283`) — usar `MpcState.ts` como âncora adiantaria o plano inteiro em 1×Ts_mpc. Quadro sem predição (fora de AUTO) publica `prediction.ts` igual ao `ts` do quadro, com `t: []`.

E em §3, item novo:

> 5. A âncora do overlay é `prediction.ts` (§2.1), **nunca** o `ts` do quadro.

**Teste que precisa existir (§9.1, flow-runtime, clock controlado):** em regime, `prediction.ts == ts − Ts_mpc`; e `prediction.mv[i][0]` é igual ao `vars.<mv_id>.v` publicado no quadro **anterior**. Sem esse teste o erro é invisível: um overlay deslocado um passo parece plausível na tela.

**Alternativa rejeitada:** especificar o overlay como `ts − Ts_mpc + t[k]` sem campo novo. Quebra no primeiro quadro após armar, em respawn e em qualquer caso em que o resultado atravesse mais de uma fronteira; e obriga o cliente a conhecer Ts_mpc para desenhar (conhece, mas por outra rota — `/api/operate/mpcs`). Um campo é mais barato que uma regra condicional.

---

#### F5R-02 — A família TTL contradiz o produtor: o dedupe do runtime é latch de condição, não repetição periódica

**Seção afetada:** §7.2-1, linha "TTL" da tabela normativa de cessação

**Evidência.** A regra da spec é "cessa quando não houver repetição do mesmo `kind`+`origin` por 3× o período, mínimo 30 s". Ela pressupõe que uma condição persistente **re-emite** o evento. Nenhum produtor faz isso — todos latcham:

| kind | Latch | Rearme |
|---|---|---|
| `flow_overrun` | `scheduler.py:236-238` (`_overrun_armed`) | só quando uma varredura fecha **dentro** do orçamento (`scheduler.py:232`) |
| `mpc_overrun` | `blocks/mpc.py:412-415` (`_overrun_reported`) | só quando chega um resultado com `status != "overrun"` (`blocks/mpc.py:313-314`) |
| `mpc_input_invalid` | `blocks/mpc.py:440-443` | só quando a entrada volta a ser válida (`blocks/mpc.py:252-253`) |
| `script_timeout` / `script_error` | `blocks/script.py` `_reported_kind` (linhas 113-116) | só quando o script roda com sucesso (`blocks/script.py:95`) |

Logo, um flow que estoura o ciclo **em toda varredura** emite `flow_overrun` **uma única vez**. Pela regra da spec, 3×Ts depois (1,5 s num flow de 0,5 s, elevado ao mínimo de 30 s) a faixa declara a condição cessada — com o flow ainda estourando todas as varreduras. Isso é um falso "tudo normal" num painel anunciador, contra o princípio 1 do PRODUCT.md ("falhar para o lado seguro") e contra ADR-020 ("condição ativa ⇒ visível; condição cessou ⇒ some").

Note que `mpc_input_invalid` **já** está na família "estado publicado" na tabela — a spec acertou nesse e errou nos vizinhos que têm exatamente a mesma natureza.

**Correção proposta.** Reescrever a tabela §7.2-1 com quatro famílias, movendo os dois overruns para o estado publicado (onde o contador é o sinal exato, e o critério de cessação vira o espelho literal do rearme do latch do produtor):

| Família | Kinds | Ativa desde | Cessa quando |
|---|---|---|---|
| Par de eventos | `comm_failure`→`comm_restored` · `flow_failed`→`flow_deployed` | evento de abertura | evento par com a mesma `origin` |
| Estado publicado | `mpc_solver_error` · `mpc_input_invalid` · `mpc_shed` | evento | `mpc.state` do bloco publica `solver ≠ "error"` / `input_valid = true` / `armed = true` |
| Contador publicado | `flow_overrun` · `mpc_overrun` | evento | duas publicações consecutivas do mesmo produtor com `overruns` **inalterado** (`flow.status.overruns` / `mpc.state.status.overruns`) — espelha o rearme do latch do produtor (`scheduler.py:232`, `blocks/mpc.py:313`) |
| Notificação pontual (TTL) | `mpc_arm_failed` | evento | 60 s sem repetição do mesmo `kind`+`origin` **[NOVA — implementação]** — é tentativa discreta do operador, não condição |

E para `script_timeout`/`script_error`, que não têm estado publicado por bloco de script, escolher **uma** das duas saídas e cravá-la:

- **(a) sem mudança no runtime, conservadora:** entram na família "par de eventos", cessando com `flow_deployed`/`flow_stopped`/`flow_failed` da mesma `origin` de flow (um script que se recupera sozinho mantém a faixa acesa até o próximo deploy — falso positivo, lado seguro).
- **(b) exata, com 3 linhas no runtime:** o rearme do latch em `blocks/script.py:95` passa a publicar `script_recovered` (info), e o par vira `script_timeout|script_error` → `script_recovered`. Custo: um `kind` novo em `bus.py`, um `publish_event` no ponto onde o latch já zera, uma linha na tabela §5.3 da F4.

Recomendo **(b)**: é menor que a dívida que evita, e alinha os quatro kinds latchados sob a mesma disciplina de "quem latcha, anuncia o rearme". O fallback de período (90 s) desaparece junto com a família TTL genérica — ver F5R-19.

---

#### F5R-03 — O bootstrap da faixa não enxerga nenhum evento de cessação

**Seção afetada:** §7.2-2

**Evidência.** O bootstrap é `GET /api/events?severity=warning&limit=200` + `GET /api/events?severity=alarm&limit=200`. Os eventos que **fecham** a família "par de eventos" são de severidade `info`:

- `services/opc-worker/src/ottima_opc_worker/connection.py:375-378` — `comm_restored` com `severity="info"`.
- `flow_deployed` é `info` (spec F3 §4.3; `events.py` do flow-runtime).

Como `severity` é `Literal` único por chamada (`services/api/src/ottima_api/routers/events.py:29,41-42` — a suposição de "duas chamadas" da spec está **correta**), as duas queries do bootstrap retornam apenas aberturas e **jamais** os fechamentos. Resultado: ao montar o shell (login, F5 do browser, troca de tela com remount), todo `comm_failure` e `flow_failed` presente nas últimas 200 ocorrências de cada severidade — retenção de 1 mês, ADR-003 — é renderizado como **alarme ativo**. Numa sala de controle, uma faixa anunciadora que acende alarmes de três semanas atrás no refresh é pior que faixa nenhuma.

Efeito secundário: mesmo que os fechamentos fossem buscados, o `limit=200` sem janela pode cortar o par (200 warnings entre a abertura e o fechamento), produzindo o mesmo fantasma de forma intermitente.

**Correção proposta.** Substituir o item §7.2-2 por um bootstrap em duas partes, reusando o padrão já estabelecido na F3 §6.1 (`frontend/src/features/flows/useLastFlowState.ts:112-133` já consulta `/api/events?origin=flow:<id>&limit=N` por flow e deriva o **último** estado — é exatamente esta forma de problema):

> 2. **Bootstrap na montagem do shell**, dois grupos:
>    - **Famílias "par de eventos"** (condição derivada do último evento por origem, independente de severidade): `GET /api/events?origin=flow:<id>&limit=20` por flow do projeto ativo e `GET /api/events?origin=conn:<id>&limit=20` por conexão (≤10 + ≤5 chamadas, cache 60 s — mesmo padrão de `useLastFlowState`, F3 §6.1). A condição está ativa se o **último** evento da família naquela origem for o de abertura.
>    - **Famílias "estado publicado", "contador publicado" e TTL**: `GET /api/events?severity=warning&start=<agora−2h>&limit=500` + idem `alarm`. A janela de 2 h existe porque essas famílias só cessam por estado vivo ou por decaimento: evento mais velho que isso já foi resolvido pelo estado publicado do primeiro quadro recebido (≤ Ts_mpc após a montagem) ou já decaiu.
>
>    Depois disso, só WS. Períodos do TTL: ver §7.2-1.

Se preferir uma chamada só em vez de N+1 (coerente com o espírito de A-7), a alternativa é adicionar filtro de `kind` a `GET /api/events` (`payload->>'kind' = ANY(...)`) e buscar os 12 kinds relevantes numa janela — mas isso é rota nova a especificar e a testar, e o N aqui é ~15 com cache de 60 s, não N por linha de tabela. A alternativa por origem é a mais barata e já tem precedente testado no repositório.

---

#### F5R-04 — A cessação por estado publicado exige assinaturas que o shell não faz

**Seções afetadas:** §7.1-2, §7.1-3, §7.2-1 (famílias "estado publicado" e, com F5R-02, "contador publicado"), §7.2-2

**Evidência.** A faixa anunciadora é do shell e vive em **toda** tela (§7.2-3, DESIGN.md §Layout: "faixa anunciadora persistente no topo de toda tela em sessão"). Mas:

- §7.1-2 — "Páginas registram interesse via `useAssinatura({flow_status: [id]} | {mpc_state: ["fid/bid"]})`": as assinaturas de `flow_status`/`mpc_state` são **por página**.
- §7.1-3 — "`events` sempre assinado (o banner é do shell)": só `events` é global.
- §7.2-2 — a assinatura da função pura é `resolverAlarmes(eventos, flowStatus, mpcStates, periodos, agora)`, com `mpcStates` no **plural**.

Logo, fora de `/operacao/:flowId/:blockId` não existe nenhum `mpc.state` no cliente, e um `mpc_solver_error`/`mpc_shed`/`mpc_input_invalid` (e, com F5R-02, os overruns) **não tem como cessar**. B-F5-06 só exercita o watchdog (família "par de eventos"), então o gate passa sem tocar no defeito.

**Correção proposta.** Assinatura **sob demanda, dirigida por condição ativa** — mais barata que assinar tudo e sem custo em regime normal. Texto sugerido para §7.1, item novo:

> 5. **Assinatura derivada de condição ativa:** quando `resolverAlarmes` acusa condição ativa de família "estado publicado" ou "contador publicado", o provider assina o `mpc_state`/`flow_status` daquela origem e a mantém até a condição cessar; então desassina. Em operação normal (sem condição ativa) o shell assina apenas `events`. É o provider quem faz isso, não a página: a faixa não pode depender da tela aberta.

Justificativa de custo, que deve constar da spec para não ser redescoberta no plano: assinar `flow_status` de todos os flows por precaução traria a tabela `ports` **inteira** de cada flow a cada varredura (spec F3 §4.2) — 10 flows a 2 Hz de payload de canvas em toda tela, o oposto de barato. A fila por socket é de 8 mensagens com descarte do mais antigo (`services/api/src/ottima_api/ws.py:45-48,68-74`), o que é seguro para condição derivada de estado (a próxima publicação re-deriva), mas não convida a inflar o fanout.

**Teste (§9.1, frontend `test:unit`):** `resolverAlarmes` com evento de abertura e **sem** estado da origem ⇒ condição ativa (não silenciosa); com o estado subsequente ⇒ cessa. E máquina do canal único: condição ativa gera delta de `subscribe` daquela origem; cessação gera `unsubscribe`.

---

#### F5R-05 — `building` continua inalcançável no deploy; E2E-F5-05, como escrito, não pode passar

**Seções afetadas:** §6.2, §9.2 L2 (E2E-F5-05), §7.4-3

**Evidência.** A spec afirma (§6.2): "o bloco MPC publica `status.solver = "building"` até o worker ficar pronto — o valor deixa de ser inalcançável". Não é o que o código faz:

- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:563-575` — `building` só é publicado quando `auto` é verdadeiro: `if not auto: solver = "idle"` **antes** de `elif not self._host.ready: solver = "building"`.
- Deploy nasce sempre em **LOCAL** (spec F4 §4.4, decisão A-4, RNF-03) ⇒ `auto` falso ⇒ `idle` durante todo o build.
- Entrar em AUTO exige host pronto: `supervisor_mpc.py:151-152` (eixo `local_remote`) e `:109` (eixo `man_auto`) chamam `block.auto_arm_blocked_reason()`, que retorna `"worker_not_ready"` quando `not self._host.ready` (`blocks/mpc.py:181-182`).

Ou seja: em LOCAL o estado é `idle`, e não se chega a AUTO antes de `ready`. Depois do F-1, `building` segue alcançável **apenas** por respawn com o bloco já em AUTO — exatamente o que já acontecia antes do F-1. E o cenário E2E-F5-05 ("`building` observável em `mpc.state` antes de `idle`") pede a ordem inversa da que o código produz.

Há um segundo problema, operacional, escondido no mesmo ponto: com boot assíncrono, existe uma janela em que o operador vê `solver: idle`, tenta armar e recebe `mpc_arm_failed{worker_not_ready}` **sem nenhuma indicação publicada do motivo**. Isso viola o princípio 2 do PRODUCT.md ("estado publicado é a única verdade") justamente na tela cuja razão de existir é tornar o estado legível.

**Correção proposta.** Emenda consciente e declarada a F4 §4.2/§5.1, com texto em §6.2:

> 2. O flow varre desde a primeira fronteira. **Emenda a F4 §4.2/§5.1:** `status.solver = "building"` passa a ser publicado sempre que o host não estiver pronto, **em qualquer modo** — precedendo `idle`, que fica reservado a "worker pronto e ocioso fora de AUTO". Sem isso o valor segue inalcançável no deploy (`blocks/mpc.py:563-575` força `idle` fora de AUTO) e o operador não tem estado publicado que explique o `mpc_arm_failed{worker_not_ready}` da janela de build (`blocks/mpc.py:181-182`).

Ajustar em consequência: §7.4-3 (a lâmpada do solver ganha `building` como estado de partida esperado, com o comutador de modo desabilitado e rótulo — Regra do Canal Redundante) e E2E-F5-05, que passa a ler "`building` observável em `mpc.state` no deploy, **antes** de `idle`, e `mpc_arm_failed{worker_not_ready}` se o operador tentar armar nessa janela".

---

#### F5R-06 — O F-1, como especificado, não fecha o head-of-line blocking

**Seções afetadas:** §6.1, §6.3, §6.5, §9.1 (flow-runtime), §9.2 (E2E-F5-05), §8 (linha F-1)

**Evidência.** A spec descreve o F-1 apenas pelo caminho de deploy ("o deploy estagia o flow e retorna"), e afirma em §6.3 que "`stop`/`deploy`/`reload` de **outro** flow não esperam build alheio". Faltam dois caminhos, ambos sob o **mesmo lock global**:

1. **`reload` (hot-swap)** também espera build síncrono: `services/flow-runtime/src/ottima_flow_runtime/supervisor_mpc.py:349-350` — `reconcile_mpc_hosts()` faz `await host.start()` para todo bloco cujo config mudou. O handler roda dentro de `async with self._lock` (`supervisor.py:245`). Editar um MPC pesado num flow bloqueia o deploy/stop de qualquer outro flow, exatamente como o deploy bloqueia hoje.
2. **`stop` do próprio flow durante o build** devolve o bloqueio pela porta de trás: `supervisor.py:_stop` → `supervisor_mpc.py:320-321` (`for host in runtime.hosts.values(): await host.stop()`), e `MpcHost.stop()` **espera o boot em voo**: `mpc/host.py:263-268` — `while self._background: await asyncio.wait(pending, timeout=_BOOT_TIMEOUT_S)`, com `_BOOT_TIMEOUT_S = 30.0` (`host.py:85`). Tudo isso sob `self._lock`. Depois do F-1 o build passa a estar sempre "em voo", então este caminho deixa de ser teórico e passa a ser o caso comum.

Ou seja: o F-1 como especificado **move** o head-of-line blocking do deploy para o stop, em vez de eliminá-lo, e deixa o reload intocado. E o E2E-F5-05 mede apenas a direção fácil (deploy pesado × stop de outro flow), que passará mesmo com os dois caminhos quebrados.

Nota técnica que a spec precisa registrar para §6.5 não virar armadilha de plano: `_spawn_and_wait_ready()` usa `asyncio.to_thread` (`host.py:342-344`). Cancelar a task **não** cancela a thread nem mata o processo já spawnado — "cancelar o build limpo" significa necessariamente *marcar parado, deixar a thread terminar e então matar/juntar o processo*, que é o que `MpcHost.stop()` já faz (`host.py:263-290`, com `_shutdown_worker` em `host.py:108-126`). O que **falta** não é cancelamento: é não pagar essa espera com o lock global na mão.

**Correção proposta.** Substituir §6.1/§6.3/§6.5 por:

> 1. `host.start()` sai do caminho síncrono do lock global em **todos** os caminhos que o chamam: `_deploy` (`supervisor.py:293-294`) e `reconcile_mpc_hosts` do hot-swap (`supervisor_mpc.py:349-350`). O deploy/reload estagia e retorna; o build roda como task de fundo.
> 3. O **ciclo de vida do host deixa de ser serializado pelo lock global**: `stop`/`shutdown_mpc` não podem esperar boot em voo com o lock na mão (`MpcHost.stop()` espera até `_BOOT_TIMEOUT_S` por `_background`, `host.py:263-268`). Forma **[NOVA — implementação]**: o lock global passa a proteger só o mapa `_runtimes`; a espera de desmonte de host roda fora dele (lock por flow, ou desmonte destacado com o `MpcHost` já removido do mapa). Sem isso o bloqueio de até `_BOOT_TIMEOUT_S` migra do deploy para o stop, e o reload continua bloqueando.
> 5. `stop` do próprio flow durante o build encerra o build sem processo órfão: `_stopped` primeiro, thread de spawn concluída, processo morto e juntado (`host.py:263-290` — `asyncio.to_thread` não é cancelável, então "cancelar" é sempre matar depois de nascer, nunca antes).

**Testes a acrescentar em §9.1/§9.2:** (a) `reload` de flow com MPC pesado não bloqueia `deploy`/`stop` de outro flow; (b) `stop` de flow **em build** não bloqueia `deploy` de outro flow (latência medida — é a inversão que E2E-F5-05 não cobre); (c) nenhum processo de worker sobra depois de (b) (asserção sobre `stats()["alive"]`/PID).

---

### Important

---

#### F5R-07 — O continuous aggregate `mpc_samples_1m` não tem política de refresh: a janela >2 h volta vazia

**Seção afetada:** §2.2-3 (e por consequência §2.4-2, §7.4-6, E2E-F5-02)

**Evidência.** §2.2-3 define a view e nada mais. A 0002 mostra que uma CAgg no Timescale precisa de três coisas, não uma: `packages/ottima-core/alembic/versions/0002_timescale.py:46-68` — `autocommit_block()` (a `CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)` não roda em transação), `add_continuous_aggregate_policy(...)` e `add_retention_policy` **na própria CAgg**. Sem a política de refresh, `mpc_samples_1m` nasce `WITH NO DATA` e nunca materializa: a janela de 8 h de §7.4-6 retorna série vazia e o E2E-F5-02 ("`1m` acima") falha. Sem retenção na CAgg, o agregado cresce sem limite — contra ADR-003 e o não-objetivo "histórico > 1 mês" do PRD §1.

**Correção proposta.** §2.2-3 passa a:

> 3. Continuous aggregate `mpc_samples_1m`: `time_bucket('1 minute', ts)` com `avg(v)` e `avg(sp)` por `(flow_id, block_id, var_id)`, criada em `autocommit_block()` com `WITH NO DATA`, mais `add_continuous_aggregate_policy(start_offset => INTERVAL '1 hour', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute')` e `add_retention_policy('mpc_samples_1m', INTERVAL '1 month')` — os três passos da 0002 (`0002_timescale.py:46-68`), não só a view.

Acrescentar em §9.2 L1 a asserção de retenção (o smoke já verifica "retenção ativa"): as políticas de `mpc_samples` **e** de `mpc_samples_1m` presentes em `timescaledb_information.jobs`.

---

#### F5R-08 — Chunk de 7 dias não é "o padrão da 0002" para tabela de alta escrita

**Seção afetada:** §2.2-1/2

**Evidência.** A 0002 usa **dois** intervalos, por natureza de tabela: `samples` (alta escrita, ~100 linhas/s) com `chunk_time_interval => INTERVAL '1 day'` (`0002_timescale.py:23`) e `events` (baixa escrita) com `'7 days'` (`0002_timescale.py:39`). `mpc_samples` é declaradamente da ordem de `samples` — 200 linhas/s por §2.2-5, o dobro — e a spec lhe dá o chunk de `events`, citando "padrão da 0002" como se houvesse um só. Um chunk de 7 dias a 200 linhas/s são ~120 M linhas por chunk, contra ~8,6 M nos chunks de `samples`: pior localidade de índice, drop de retenção em blocos grandes, e o oposto da recomendação de dimensionamento do Timescale.

**Correção proposta.** §2.2-2: "Hypertable com chunk de **1 dia** — mesmo intervalo de `samples` (`0002_timescale.py:23`), que é a tabela de natureza comparável; os 7 dias da 0002 são de `events`, de escrita esparsa."

---

#### F5R-09 — `httpx` não é dependência de runtime da API: `GET /api/health/workers` levanta ImportError na imagem

**Seção afetada:** §4.2-1

**Evidência.** A spec manda a API agregar os `/health` internos "(httpx, timeout 1 s cada)". Mas:

- `services/api/pyproject.toml:6-10` — dependências da API: `ottima-core`, `fastapi`, `uvicorn[standard]`. Sem httpx.
- `pyproject.toml:13-18` — `httpx>=0.27` está **apenas** no `[dependency-groups] dev`.
- `deploy/Dockerfile.python:8` — `RUN uv sync --frozen --no-dev --package ${PACKAGE}`: `--no-dev` exclui o grupo dev. Nos testes (que rodam no workspace com dev) funciona; na imagem, a rota morre com ImportError no primeiro acesso.

Isso é o tipo de defeito que passa em toda a suíte e só aparece no L1/L3.

**Correção proposta.** §4.2-1 ganha: "`httpx>=0.27` passa a ser dependência de **runtime** de `services/api/pyproject.toml` (hoje existe só no grupo `dev` do workspace, `pyproject.toml:18`, e a imagem é construída com `--no-dev`, `deploy/Dockerfile.python:8`)." Alternativa sem dependência nova, se a preferência for imagem magra: `urllib.request` em `asyncio.to_thread`, que é exatamente o que o compose e o smoke já fazem (`deploy/docker-compose.yml:75,101,127`) — três chamadas paralelas com timeout de 1 s não justificam um cliente HTTP, mas a escolha precisa estar na spec e não no plano.

Cravar também os defaults, já que a spec diz "defaults = nomes de serviço do compose": `http://opc-worker:8001/health`, `http://flow-runtime:8002/health`, `http://recorder:8003/health` (`deploy/docker-compose.yml:60,88,114`).

---

#### F5R-10 — A resposta de `/api/history/mpc` cria uma segunda convenção ao lado do RF-802 já implementado

**Seção afetada:** §2.4-2/3

**Evidência.** A spec diz "Downsampling idêntico ao RF-802" e "padrões F1 §6.1", mas a forma proposta (`{mode, series: {<var_id>: {t, v, sp}}}`) divergem do que existe:

- `packages/ottima-core/src/ottima_core/schemas/history.py:13-26` — `HistoryResponse` é `{mode, start, end, series: list[HistorySeries]}`, com `HistorySeries = {tag_id, t, v, q, v_min?, v_max?}`. Série é **lista** com a chave dentro, não dicionário; `start`/`end` são ecoados; `v_min`/`v_max` existem no modo `1m` (`routers/history.py:104-118`) e são o que permite desenhar banda no agregado.
- `routers/history.py:95-101` — há duas guardas que §2.4-3 não lista: `start`/`end` **opcionais** com default (`end = now`, `start = end − 1 h`) e teto de janela `MAX_WINDOW_DAYS = 31` (`schemas/history.py:9`), coerente com a retenção de 1 mês.
- "Uma série por tag pedida, sempre" (`routers/history.py:91`) — a série existe mesmo vazia; a spec não diz o que acontece com `var_id` desconhecido.

Duas formas de resposta para a mesma pergunta ("histórico colunar para uPlot") é exatamente a segunda convenção que a disciplina do repositório proíbe.

**Correção proposta.** §2.4-2 espelha a forma existente:

> 2. Downsampling idêntico ao RF-802 (`RAW_WINDOW_HOURS`/`MAX_WINDOW_DAYS` de `schemas/history.py`, sem número novo): janela ≤ 2 h ⇒ bruto; acima ⇒ `mpc_samples_1m`. Response `{mode: "raw"|"1m", start, end, series: [{var_id, t: [], v: [], sp: [], v_min?, v_max?}]}` — mesma forma de `HistoryResponse`/`HistorySeries` (`schemas/history.py:13-26`), com `var_id` no lugar de `tag_id`, `sp` alinhado a `t` (`null` onde não havia) e sem `q` (o estado publicado do MPC não carrega qualidade por variável). Série presente para todo `var_id` pedido, mesmo vazia; `start`/`end` opcionais com o mesmo default (`end = agora`, `start = end − 1 h`).

§2.4-3 acrescenta as reprovações que faltam: janela > 31 dias, e flow inexistente ⇒ **404** (coerente com §4.3-2) / `block_id` inexistente ou não-MPC ⇒ 422.

---

#### F5R-11 — A emenda PRD v1.3 está subespecificada e não tem dono no plano

**Seções afetadas:** §2.1, §1.1, §8

**Evidência.** O cabeçalho da spec já se declara sobre "PRD v1.2→v1.3", mas `docs/PRD.md:4` continua "Versão do documento: 1.2". O precedente do rito é visível: a emenda `ports` da F3 **editou** o PRD (`docs/PRD.md:6`, linha de changelog 1.2 e a linha do canal em §7.1). Nenhum item de §1.1, §8 ou §9 atribui essa edição a uma etapa de plano — e a emenda é maior do que "`mpc.state` ganha `ts`":

- **§7.1 do PRD, coluna Consumidores** de `mpc.state.<flow_id>.<block_id>`: hoje "api(WS)". Com a decisão A-1, passa a "api(WS), recorder". A revogação do "Recorder ignora `mpc.state`" (F4 §5.2) **é** uma mudança de contrato do PRD, não só de spec.
- **§7.1, payload:** `{modes, status, vars, cost, prediction{t[], cv[][], mv[][]}}` ganha `ts` e (com F5R-01) `prediction.ts`.
- **§4 do PRD (modelo de domínio):** lista `Sample` e `Event` como hypertables; ganha `MpcSample`.
- **RF-703:** "via Timescale/continuous aggregate" ganha a fonte concreta (`mpc_samples`/`mpc_samples_1m`), senão a lacuna que A-1 resolveu volta a ser lacuna na leitura do PRD.

**Correção proposta.** §2.1 fecha com o escopo exato da emenda (os quatro pontos acima) e §1.1/§8 recebem a linha "Emenda PRD v1.3 aplicada em `docs/PRD.md` (changelog + §7.1 + §4 + RF-703) — **Etapa 0 do plano F5a**, antes de qualquer código". Acrescentar um bloco "Emendas a documentos anteriores" (ver F5R-26) para não deixar as quatro emendas desta spec espalhadas por cinco seções.

---

#### F5R-12 — O terceiro listener do recorder precisa de mais que "mesmo lote e mesma resiliência"

**Seção afetada:** §2.3-1/3

**Evidência.** O pipeline não tem "um" buffer: tem um por tabela, com teto, contador de descarte e gatilho próprios, e cada um aparece em cinco lugares. Acrescentar `mpc.state.*` toca:

- `services/recorder/src/ottima_recorder/pipeline.py:95-107` — construtor (buffer novo, `mpc_queue_max` parametrizável como os outros).
- `pipeline.py:182-190` — `flush()`: ordem explícita (eventos primeiro por prioridade de auditoria, spec F2 §6.3); a nova tabela entra **depois** de `samples`.
- `pipeline.py:146-152` — `start()`: o desmonte cruzado no `except BaseException` existe justamente para não deixar assinatura pendurada; com três listeners a árvore precisa cobrir os três.
- `pipeline.py:197-206` + `stop()` — `stop()` de todos os listeners e flush final.
- `pipeline.py:119-127` — `dropped_total` (soma dos buffers) e o `/health` do recorder, que expõe `buffered_samples`/`buffered_events`/`dropped_total` e é asserido no L1.
- `pipeline.py:41` — `MAX_BIND_PARAMS`: 6 colunas ⇒ ~5.300 linhas por statement, sem ajuste necessário, mas vale a nota.

Sem enumerar isso, "mesma resiliência" é uma frase que o plano vai interpretar como "só um listener novo".

**Correção proposta.** §2.3-3 passa a:

> 3. Buffer próprio (`_DropOldestBuffer`), com teto e contador de descarte próprios, somando em `dropped_total` e visível no `/health` do recorder ao lado de `samples`/`events` (`pipeline.py:95-127`); entra em `flush()` **depois** de `events` e `samples` (auditoria primeiro, spec F2 §6.3), no desmonte cruzado de `start()` e no `stop()` (`pipeline.py:146-206`). Mesmo lote de 1 s (`FLUSH_INTERVAL_S`) e mesmo backoff; payload malformado é logado e descartado sem derrubar nada (RNF-05), contando em `malformed_total`.

---

#### F5R-13 — O golden do F-3 não detecta drift do lado Python e cobre menos da metade do espelho

**Seção afetada:** §7.6, §8 (linha F-3), §9.1

**Evidência.** Dois problemas distintos:

1. **Direção do drift.** O golden é gerado por comando manual e **commitado**; `mpcLogic.check.ts` compara TS contra o arquivo. O único teste do lado Python listado em §9.1 é "`mpc_golden_export` determinístico (mesma entrada ⇒ mesmo JSON)" — determinismo não detecta mudança. Se `derive_horizons` mudar em Python e ninguém regenerar, o JSON commitado fica velho, o check TS continua verde e a divergência volta a ser silenciosa: exatamente o que o F-3 existe para eliminar.
2. **Cobertura.** O espelho real é maior que os itens listados. Confere-se em `frontend/src/features/flows/mpc/mpcLogic.ts`: `derivarHorizontes` (219-229), `arredondarBankers` (235-241), `dimensaoEstado` (248-268), `FAIXA_MV/FAIXA_CV_RESTRICAO/FAIXA_DV` (205-207) — todos no golden — **mas também** `validarConfigMpc` (306-442, ~130 linhas), `paramsValidosParaKind` (283-293) e as mensagens pt-BR de reprovação, que espelham `_check_mpc_caps/_matrix/_numbers/_horizons` à mão e ficam de fora. §8 declara F-3 "**Fecha na F5**"; com o escopo de §7.6 ele fecha em parte.

**Correção proposta.** §7.6 ganha:

> 3. O determinismo do export não basta: um teste em `ottima-core` compara a saída de `mpc_golden_export` com o JSON **commitado** e falha se divergir ("regenere o golden"). É o que faz mudança no Python virar vermelho, e não só mudança no TS.
> 4. Escopo do golden: além de horizontes/dimensão/tetos/limiares/banker's, um caso por regra de `_check_mpc_caps/_matrix/_numbers/_horizons` com o **veredito** (regra que reprovou, aprovado/reprovado, warning ou erro) — não o texto pt-BR, que é livre por convenção. O que ficar fora entra em §8 como dívida declarada, com destino.

Se a preferência for manter §7.6 enxuto, então §8 deve rebaixar F-3 para "**Fecha em parte na F5**" e nomear o resíduo (`validarConfigMpc`) — o que não pode acontecer é a tabela §8 dizer "fecha" com metade do espelho fora.

---

#### F5R-14 — Três nomes para o mesmo Ts, um deles inexistente

**Seções afetadas:** §7.2-1 (coluna "Cessa quando", nota de período), §4.1-1

**Evidência.** §7.2-1 manda ler "Ts do flow (`GET /api/flows`, campo `ts`)". O campo é **`ts_seconds`**: `packages/ottima-core/src/ottima_core/schemas/flows.py:20,38` (`FlowCreate.ts_seconds`, `FlowOut.ts_seconds`). E o JSON de §4.1-1 introduz um terceiro nome para o mesmo conceito, `flow_ts`, quando `ts_seconds` já é o nome do domínio em toda a API e `TsSeconds` é o tipo único do ADR-007 (`schemas/flows.py:8`).

**Correção proposta.** §7.2-1: "`GET /api/flows`, campo `ts_seconds`". §4.1-1: `"flow_ts_seconds": 1.0` (ou `ts_seconds`), e a fórmula do Ts_mpc citada com o mesmo nome: `Ts_mpc = multiplier × flow_ts_seconds`.

---

#### F5R-15 — A chave booleana não encaixa na forma do parser do `/ws` e deixa um caso indefinido

**Seção afetada:** §5.1

**Evidência.** O parser tem uma forma uniforme: para cada chave do corpo, um par `(atributo, função de parse)` que converte uma **lista de ids** num set, e aplica `update`/`difference_update`: `services/api/src/ottima_api/ws.py:213-241`, especialmente 234-241. Uma chave booleana não é "extensão" dessa forma — é um terceiro ramo com semântica diferente (flag, não conjunto). Além disso, §5.1 não define o que fazer com `{"subscribe": {"events": false}}` nem com `{"events": 1}`/`{"events": []}`, e a disciplina do módulo é explícita: "mensagem malformada nunca derruba o socket" com log e descarte (`ws.py:214-216,226-232`).

**Correção proposta.** §5.1-1 passa a:

> 1. Protocolo estende com chave booleana: `{"subscribe": {"events": true}}` / `{"unsubscribe": {"events": true}}` — canal único, sem ids **[NOVA — implementação]** (forma). No parser é um **ramo próprio** (flag `sub.events: bool`), não o par `(atributo, parse de lista)` das duas chaves de id (`ws.py:234-241`): valor que não seja o booleano `true` (`false`, número, lista) é logado e ignorado, como qualquer corpo inesperado, e **não** inverte a ação — `unsubscribe` é a única forma de desassinar.

**Teste (§9.1, ws):** `{"subscribe":{"events":false}}` é no-op registrado em log, não assinatura nem desassinatura; e os três tipos de assinatura convivem no mesmo socket (já previsto).

---

#### F5R-16 — Os defaults do trend estouram o próprio teto de penas

**Seções afetadas:** §7.4-6 (Defaults), §2.4-1

**Evidência.** Default: "CVs + Restrições + SPs ligadas; MVs opt-in" e, no mesmo item, "~8 penas visíveis por legibilidade". O teto de config é **1..6 CVs+Restrições** combinadas (spec F4 §2.2-2, espelhado em `mpcLogic.ts:206`). Com 6 CVs: 6 penas de PV + 6 penas de SP = **12 penas** por default, 50% acima do teto declarado — e a Restrição contribui ainda com banda `low/high` sombreada. Os dois números da mesma frase não fecham.

**Correção proposta.** §7.4-6, item Defaults:

> - Defaults (decisão A-11): CVs (PV + SP) ligadas até o teto de **8 penas**, na ordem do config; Restrições ligadas como banda `low/high` (Poço) com a pena de PV contando no teto; MVs **opt-in** pela legenda clicável. Acima de 8 penas o excedente nasce desligado e a legenda o indica. Eixo futuro dimensionado por `Np×Ts_mpc`.

---

### Minor

---

#### F5R-17 — §3.3: "meio passo" é um passo inteiro, e o intervalo está com a borda invertida

`align: +1` não desloca o plano em meio passo: desloca **um passo inteiro** (`Ts_mpc`), porque cada valor passaria a valer no intervalo seguinte ao seu (com `t` espaçado de `Ts_mpc`, ver `mpc/worker.py:212` — `t = [k * ts_mpc for k in range(n_p + 1)]`). E, na convenção ZOH, `u_j` vale em `[t[j-1], t[j])`, não em `(t[j-1], t[j]]` — a borda importa zero para o traço (medida nula) mas o texto é normativo e vai ser citado por outros documentos. Sugestão: "o índice `j ≥ 1` é a MV aplicada no intervalo `[t[j-1], t[j])`; renderização com degrau alinhado à esquerda (uPlot `stepped`, `align: -1`), que faz o valor pertencer ao intervalo que **termina** no seu ponto — `align: +1` deslocaria o plano inteiro em um passo (`Ts_mpc`) e é proibido."

---

#### F5R-18 — §7.4-4: a janela do pendente empata com a janela de decisão do runtime

"Sem materialização em 2×Ts_mpc (mín. 5 s) ⇒ reverte ao publicado" usa exatamente a mesma janela que o watchdog de armar do runtime: `CONFIRM_MISSES_LIMIT = 2` ticks de Ts_mpc (`services/flow-runtime/src/ottima_flow_runtime/mpc_arming.py:34-35`). Janelas iguais são corrida: o cliente pode desistir no mesmo instante em que o runtime reverte, e o operador vê o fantasma sumir sem nunca ver o `mpc_arm_failed`. Sugestão: **3×Ts_mpc (mín. 5 s)**, com a nota "estritamente maior que a janela de confirmação do runtime (`CONFIRM_MISSES_LIMIT`, `mpc_arming.py:34`), para que o desfecho publicado sempre chegue antes do timeout do cliente".

---

#### F5R-19 — §7.2-1: o fallback de 90 s é justificado por uma regra diferente da que aplica

"3× o período" com "fallback 90 s (1,5× o Ts máximo da lista ADR-007)" mistura dois critérios: 3× o Ts máximo (60 s) seriam 180 s. Um fallback menor que a regra é o lado inseguro (cessa cedo). Com a reescrita de F5R-02 a família TTL fica só com `mpc_arm_failed`, e o fallback desaparece; se alguma família TTL sobrevivver, usar **180 s** e citar "3× o Ts máximo da lista ADR-007".

---

#### F5R-20 — §2.1: "nenhum consumidor existente quebra" vale para o runtime, não para a suíte

Correto no essencial (`ws.py:_dispatch_mpc_state` reencaminha o JSON sem validar contra o modelo — `ws.py:158-174`; nenhum código de frontend consome `MpcState` hoje). Mas `MpcState` é **construído** em quatro módulos de teste, que passam a exigir `ts`: `packages/ottima-core/tests/test_bus_events.py`, `services/api/tests/test_ws_mpc.py`, `services/flow-runtime/tests/test_mpc_block.py`, `services/flow-runtime/tests/test_supervisor_mpc.py`. Trocar a frase por "nenhum consumidor de produção quebra; quatro módulos de teste que constroem `MpcState` passam a informar `ts` (campo obrigatório de propósito — o recorder depende dele)".

---

#### F5R-21 — §2.2: o histórico não distingue SP comandado de SP rastreado

Fora de AUTO o SP faz PV-tracking (spec F4 decisão A-4), então `mpc_samples.sp == v` nesses períodos. `mpc_samples` não guarda modo, então o trend não consegue dessaturar o SP rastreado como §7.4-5 faz no faceplate: no histórico, um SP que só estava seguindo a PV é indistinguível de um SP comandado pelo operador. Numa análise de turno isso é leitura errada. Sugestão barata: coluna `auto boolean NOT NULL` em `mpc_samples` (o quadro já sabe: `modes.man_auto == "auto"` e `armed`), `bool_or(auto)` na CAgg, e §7.4-6 dessatura a pena de SP nos trechos com `auto = false`. Se ficar de fora, registrar explicitamente em §1.2 como decisão consciente, não como omissão.

---

#### F5R-22 — §7.1: o raio do refactor do socket está subestimado

"`useFlowStatus(flowId)` mantém assinatura pública idêntica" é verdade para o hook e falso para o módulo. Muda de casa muito mais: `abrirCanalAoVivo` e `AmbienteAoVivo` (todo o ciclo de vida do socket, `frontend/src/features/flows/useFlowStatus.ts:191-289`) vão para o provider com o harness de dublês que os testa; `analisarMensagem` (141-165) muda de tipo de retorno ao generalizar por canal (hoje filtra por `PREFIXO_CANAL = "flow.status."`, linha 52); `comandoAssinatura(acao, flowId)` (74-76) vira gerador de delta multi-canal; e `mesclarPorts` (92-94, "ports vazio preserva o anterior") tem de sobreviver no redutor por canal, ou o canvas apaga a cada transição de estado. Sugestão: listar essas quatro puras em §7.1-1 e cravar "o check de desmonte de `useFlowStatus.check.ts` acompanha o provider — não é apagado".

---

#### F5R-23 — §2.4/§4.1: validações não especificadas

§2.4-3 lista três reprovações (var_ids vazio/malformado, `start ≥ end`, teto excedido) e deixa em aberto: flow/`block_id` inexistente (deve seguir §4.3-2: 404 para flow, 422 para bloco), `var_id` que não existe no config (sugestão: série vazia, coerente com "uma série por tag pedida, sempre" — `routers/history.py:91`), e o teto de janela de 31 dias (F5R-10). §4.1 não diz o que acontece com flow cujo `graph_json` não parseia (sugestão: pular o flow com log, nunca 5xx — a descoberta é leitura de tela de operação).

---

#### F5R-24 — §7.5-1: o filtro de origem da UI não tem como ser populado

`GET /api/events` filtra `origin` por **igualdade exata** (`services/api/src/ottima_api/routers/events.py:43-44`), e as origens reais são `flow:59/block:mpc_x7k2`, `conn:3`, `recorder`. Um campo de texto livre exige que o operador digite isso. Sugestão para §7.5-1: "filtro de origem como select, populado das origens conhecidas (`GET /api/flows` + `GET /api/operate/mpcs` + `GET /api/connections`, mais as origens distintas presentes no resultado carregado) — a API filtra por igualdade exata (`routers/events.py:43`), então a UI nunca pede texto livre".

---

#### F5R-25 — §2.2-5: o "pior caso" de volume não é o pior caso

"10 flows × ~10 vars × 2 Hz = 200 linhas/s" está aritmeticamente certo (Ts_mpc mín. = 0,5 s ⇒ 2 Hz) e a comparação com `samples` é honesta (~100 linhas/s), mas o rótulo "pior caso" não se sustenta: o teto de config é **14 variáveis** por bloco (4 MV + 6 CV/Restr + 4 DV, spec F4 §2.2-2 — o mesmo 14 que §2.4-1 usa como teto de `var_ids`, coerente), e nada limita o número de blocos MPC por flow (§4.1-1 projeta "**todos** os nós `type=mpc`"). Sugestão: chamar de **caso típico** (200 linhas/s, ~2× `samples`, aceito) e acrescentar o teto real com a premissa explícita: "um bloco MPC por flow como caso de projeto; 14 vars × 10 flows = 280 linhas/s no teto de config. Mais de um MPC por flow multiplica linearmente e não tem teto declarado — registrado como limite de dimensionamento, não como validação".

---

#### F5R-26 — As quatro emendas da spec estão espalhadas por cinco seções

Esta spec emenda quatro documentos vinculantes: PRD §7.1 (`ts`, §2.1), F4 §5.2 ("Recorder ignora `mpc.state`" revogada, §2.2-7 e A-1), F4 §6.1 (422 → 404, §4.3-2), F2 §1.2/F3 §1.2 ("valores de tag → F5" reapontado, §1.2) — e, com F5R-05, também F4 §4.2/§5.1. Todas estão **sinalizadas** (o rito está cumprido, ver apêndice F5R-B), mas nenhuma está reunida, e nenhuma diz se o documento-fonte recebe anotação. O PRD tem regra explícita para isso ("o PRD deve ser corrigido", `docs/PRD.md:10`); specs anteriores não têm. Sugestão: uma subseção "§1.3 Emendas a documentos anteriores" com uma linha por emenda (documento, trecho, o que muda, quem aplica) e a regra: "PRD é editado (Etapa 0 do F5a, F5R-11); specs anteriores recebem nota de remissão a esta spec no trecho revogado, nunca reescrita silenciosa".

---

#### F5R-27 — §4.3-3: as duas cópias de `_empty_result` têm assinaturas diferentes

Confirmado que a duplicação existe: `services/flow-runtime/src/ottima_flow_runtime/mpc/host.py:128-140` (kw-only, `wall_ms` obrigatório) e `services/flow-runtime/src/ottima_flow_runtime/mpc/worker.py:238-247` (posicional, `wall_ms` com default) — o comentário do host até declara a duplicação. Como as assinaturas divergem, "função única em módulo comum" precisa escolher uma: sugerir a do host (kw-only, `wall_ms` explícito — chamador sintético sempre sabe o que mediu) e ajustar os chamadores do worker. Uma linha na spec evita uma discussão no plano.

---

## Conformidade por requisito

Legenda: **OK** = coberto e testado · **OK\*** = coberto, com achado a aplicar antes do plano · **Parcial** = cobertura incompleta

| Requisito | Seção da spec que cobre | Teste que prova | Status |
|---|---|---|---|
| **RF-701** — tela dedicada por bloco MPC, seletor, faceplate principal (modos, watchdog/solver, overrun, comandos) | §4.1 (descoberta) · §7.4-1 (seletor, MPC na URL) · §7.4-3 (faceplate principal) | E2E-F5-03 (projeção sem `pid`/`models`) · B-F5-01 · B-F5-03 · unit api (`/operate/mpcs`) | OK\* (F5R-05: lâmpada do solver precisa de `building`; F5R-14: nome do campo de Ts) |
| **RF-702** — faceplates menores por variável (CV+SP, MV manual em MAN, Restrição com faixa, DV read-only), com EU e limites | §7.4-5 (barra vertical com escala, mono tabular + EU, clamps, habilitação por modo) | B-F5-02 · B-F5-04 · unit frontend (clamps de faceplate) | OK |
| **RF-703** — trend central: histórico via Timescale/CAgg + overlay de predição no horizonte Np, janela ajustável | §2.2 (`mpc_samples` + CAgg) · §2.4 (`/api/history/mpc`) · §3 (semântica) · §7.4-6 (overlay, janelas, borda viva) | E2E-F5-01 (linhas na cadência) · E2E-F5-02 (raw×1m, teto, RBAC) · B-F5-05 · unit frontend (montagem de séries, alinhamento, `align:-1`) | **Parcial** — F5R-01 (âncora do overlay errada em 1×Ts_mpc), F5R-07 (CAgg sem refresh ⇒ janela de 8 h vazia), F5R-10 (forma da resposta), F5R-16 (defaults × teto de penas) |
| **RF-704** — comandos UI → REST → `flow.commands` → runtime → estado republicado; todos auditados | §7.4-4 (pendente-até-confirmar, Regra do Estado Publicado) · §7.4-5 (fluxo completo; auditoria é do runtime, F4 §4.8) | B-F5-03 · B-F5-04 (auditoria visível em `/eventos`) · E2E-F4-08 (regressão) · unit frontend (redutor pendente: materializa/ignora/expira) | OK\* (F5R-18: janela do pendente empata com a do runtime) |
| **RF-705** — banner de alarmes ativos (condições vigentes), sem ACK | §7.2 (tabela de cessação, bootstrap, `resolverAlarmes`) · §7.2-3 (renderização, Canal Redundante) | B-F5-06 (watchdog: acende em qualquer tela, cessa ao restaurar) · unit frontend (`resolverAlarmes`: 3 famílias, TTL, bootstrap, mesma `origin`) | **Parcial** — F5R-02 (TTL contradiz o produtor: falso *all clear* em `flow_overrun`, `mpc_overrun`, `script_timeout`, `script_error`), F5R-03 (bootstrap nunca vê a cessação ⇒ alarme fantasma no reload), F5R-04 (estado publicado não assinado fora da tela de operação). B-F5-06 só exercita a família que funciona |
| **RF-803** — log de eventos consultável e filtrável (severidade, origem, período) na UI | §7.5 (tabela ts desc, payload expansível, filtros, prepend ao vivo) | B-F5-07 (filtros; prepend com marca de recém-chegado) | OK\* (F5R-24: como popular o filtro de origem) |
| **RNF-07** — endpoint de health por serviço; heartbeat de opc-worker/flow-runtime visível na UI | §4.2 (`GET /api/health/workers`, sempre 200) · §7.3-3 (lâmpadas na Home, polling 5 s, lâmpada de estado nunca só cor) | L1 smoke (3 × `up: true`) · B-F5-08 (parar o recorder ⇒ lâmpada down) · unit api (agrega, down ⇒ `up:false`, timeout, sempre 200) | OK\* (F5R-09: `httpx` ausente na imagem da API) |
| **Aceite §8-F5** — operador conduz LOCAL/REMOTO/MAN/AUTO | §7.4-3 (comutadores de posição; MAN/AUTO só em REMOTO — ADR-010) · §7.4-4 | B-F5-03 · E2E-F4-03/07/08 (regressão) | OK\* (F5R-05: sem `building` publicado o operador não sabe por que o armar falha na janela de build) |
| **Aceite §8-F5** — escreve SP/MV | §7.4-5 (SP só em AUTO, MV só em REMOTO+MAN, clamps client-side; servidor é a barreira) | B-F5-04 · E2E-F4-08 (regressão) | OK |
| **Aceite §8-F5** — predição sobreposta ao histórico | §2 (mpc_samples + `ts`) · §3 (semântica normativa) · §7.4-6 (overlay) | B-F5-05 · unit frontend (alinhamento) | **Parcial** — F5R-01 desloca o overlay em 1×Ts_mpc: o aceite passaria visualmente e estaria errado. **Teste faltante:** nenhum cenário compara a predição com o histórico que ela previu |
| **Aceite §8-F5** (entrega) — eventos/banner | §7.2 · §7.5 | B-F5-06/07 | **Parcial** (F5R-02/03/04) |
| **Aceite §8-F5** (entrega) — auditoria | runtime F4 §4.8 (já audita) · §7.5 (exibe) | B-F5-04 · B-F5-07 | OK |

### Claims normativos sem teste correspondente em §9

Levantados por varredura item a item da spec; todos são acréscimos pequenos ao §9 já escrito.

| Claim | Onde | Teste sugerido |
|---|---|---|
| Retenção de 1 mês em `mpc_samples` e na CAgg | §2.2-2, §2.2-3 | L1: políticas presentes em `timescaledb_information.jobs` (o smoke já verifica "retenção ativa") |
| Recorder grava **em todos os modos**, inclusive LOCAL | §2.3-4 | E2E-F5-01 estende: flow MPC em LOCAL também produz linhas |
| Predição vazia fora de AUTO ⇒ overlay some, histórico segue | §3.4, §7.4-6 | unit frontend: quadro com `t: []` remove o overlay sem apagar as séries |
| MPC ausente na revalidação ⇒ volta ao seletor com aviso | §7.4-2 | unit frontend (ou B-F5-01 estendido) |
| `reload`/`stop` durante build não bloqueiam outro flow | §6.3 (com F5R-06) | flow-runtime, clock controlado + latência medida |
| Nenhum worker órfão após stop durante build | §6.5 | flow-runtime: `stats()["alive"]` falso e processo juntado |
| `{"subscribe":{"events":false}}` é no-op | §5.1 (com F5R-15) | api ws |
| Teto de janela (31 dias) e `var_id` desconhecido em `/api/history/mpc` | §2.4-3 (com F5R-23) | api |
| Golden não fica velho em silêncio | §7.6 (com F5R-13) | ottima-core: export × JSON commitado |

---

## Apêndice — claims verificados e confirmados

Registrado porque metade do valor desta revisão é dizer o que **não** precisa mudar.

**F5R-A — `mpc_samples` × ADR-016: o argumento da spec se sustenta.** ADR-016 diz literalmente "Predições **não são persistidas** — só a última importa; histórico vem da hypertable/continuous aggregate", e RF-625 repete "Predições não são persistidas". A proibição é nominalmente sobre predição; e o próprio ADR-016 manda o histórico vir de hypertable. Como `samples` só guarda tags (CV entra por porta, SP é volátil, MV escreve em tag W), sem `mpc_samples` o RF-703 é inexequível — a decisão A-1 resolve uma lacuna real sem tocar a letra do ADR. §2.2-7 exclui corretamente `prediction`, `cost` e `status`. **Aprovado.** (Ressalva de forma em F5R-11: a consequência precisa aparecer no PRD, não só nesta spec.)

**F5R-B — as emendas estão sinalizadas com rito.** `ts` no `mpc.state` (§2.1, invocando o precedente da emenda `ports` da F3 → PRD v1.2, confirmado em `docs/PRD.md:6`); 404 no `/operate` (§4.3-2, declarada "emenda consciente à spec F4 §6.1"); revogação do "Recorder ignora `mpc.state`" (§2.2-7 + §1.2 + A-1, preservando explicitamente a proibição que a nota protegia). Nenhuma emenda silenciosa encontrada. Ver F5R-26 (consolidação) e F5R-11 (escopo).

**Claims sobre o código conferidos e corretos:**

- `MpcState` não tem `ts` hoje (`bus.py:101-112`); `MpcVarState` é `{v, sp}` (`bus.py:74-79`) — §2.1 correta.
- Os **12** kinds citados na tabela de cessação §7.2-1 existem todos em `bus.py:125-162`.
- `ChannelListener`/`PatternListener` existem em `ottima_core.pubsub` (`pubsub.py:148,172`); o hub tem hoje dois `PatternListener` e ganha um `ChannelListener` (`ws.py:112-118`) — §5.2 correta.
- `TIMESERIES_METADATA` fora do autogenerate, padrão de handle (`models/timeseries.py:1-6,21`) — §2.2-6 correta.
- Migrations 0001/0002 existem; `0003_mpc_samples` é a próxima — correta.
- `severity` é `Literal` único por chamada (`routers/events.py:29`), logo as duas chamadas do bootstrap são necessárias; `DEFAULT_LIMIT=100`/`MAX_LIMIT=1000` (`routers/events.py:14-15`) acomodam `limit=200` — §7.2-2 correta na mecânica (o defeito é outro: F5R-03).
- `/operate` responde hoje 422 com `MSG_FLOW_NAO_ENCONTRADO` (`routers/operate.py:45,71-72`) enquanto `flows.py:55` usa 404 com a mesma mensagem — a unificação de §4.3-2 é coerente; `history.py`/`events.py` não têm lookup de flow, sem conflito. Sugestão de plano: constante única em vez de terceira cópia da string.
- Ausência de handler global de `RequestValidationError` confirmada (`app.py:35-74`) — §4.3-1 fecha dívida real.
- Fronteira raw/1m de 2 h e `MAX_TAGS`/`MAX_WINDOW_DAYS` (`schemas/history.py:8-10`; `routers/history.py:100-101`) — o padrão que §2.4 diz espelhar existe; ver F5R-10.
- Teto **14** de `var_ids` = 4 MV + 6 CV/Restr + 4 DV fecha com os tetos da F4 §2.2-2 (espelhados em `mpcLogic.ts:205-207`) — §2.4-1 correta.
- Pipeline do recorder com `PatternListener` + lote de 1 s (`pipeline.py:32,146-152`); o terceiro listener encaixa — ver F5R-12 para o que falta enumerar.
- Semântica da predição **fiel ao código**: `t` com Np+1 pontos (`mpc/worker.py:212`), `cv[i][k]` no instante `t[k]` (`worker.py:216-227`), `mv[i] = [u_prev, u_0, …, u_{Np-1}]` com `u_prev` lido do estado aumentado em `x0` (`worker.py:230-233`) — §3.1/§3.2/§3.3 corretas quanto ao conteúdo (ver F5R-01 para a âncora e F5R-17 para o texto).
- `host.start()` síncrono sob o lock global confirmado (`supervisor.py:245,293-294`); `_BOOT_TIMEOUT_S = 30.0` (`host.py:85`) — §6.1/§6.3 corretas no diagnóstico (ver F5R-06 para o que falta).
- `mpc_arm_failed{worker_not_ready}` **já existe** para o eixo `local_remote`, não só para `man_auto`: `supervisor_mpc.py:151-152` chama `auto_arm_blocked_reason()` (`blocks/mpc.py:181-182`) antes de materializar REMOTO. §6.4 acerta contra o **código**, ainda que a tabela F4 §4.4 mostre esse motivo só em MAN→AUTO.
- Puras de `useFlowStatus` exportadas como a spec supõe: `urlDoWs` (72), `atrasoReconexao` (79), `deveReconectar` (83), `analisarMensagem` (141) — §7.1-1 correta (ver F5R-22 para o resto do módulo).
- Regras espelhadas que o golden deve congelar existem todas em `mpcLogic.ts` (205-207, 219-229, 235-241, 248-268), com `mpcLogic.check.ts` já no lugar — §7.6 correta no alvo (ver F5R-13 no escopo).
- Pipeline de geração atravessada pela emenda: `contracts_export.py:94` (`_WS_MODELS` inclui `MpcState`) → `generate:contracts` → `contracts.gen.ts:127-165` (`FlowStatus.ts` já sai como `string`, então `MpcState.ts` idem) — §2.1 correta.
- Router `health` montado com `prefix="/api"` e rota `/health` (`app.py:62`; `routers/health.py:10`): `GET /api/health/workers` cabe no mesmo router, e `dependencies=[Depends(require_operator)]` por rota preserva o `/api/health` público. Sem conflito — §4.2 correta. O L1 já autentica (`deploy/smoke.sh:47-51`), então a asserção nova é viável.
- `useCanMutate` (`features/auth/useAuth.tsx:81-83`) está em uso nas quatro telas de engenharia — §7.3-2 ("seguem como estão") é verdade, e B-F5-09 é regressão legítima.
- "34 cenários L2 F1-F4" confere exatamente: 34 funções de teste em `tests/e2e/` (5+5+3+1+7+3+3+5+2).
- O roteiro L3 da F4 tem a seção citada (`docs/plans/tests-e2e-f4.md:50`, "Regras de execução com a tool `browser`").
- `flow.status.ts` é o instante da **fronteira de disparo**, não o fim da varredura (`services/flow-runtime/tests/test_scheduler.py:467-480`), e `task.last_scan_ts` já expõe esse instante — o "mesmo relógio" pedido por §2.1 é implementável sem invenção.
- `_empty_result` duplicado confirmado (`mpc/host.py:128` e `mpc/worker.py:238`) — §4.3-3 e a linha de §8 corretas (ver F5R-27).
- `building` inalcançável hoje: confirmado, e **continua** inalcançável depois do F-1 (F5R-05) — a linha de §8 está certa no diagnóstico e errada na consequência.
