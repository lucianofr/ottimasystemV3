# ADR-020 — Log de eventos persistido, banner de alarmes, sem ACK

**Status:** Aceito · 2026-08-03

## Contexto
O design gera eventos operacionais que precisam de rastro: overrun de solver, timeout/exceção de script, falha de watchdog, troca de modo, escrita manual de operador, deploy, ativação de projeto.

## Decisão
- **Log de eventos persistido** no Postgres (hypertable com retenção de **1 mês**, mesma política das amostras): timestamp, severidade (info/warning/alarm), origem (flow/bloco/conexão/usuário), mensagem, payload.
- **Banner de alarmes ativos** na tela de operação, derivado do estado atual (condição ativa ⇒ visível; condição cessou ⇒ some). **Sem reconhecimento (ACK)** na v1.
- Fanout em tempo real pelo canal `events` do barramento → WebSocket.

## Consequências
- (+) Auditoria de operação (quem escreveu o quê) sai de graça do mesmo log.
- Sem ACK, não há estado "reconhecido" a persistir — banner é puramente derivado (stateless).
- Retenção de 1 mês vale também para auditoria — aceito explicitamente.
