# ADR-010 — Modos LOCAL/REMOTO e MAN/AUTO com transferência bumpless

**Status:** Aceito · 2026-08-03 · **Hierarquia fixada (assunção da Rodada 3): MAN/AUTO é sub-modo de REMOTO**

## Contexto
O MPC assume e devolve malhas que possuem PID convencional no PLC. A transferência não pode gerar salto nas MVs.

## Decisão
Dois eixos de modo, aplicados ao MPC:
- **LOCAL / REMOTO:** em LOCAL, o controle é do PID no PLC; em REMOTO, o MPC assume. A troca é **bumpless nos dois sentidos**. Para assumir/devolver, o sistema **escreve no PLC as variáveis de modo do PID**, tipicamente alternando AUTO ↔ **RCAS, CAS ou ROUT**.
- **MAN / AUTO (do MPC):** em MAN, o usuário escreve **diretamente nas MVs pela UI do sistema**; em AUTO, o MPC calcula as MVs.

## Consequências
- (+) Alinhado à prática de APC industrial (shed hierarchy PID↔APC).
- O modo-alvo do PID (RCAS/CAS/ROUT) determina O QUE o MPC escreve (SP do PID vs. saída direta) → deve ser **configurável por MV**.
- Bumpless exige: **em LOCAL, a MV do bloco MPC segue (tracking) a MV real do PID no PLC** (tag de readback por MV), de modo que LOCAL→REMOTO parte exatamente do valor vigente; ao devolver (REMOTO→LOCAL), o PID assume com SP/OUT-tracking do seu lado.
- Hierarquia: **em LOCAL o sistema não escreve MV** (PID do PLC controla); MAN/AUTO só tem efeito em REMOTO — MAN: operador escreve MV pela UI; AUTO: MPC calcula.
- Quem opera: papel **operador** (ADR-015).
