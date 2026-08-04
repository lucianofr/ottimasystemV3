# ADR-014 — Orçamento de tempo do MPC e multiplicador de execução

**Status:** Aceito · 2026-08-03

## Contexto
Ts mínimo de flow é 0.5 s; um solve IPOPT pode exceder isso. Scripts de condicionamento precisam rodar mais rápido que o controlador.

## Decisão
- **Timeout do solver = ~70% do Ts efetivo do MPC.** Ao estourar: **mantém a última MV, gera alarme de overrun e pula para a próxima varredura** — nunca acumula fila.
- **Multiplicador por bloco MPC:** o bloco executa a cada N varreduras do flow (`Ts_mpc = N × Ts_flow`). Demais blocos executam em toda varredura.

## Consequências
- (+) Flow rápido (condicionamento a 1 s) com MPC lento (a 5–10 s) no mesmo grafo.
- Entre execuções do MPC, as saídas do bloco seguram o último valor calculado.
- O overrun é evento operacional visível (alarme + contador no faceplate), não falha silenciosa.
