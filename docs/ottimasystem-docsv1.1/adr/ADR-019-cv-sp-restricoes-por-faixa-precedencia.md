# ADR-019 — Categorias de variáveis do MPC: CV com SP, Restrição por faixa (com precedência)

**Status:** Aceito · 2026-08-03

## Contexto
Só SP-tracking não cobre APC real: há variáveis que não devem seguir SP, apenas permanecer dentro de uma faixa — e a proteção delas vale mais do que o rastreamento das CVs.

## Decisão
O MPC opera **quatro categorias** de variáveis:
- **MV** — manipuladas (limites duros min/max, Δu máx/ciclo);
- **CV** — controladas por **setpoint** (SP escrito pelo operador);
- **Restrição** — controladas **dentro de uma faixa** (low/high), sem SP, **com precedência sobre as CVs**;
- **DV** — distúrbios medidos (feedforward).

A matriz de modelos (ADR-013) tem linhas = CVs + Restrições e colunas = MVs + DVs.

## Consequências
- Implementação da precedência: Restrições como **restrições suaves com slack e penalidade dominante** na função objetivo; CVs como termos quadráticos de rastreamento com peso inferior. Violação de faixa "compra" erro de SP, nunca o contrário.
- O formulário ganha aba própria de Restrições (faixas) e pesos relativos por CV / prioridade por Restrição.
- Validação: um MPC exige ≥1 MV e ≥1 (CV ou Restrição).
- Ideal resting values de MVs excedentes: **fora da v1**.
