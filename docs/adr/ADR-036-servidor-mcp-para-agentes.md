# ADR-036 — Servidor MCP para agentes de IA sobre a API existente

**Status:** Proposto · 2026-08-17 · Decisões fixadas em entrevista (grill) com o usuário

**Plano de implementação:** `docs/plans/servidor-mcp-agentes.md` (fases 0-6, fatos verificados em 2026-08-17)

## Contexto

Agentes de IA (Claude Code e afins, clientes MCP desktop) precisam operar o sistema:
tela de operação (LOCAL/REMOTO, MAN/AUTO, SP, MV), monitorar otimizador/SSTO e
tendências, e fazer engenharia de flows (criar blocos, configurar, conectar portas,
deploy). O pedido original era "web-MCP no frontend"; a análise mostrou que **todas**
as capacidades pedidas já existem como endpoints REST (38 rotas) — a tela é um
cliente fino da API (ADR-005), e até posição de nó vive no `graph_json`. "Operar a
tela" e "operar o sistema" têm o mesmo poder por superfícies diferentes.

## Decisão

1. **Servidor MCP sobre a API, não WebMCP na aba.** Pacote stdio novo
   `packages/ottima-mcp` (Python, SDK oficial `mcp`), rodando na máquina do usuário
   do agente, falando HTTP com a API existente (`OTTIMA_URL` + credenciais via env,
   login em `/api/auth/login`, re-login em 401). Zero infra nova; sem porta nova no
   perímetro. Camada WebMCP/visual fica explicitamente fora da v1.
2. **Conta dedicada `agente`, papel admin, superfície curada.** A atribuição de
   auditoria já é gratuita (`FlowCommand.user = "user:{id}"`; eventos
   `mpc_*_written`/`mpc_mode_changed` materializados pelo runtime). O token alcança
   admin, mas o servidor MCP **só expõe** ferramentas de operação, monitoramento e
   engenharia de flows — usuários, certificados, conexões OPC (escrita), projetos
   (CRUD/activate/import) e system-settings ficam fora da superfície de ferramentas.
3. **Sem gate de confirmação humana.** O backend já é a fronteira de segurança:
   422 de domínio (SP fora de `sp_limits`, `remote_sp` recusado, MV fora de
   categoria), LOCAL bloqueia escrita de MV (ADR-010), `max_rate` por ciclo
   (ADR-028). Erros 422 pt-BR são repassados verbatim ao agente. Decisão tomada com
   o alvo atual (planta virtual); rever antes de planta real.
4. **Canvas em nível de grafo.** Ferramentas de mutação fina
   (`flow_add_block`, `flow_connect`, `flow_set_block_config`, …) fazem
   read-modify-write do `graph_json` via `PUT /api/flows/{id}` — a validação do
   save (spec §5.2) é a rede de proteção; nada de manipulação visual ao vivo.
5. **Escrita espera estado publicado (RNF-05).** Toda ferramenta de escrita trata o
   202 como intenção: aguarda o estado confirmado (`mpc_state`/`flow_status` no
   canal `/ws`, assinatura única e curta por comando) com timeout proporcional ao
   ciclo de scan do flow (ADR-007), e devolve estado confirmado ou falha explícita
   de timeout. O agente nunca recebe "sucesso" por HTTP 200/202.
6. **Escopo v1: operação + engenharia desde o dia 1; uso sob demanda.** Leituras
   one-shot, mas `events_since` já nasce com cursor (`since_id`) para não quebrar
   contrato quando vier supervisão contínua (v2).

### Superfície de ferramentas (curada, ~20)

- **Operação:** `mpc_list`, `mpc_state`, `mpc_set_mode`, `mpc_write_sp`,
  `mpc_write_mv`, `fuzzy_list`, `fuzzy_operate`, `ssto_last`
- **Monitoramento:** `trend` (`/api/history`), `mpc_history`, `events_since`,
  `system_health` (`/api/health*`)
- **Engenharia:** `block_catalog` (contratos dos blocos, espelho ADR-034),
  `flow_list`, `flow_get`, `flow_create`, `flow_add_block`, `flow_remove_block`,
  `flow_connect`, `flow_disconnect`, `flow_set_block_config`, `flow_deploy`,
  `flow_stop`
- **Fora da superfície (deliberado):** users, certificates, connections (escrita),
  tags/calc-tags (escrita), projects (escrita/activate/import), system-settings,
  history-retention.

## Consequências

- (+) Nenhuma mudança no backend para a v1 além de criar a conta `agente`; o MCP é
  um cliente como o frontend, com as mesmas validações e a mesma auditoria.
- (+) Testável headless (contra a stack compose já existente), sem browser.
- (−) Token admin vive no env da máquina do agente — mesmo perímetro de confiança
  do `deploy/.env`; aceitável para planta virtual, condição a rever para planta real
  (mitigação futura: papel `engenharia` no backend restrito a flows/tags).
- (−) Agente e operador humano simultâneos: last-write-wins, sem interlock — igual
  a dois operadores hoje; a auditoria por usuário distingue autoria.
- Risco de implementação: o estado confirmado (modos/MVs correntes) é publicado só
  no `/ws` (`/api/operate/mpcs` é projeção de config). O servidor MCP mantém um
  cliente WS efêmero por espera de confirmação (assinatura única, fila 8 do servidor
  não é pressionada); se isso se provar frágil, expor `GET /operate/.../state` REST.
- Deploy/stop pelo agente faz hot-swap ao vivo (ADR-011) sem confirmação — aceito
  explicitamente nesta rodada; um gate por ferramenta (elicitation MCP) é um `if`
  reintroduzível sem quebra de contrato.
- (−) Sem push/streaming: "supervisão contínua" (item de decisão 6) é polling orquestrado
  pelo host do agente, nenhuma ferramenta assina/notifica sozinha; sem ferramenta composta
  de step test (degrau→espera→coleta num call só). Detalhado em
  `docs/plans/servidor-mcp-agentes.md` § Fora de escopo (v1) — v2.
