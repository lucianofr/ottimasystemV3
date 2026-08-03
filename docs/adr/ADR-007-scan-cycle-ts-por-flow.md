# ADR-007 — Execução por scan cycle com Ts individual por flow

**Status:** Aceito · 2026-08-03

## Contexto
Era preciso definir a semântica de execução do grafo: reativa (event-driven) ou cíclica (scan estilo PLC).

## Decisão
**Scan cycle:** a cada Ts, o flow-runtime avalia todos os blocos do flow em ordem topológica, usando os últimos valores conhecidos das entradas. **Ts é definido por flow**, escolhido de lista fixa: **0.5, 1, 2, 5, 10, 30 ou 60 segundos.**

## Consequências
- (+) Determinismo e familiaridade FBD/PLC; semântica simples de raciocinar e de gerar código.
- (+) Lista fixa de Ts elimina validação de valores arbitrários e simplifica o scheduler.
- (−) Ts = 0.5 s impõe orçamento de tempo apertado para o solve do MPC → política de overrun do solver precisa ser definida (Rodada 2).
- Blocos leem o snapshot mais recente do barramento; não há execução disparada por evento de tag.
