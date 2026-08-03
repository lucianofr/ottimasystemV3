# ADR-003 — Postgres/TimescaleDB único, retenção de 1 mês

**Status:** Aceito · 2026-08-03

## Contexto
O sistema tem duas naturezas de dados: cadastros de baixa escrita (usuários, conexões OPC, tags, flows) e séries temporais de alta escrita (amostras de processo). Histórico exigido: 1 mês.

## Decisão
**Um único Postgres com extensão TimescaleDB**: tabelas relacionais para cadastros + hypertable para amostras. Retenção nativa via `add_retention_policy(..., INTERVAL '1 month')`. Continuous aggregate (ex.: média por minuto) para trends.

## Consequências
- (+) JOIN direto metadado↔série; um backup; um paradigma (SQL/SQLAlchemy); escrita concorrente nativa.
- (+) Limpeza de histórico automática pelo Timescale, sem código de manutenção.
- (−) Postgres na stack mesmo para cadastros pequenos — custo já pago pelo Timescale.
