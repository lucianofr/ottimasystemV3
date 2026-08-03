# ADR-006 — Separação de processos: opc-worker × flow-runtime × recorder

**Status:** Aceito · 2026-08-03

## Contexto
O solver do MPC é CPU-bound; a aquisição OPC é sensível a jitter. Rodar ambos no mesmo processo faz picos de CPU do solver atrasarem amostragem/escrita OPC.

## Decisão
Processos asyncio distintos, conectados só pelo barramento (ADR-002):
- **opc-worker** — único processo que fala com servidores OPC-UA (asyncua); publica leituras, executa escritas.
- **flow-runtime** — interpreta e executa os flows (MPC, scripts).
- **recorder** — assina o barramento e grava na hypertable.

## Consequências
- (+) Isolamento de jitter; falha/restart de um não derruba os outros.
- (+) Escala por processo (múltiplos flow-runtimes particionando flows).
- (−) Observabilidade multi-processo necessária (health/heartbeat por serviço).
