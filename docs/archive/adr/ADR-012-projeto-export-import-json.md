# ADR-012 — Projeto como unidade de agrupamento e portabilidade (JSON)

**Status:** Aceito · 2026-08-03

## Contexto
Flows precisam de agrupamento lógico e de portabilidade entre instalações (levar a engenharia de uma planta para outra / backup de configuração). Dimensionamento-alvo informado: **~10 flows simultâneos, ~100 tags OPC (leitura+escrita), até 5 servidores OPC-UA**.

## Decisão
**Projeto** agrupa flows. Projeto é **exportável e importável em JSON**, contendo **flows + configurações do sistema (servidores OPC etc.)** e **nunca dados históricos**.

## Consequências
- (+) Backup e replicação de engenharia com um arquivo; serve de mitigação à ausência de versionamento (ADR-011).
- O JSON de projeto precisa de campo de versão de schema para compatibilidade futura de import.
- Credenciais/segredos das conexões OPC no export: exportar sem segredos (re-informar no import) — a validar.
- Pendências (Rodada 2): uma instalação roda UM projeto ativo por vez ou vários projetos simultâneos? Flows iniciam automaticamente no boot do sistema?
