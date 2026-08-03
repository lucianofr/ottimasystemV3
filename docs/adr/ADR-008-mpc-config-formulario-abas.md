# ADR-008 — Configuração do MPC por formulário estruturado (modal com abas)

**Status:** Aceito · 2026-08-03 · **Detalhado pelo ADR-013**

## Contexto
O do-mpc exige modelo do processo, horizontes, restrições e pesos. Opções: editor de código livre, formulário estruturado, ou híbrido.

## Decisão
**Formulário completo, sem código:** duplo-clique no bloco MPC abre modal de configuração com **abas por categoria de parâmetros**. O sistema monta o modelo do-mpc internamente a partir do formulário.

## Consequências
- (+) Usuário de processo configura MPC sem escrever Python; validação de campos na UI.
- (−) O tipo de modelo fica **restrito a formas paramétricas** que o formulário consegue expressar — a estrutura exata (ex.: matriz FOPDT por par MV/CV) é decisão pendente.
- Abas previstas (a confirmar): Variáveis (MVs/CVs/DVs), Modelo, Horizontes/Ts, Restrições, Pesos/Objetivo, Modos/Escrita no PLC.
