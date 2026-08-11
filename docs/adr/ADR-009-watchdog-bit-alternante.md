# ADR-009 — Watchdog de comunicação por bit alternante (NOT cruzado)

**Status:** Aceito · 2026-08-03

> **Revisão:** ver mudança de granularidade (por flow, não por conexão) e correção do lado que aplica o NOT, 2026-08-11.

## Contexto
Sistema que escreve em planta precisa de detecção ativa de perda de comunicação nos dois lados, independente do status da sessão OPC. Uma conexão OPC-UA pode ser um gateway na frente de vários PLCs independentes — o watchdog precisa monitorar especificamente o caminho por onde CADA flow escreve seu controle, que pode ser um subconjunto do que a conexão compartilhada alcança.

## Decisão
Watchdog com **duas variáveis OPC por flow** (`watchdog_read_node_id`, `watchdog_write_node_id` — nós OPC distintos, lidos através de `watchdog_connection_id`), não mais por conexão. O sistema lê o bit de entrada e escreve o **mesmo valor** (cópia pura, sem inverter) na saída; é o PLC/DCS do outro lado que aplica o **NOT**. O bit alterna 0↔1 continuamente. **Se o bit parar de variar por mais de 10 s, a comunicação daquele flow é declarada em falha.**

Em falha de comunicação/OPC de um flow: **o sistema para de escrever nas MVs e o flow para de executar** (o PLC, pelo seu próprio watchdog, retoma o controle convencional). Flows-irmãos que compartilham a mesma conexão OPC, mas não o watchdog em falha, não são afetados.

> Leitura e escrita **precisam ser dois nós distintos**. Um único nó compartilhado para `watchdog_read_node_id` e `watchdog_write_node_id` congela o handshake permanentemente após o primeiro ciclo (o valor lido de volta já é o que acabou de ser escrito) — nunca configurar dessa forma.

## Consequências
- (+) Detecção simétrica: cada lado detecta a morte do outro sem depender de status de sessão.
- (+) Mecanismo trivial de implementar em qualquer PLC (uma rung, NOT do lado do PLC).
- (+) Watchdog configurado **por flow**, não por conexão: uma conexão-gateway com vários PLCs atrás dela isola a falha no flow cujo PLC parou, sem derrubar os demais flows que passam pela mesma conexão.
- O período de alternância deve ser ≪ 10 s (proposto: escrever a cada ciclo de 1–2 s, independente do Ts dos flows).
