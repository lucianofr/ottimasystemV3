# ADR-025 — Retomada automática completa após `comm_restored`

**Status:** Aceito · 2026-08-10

## Contexto
A campanha de 14 h de operação contínua precisou de um supervisor externo (`planta_virtual/supervisor_mpc.py`) só para religar os flows e rearmar os blocos `mpc` toda vez que uma conexão OPC caía e voltava — o runtime, por si, derrubava o flow em `comm_failure` (RF-207) e nunca o retomava sozinho (ADR-017: "retomada é só por deploy manual"). Isso empurrava para fora do sistema uma responsabilidade que é dele: um operador (ou um script à parte) tinha de perceber a queda, religar o flow na mão e rearmar o MPC modo a modo, SP a SP.

O boot do servidor é um caso DIFERENTE: nenhuma conexão caiu, o processo é que subiu do zero, e nenhum snapshot de "como estava antes" existe para restaurar — ADR-017 continua valendo *ipsis litteris* para esse caminho.

## Decisão
Após `comm_restored` na conexão que derrubou um flow, e SÓ se `flow.desired_state == "running"` continuar valendo no banco (o operador pode ter parado o flow durante a queda — comando manual sempre vence, RNF-05), o runtime:

1. Redeploya o flow sozinho (mesmo caminho de um `deploy` manual, ator `sistema:retomada`).
2. Aplica, em cada bloco `mpc` do flow, o snapshot capturado ANTES de `comm_failure` zerar o estado (`EstadoMpcTransplante`: eixos de modo, últimos valores de MV, SP de cada CV — TD-006 já introduziu essa estrutura para o hot-swap bumpless, TD-005 a reusa).
3. Rearma REMOTO/AUTO pela MESMA máquina de comandos que um operador usaria (`mpc_mode`/`mpc_sp`), esperando as entradas voltarem a quentes/válidas antes de tentar — sem atalho e sem novo canal de confirmação: o gate (`auto_arm_blocked_reason`) e o watchdog de confirmação (`mpc_arming.watch_arm`) são os de sempre.
4. Publica `flow_resumed` (auditoria do redeploy) e `mpc_mode_changed {reason: auto_resume}` por bloco restaurado.

Escopo: SÓ queda de comunicação com `desired_state == "running"`. **Boot continua parado — o ADR-017 permanece intacto para o caminho de boot.**

Guarda: 1 tentativa de redeploy por evento `comm_restored` (edge-triggered no opc-worker, sem retry storm). Se o redeploy falhar (grafo inválido etc.), a pendência permanece para o próximo `comm_restored` bem-sucedido; `deploy`/`stop` manuais sempre limpam a pendência do flow.

## Consequências
- (+) Nenhum supervisor externo é mais necessário para operação contínua através de quedas de comunicação — a campanha de 14 h vira um cenário coberto nativamente.
- (+) Auditoria completa: `flow_resumed` e `mpc_mode_changed{reason: auto_resume}` deixam rastro de que a retomada foi automática, não um comando de operador.
- (+) `desired_state` continua sendo a fonte da verdade — o operador que parou o flow durante a queda não o vê voltar sozinho.
- (−) **Um controlador volta a AUTO sem um operador dizer "pode".** É o preço aceito desta decisão, e não é pequeno: entre a queda e a retomada a planta andou sozinha, e o MPC volta a comandar contra um estado que ninguém reavaliou. O que o torna aceitável: (a) o rearme passa pelo gate normal (`auto_arm_blocked_reason`), então entrada fria, inválida ou alvo de escrita sem watchdog seguram a retomada como segurariam um comando manual; (b) o snapshot restaura o SP de antes da queda, não um SP novo, então o controlador retoma o ponto que o operador já tinha escolhido; (c) `desired_state` continua sendo um veto de um clique. Quem não quiser a retomada automática num flow específico para o flow — e ele fica parado.
- Esta decisão SUBSTITUI o supervisor externo da campanha (`planta_virtual/supervisor_mpc.py` deixa de ser necessário para este cenário).
- Reusa o transplante de estado do TD-006 (mesma `EstadoMpcTransplante`) — os dois débitos são resolvidos pelo mesmo mecanismo de captura/aplicação de estado, só com gatilhos diferentes (hot-swap de config vs. queda de conexão).
