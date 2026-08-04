# ADR-013 — Modelo do MPC: matriz SOPDT + processo integrador; horizontes derivados do TSS

**Status:** Aceito · 2026-08-03 (detalha o ADR-008)

## Contexto
O formulário sem código (ADR-008) exige forma paramétrica fixa. Na prática dos usuários-alvo, modelos vêm de step-test; processos de nível/pressão em vaso fechado são integradores (PV não estabiliza).

## Decisão
- **Matriz de modelos por par** MV→CV e DV→CV.
- **Tipo de resposta definido por CV:** *autorregulável* → parâmetros **SOPDT (K, τ1, τ2, θ)** por par; *integrador* → parâmetros de modelo integrador por par (ganho de rampa Ki [un/un·s] + tempo morto θ).
- **Np/Nc NÃO são editados pelo usuário:** derivados do **TSS (Time to Steady State)** informado por CV. Heurística default da implementação: `Ts_mpc = multiplicador × Ts_flow`; `Np = ceil(TSS / Ts_mpc)` (com teto de segurança); `Nc = max(2, ceil(Np/4))`.
- Formulário expõe ainda: **limites duros de MV (min/max)** e **rate limit (Δu máx/ciclo)**.

## Consequências
- (+) Menos botões, defaults seguros: TSS é um número que engenheiro de processo sabe estimar; horizontes errados deixam de ser um modo de falha.
- SOPDT/integrador → conversão interna para espaço de estados discreto do do-mpc; **tempo morto via aumento de estados**.
- Integrador sem restrição de CV é malha aberta instável no ótimo → validação do formulário deve exigir limites/SP coerentes.
- Pendência (Rodada 3): tratamento das CVs — SP fixo apenas, ou zonas/restrições suaves e ideal resting values na v1?
