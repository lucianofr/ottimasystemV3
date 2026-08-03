# ADR-009 — Watchdog de comunicação por bit alternante (NOT cruzado)

**Status:** Aceito · 2026-08-03

## Contexto
Sistema que escreve em planta precisa de detecção ativa de perda de comunicação nos dois lados, independente do status da sessão OPC.

## Decisão
Watchdog com **duas variáveis OPC por PLC** (uma de leitura, uma de escrita). O sistema lê o bit de entrada, aplica **NOT** e escreve na saída; o PLC faz o mesmo do lado dele. O bit alterna 0↔1 continuamente. **Se o bit parar de variar por mais de 10 s, a comunicação é declarada em falha.**

Em falha de comunicação/OPC: **o sistema para de escrever nas MVs e o flow para de executar** (o PLC, pelo seu próprio watchdog, retoma o controle convencional).

## Consequências
- (+) Detecção simétrica: cada lado detecta a morte do outro sem depender de status de sessão.
- (+) Mecanismo trivial de implementar em qualquer PLC (uma rung).
- Watchdog configurado **por conexão OPC** (por PLC), não por flow — **confirmado**.
- O período de alternância deve ser ≪ 10 s (proposto: escrever a cada ciclo de 1–2 s, independente do Ts dos flows).
