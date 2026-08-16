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
- (−) Um event loop por processo significa que todo flow do processo divide a mesma thread: bloco de custo síncrono inline (o `engine.process()` de um Fuzzy grande custa 17 ms com 125 regras) atrasa a fronteira de varredura dos OUTROS flows. `blocks/base.py` proíbe bloquear o loop por contrato, mas nada o impede por construção.

## Implementação da partição (2026-08-15)
A partição prevista na decisão existe: `OTTIMA_FLOW_PARTITIONS` (default **1** = um processo só, o comportamento original). Acima de 1, o processo que o compose sobe vira **pai**: não executa flow nenhum, dá `spawn` em N filhos e reexpõe o `/health` agregado na mesma porta 8002 — ver `services/flow-runtime/src/ottima_flow_runtime/partition.py`.

- **Posse:** `flow_id % N == index`, aplicada num ponto só (`Supervisor.handle_command`). Basta porque `flow.commands` é o ÚNICO caminho que sobe flow (ADR-017, boot parado) e porque o pai é a única autoridade que distribui índice — não há janela para dois processos executarem o mesmo flow, o que seria escrita duplicada em planta.
- **Um container, N processos** (e não N containers): mantém intactos os três pontos onde "existe um flow-runtime" está codificado — a URL fixa `health_url_flow_runtime`, o `Record` de chave única do frontend (`useWorkersHealth.ts`) e a contagem de serviços do `deploy/smoke.sh`. Verificado: o smoke completo passa com N=4 sem uma linha alterada.
- **Alcance real:** isola flows de partições DIFERENTES (processos distintos, sem GIL comum). Flows da MESMA partição continuam dividindo um event loop — a partição divide o raio do defeito por N, não o elimina. É por isso que `services/flow-runtime/tests/test_isolamento_temporal.py` segue `xfail(strict=True)`.
- **Custo:** cada partição sobe o próprio `ScriptPool` (`SCRIPT_POOL_SIZE // N`, piso 1) e o próprio espelho de valores; N alto em host pequeno troca jitter por memória.
