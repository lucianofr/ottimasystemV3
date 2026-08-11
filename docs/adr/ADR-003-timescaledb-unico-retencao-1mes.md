# ADR-003 — Postgres/TimescaleDB único, retenção de 1 mês

**Status:** Aceito · 2026-08-03 · retenção revisada em 2026-08-11 (ver Atualização)

## Contexto
O sistema tem duas naturezas de dados: cadastros de baixa escrita (usuários, conexões OPC, tags, flows) e séries temporais de alta escrita (amostras de processo). Histórico exigido: 1 mês.

## Decisão
**Um único Postgres com extensão TimescaleDB**: tabelas relacionais para cadastros + hypertable para amostras. Retenção nativa via `add_retention_policy(..., INTERVAL '1 month')`. Continuous aggregate (ex.: média por minuto) para trends.

## Consequências
- (+) JOIN direto metadado↔série; um backup; um paradigma (SQL/SQLAlchemy); escrita concorrente nativa.
- (+) Limpeza de histórico automática pelo Timescale, sem código de manutenção.
- (−) Postgres na stack mesmo para cadastros pequenos — custo já pago pelo Timescale.

## Atualização — 2026-08-11
A retenção deixa de ser um valor fixo de 1 mês e passa a ser configurável pelo admin, 1–120
dias (default 30, que preserva o comportamento anterior), via `PUT /api/history-retention` e
um controle na tela Trends. Escopo: só as 4 estruturas de **variável de processo**
(`samples`, `samples_1m`, `mpc_samples`, `mpc_samples_1m`) — `events` (ADR-020, log de
alarmes) continua fixo em 1 mês. Reduzir a janela libera espaço imediatamente (`drop_chunks`
na hora do `PUT`), não só a partir do próximo ciclo agendado do job. A decisão de um único
Postgres/TimescaleDB e de retenção nativa via `add_retention_policy` continua de pé — só o
valor do intervalo deixou de ser hardcoded.
