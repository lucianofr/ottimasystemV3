# ADR-001 — FastAPI all-in (abandono do Django na reescrita)

**Status:** Aceito · 2026-08-03

## Contexto
O OttimaSystem atual é Django + TimescaleDB + React/Vite. O centro de gravidade do sistema é I/O assíncrono persistente (OPC-UA), loops de controle MPC, WebSocket em tempo real e hypertables — exatamente onde Django é mais fraco (ORM async parcial, Channels frágil, ORM não conhece hypertables). O novo requisito de RBAC é trivial: apenas 2 papéis (admin, visualizador).

## Decisão
Reescrever com **FastAPI all-in** (API + WebSocket + workers async), SQLAlchemy 2.0 async. Sem Django, sem híbrido Django Ninja + FastAPI.

## Consequências
- (+) Código async idiomático em toda a stack; WebSocket nativo; um único framework backend.
- (+) RBAC vira ~20 linhas (tabela users com coluna role + dependências `require_admin`/`require_user`).
- (−) Perde-se o django-admin; telas de cadastro precisam ser construídas no frontend React.
