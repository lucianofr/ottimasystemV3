# ADR-004 — Loops vivos em asyncio; sem Celery

**Status:** Aceito · 2026-08-03

## Contexto
MPC e OPC-UA são processos contínuos que mantêm estado e ciclam indefinidamente (loops vivos), não jobs discretos. O escopo atual não contém nenhum job discreto (relatório, treino de modelo, processamento de imagem).

## Decisão
Executar MPC, scripts e sessões OPC como **tasks asyncio** em processos worker dedicados. **Celery fora da stack.** O `mpc.make_step()` (IPOPT/CasADi, CPU-bound e bloqueante) roda via `loop.run_in_executor(...)`. Se solvers competirem por CPU, particionar flows entre múltiplos processos (um event loop por núcleo) — nunca migrar para Celery.

## Consequências
- (+) Estado persiste entre ciclos; sem overhead de enfileiramento por ciclo de controle.
- (+) Uma peça a menos na stack (sem broker de fila dedicado a jobs).
- (−) Se surgirem jobs discretos no futuro (ex.: identificação de modelo), Celery/RQ deverá ser reavaliado como adição.
