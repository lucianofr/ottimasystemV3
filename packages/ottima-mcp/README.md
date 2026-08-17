# ottima-mcp

Servidor MCP stdio que expõe o OttimaSystem a agentes de IA (ADR-036). Cliente da API
REST/WS existente — as mesmas validações e a mesma auditoria do frontend, nenhuma regra de
domínio própria.

## Variáveis de ambiente

Todas obrigatórias — o servidor recusa subir sem elas (sem defaults mágicos):

| Variável | Exemplo | Descrição |
|---|---|---|
| `OTTIMA_URL` | `http://localhost:8080` | Base da API/`.` do OttimaSystem |
| `OTTIMA_MCP_USERNAME` | `agente` | Usuário da conta dedicada do agente |
| `OTTIMA_MCP_PASSWORD` | *(secreto)* | Senha da conta `agente` |

## Bootstrap da conta `agente`

A conta não é seedada no boot do sistema (só o admin genérico é). Crie-a uma vez, com as
credenciais de ADMIN do sistema:

```bash
export OTTIMA_URL=http://localhost:8080
export OTTIMA_ADMIN_USERNAME=<usuário admin>
export OTTIMA_ADMIN_PASSWORD=<senha admin>
export OTTIMA_MCP_USERNAME=agente
export OTTIMA_MCP_PASSWORD=<senha nova do agente, min. 8 caracteres>
uv run --project packages/ottima-mcp python -m ottima_mcp.bootstrap
```

Idempotente — rodar de novo com a conta já existente só reporta "já existe".

## Registro no Claude Code

Adicione ao `.mcp.json` (raiz do repo, arquivo local — nunca versionado):

```json
{
  "mcpServers": {
    "ottima": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--project", "packages/ottima-mcp", "ottima-mcp"],
      "cwd": "<caminho absoluto da raiz do repo>",
      "env": {
        "OTTIMA_URL": "http://localhost:8080",
        "OTTIMA_MCP_USERNAME": "agente",
        "OTTIMA_MCP_PASSWORD": "${OTTIMA_MCP_PASSWORD}"
      }
    }
  }
}
```

A senha entra por expansão de variável de ambiente — nunca como literal no arquivo.

## Superfície de ferramentas

Curada (ADR-036) — operação, monitoramento e engenharia de flows. **Fora** de propósito:
usuários, certificados, escrita de conexões/tags/projetos, configurações de sistema — o
token da conta `agente` alcança admin, mas o servidor não expõe ferramentas para isso.

- **Operação**: `mpc_list`, `mpc_state`, `mpc_set_mode`, `mpc_write_sp`, `mpc_write_mv`,
  `fuzzy_list`, `fuzzy_detail`, `ssto_last`
- **Monitoramento**: `trend`, `mpc_history`, `events_query`, `system_health`
- **Engenharia de flows**: `block_catalog`, `flow_list`, `flow_get`, `flow_create`,
  `flow_add_block`, `flow_remove_block`, `flow_update_block`, `flow_connect`,
  `flow_disconnect`, `flow_deploy`, `flow_stop`

Toda ferramenta de escrita espera a confirmação **publicada** pelo runtime antes de devolver
(RNF-05: comandado ≠ confirmado) — nunca reporta sucesso só pelo 202 HTTP.

## Perímetro de segurança (ver ADR-036, seção Consequências)

- Token admin vive no ambiente da máquina do agente — mesmo perímetro de confiança do
  `deploy/.env`. Aceitável para planta virtual; **revisar antes de apontar para planta
  real** (mitigação futura: papel `engenharia` restrito no backend).
- Agente e operador humano simultâneos: last-write-wins, sem interlock — igual a dois
  operadores hoje. A auditoria por usuário (`events_query`) distingue autoria.
- `flow_deploy` faz hot-swap ao vivo (ADR-011) sem gate de confirmação humana — decisão
  desta versão; um `if` por ferramenta reintroduz o gate sem quebra de contrato.

## Desenvolvimento

```bash
uv sync --all-packages
uv run ruff check packages/ottima-mcp
uv run pytest packages/ottima-mcp/tests -v
```
