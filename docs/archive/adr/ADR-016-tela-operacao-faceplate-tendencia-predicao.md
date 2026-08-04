# ADR-016 — Tela de operação: faceplate + tendência com predição do MPC

**Status:** Aceito · 2026-08-03

## Contexto
Operar um MPC exige ver passado (histórico) e futuro (predição) das variáveis, além de comandar modos — o padrão de console APC.

## Decisão
Tela dedicada de **operação** (por bloco MPC selecionado):
- **Faceplate principal:** modos LOCAL/REMOTO e MAN/AUTO, status (watchdog, solver, overruns), comandos.
- **Faceplates menores** na parte de baixo: todas as entradas e saídas do MPC (CVs com entrada de SP; MVs com entrada manual em MAN; DVs somente leitura).
- **Centro — gráfico de tendência:** histórico das variáveis selecionadas (TimescaleDB) **+ predição futura das PVs e MVs no horizonte Np**, sobreposta a partir de "agora".

## Consequências
- O flow-runtime **publica no barramento, a cada solve, os vetores de predição** e o estado do controlador (canal `mpc.state.*`); o FastAPI retransmite via WebSocket.
- Predições **não são persistidas** — só a última importa; histórico vem da hypertable/continuous aggregate.
- Biblioteca de gráfico: uPlot (tempo real + overlay de predição em eixo de tempo futuro).
