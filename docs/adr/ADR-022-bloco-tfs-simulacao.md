# ADR-022 — Bloco TFS: simulação de processo por função de transferência

**Status:** Aceito · 2026-08-03

## Contexto
Testar/demonstrar MPC exige fechar a malha sem PLC nem servidor OPC real.

## Decisão
Quinto bloco da paleta v1: **TFS** — matriz de funções de transferência **até 2 entradas × 2 saídas**, cada elemento configurável como **SOPDT** (K, τ1, τ2, θ) ou **IOPDT** (Ki, θ), simulada em tempo discreto no Ts do flow, com estado interno persistente entre varreduras.

## Consequências
- (+) Malha fechada MPC↔TFS 100% dentro do sistema: base dos testes de aceitação do motor e do MPC (bumpless, overrun, restrições) sem hardware.
- Discretização interna (ZOH) e tempo morto por buffer de atraso; estado segue as regras de hot-swap do ADR-011.
- Elementos não usados da matriz 2×2 ficam desabilitados (ganho zero).
