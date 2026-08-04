# ADR-018 — Contrato do bloco Python-Script

**Status:** Aceito · 2026-08-03

## Contexto
O bloco de script é a válvula de escape para lógica arbitrária (condicionamento, seleção, intertravamento leve) sem inflar a paleta de blocos.

## Decisão
- **Portas definidas pelo usuário** no modal do bloco (quantidade de entradas e saídas).
- Convenção de nomes injetados no escopo: entradas **IN1, IN2, IN3, …**; saídas **OUT1, OUT2, OUT3, …** (o script atribui às variáveis OUTx).
- **Estado persistente entre varreduras:** dict `state` injetado, preservado por instância de bloco (sobrevive ao hot-swap se o bloco não for alterado, cf. ADR-011).
- **Bibliotecas disponíveis: `math` e `numpy`** — mais nada no escopo.
- **Timeout:** ~70% do Ts do flow; ao estourar, mantém as últimas saídas + alarme (mesma política do MPC, ADR-014).

## Consequências
- (+) Contrato simples de documentar e de validar; nomes previsíveis tornam o script legível.
- Execução via `exec()` em namespace controlado, rodando em executor (nunca no event loop); modelo de ameaça = admin autenticado, sem sandboxing pesado.
- Exceção no script: saídas mantêm último valor + alarme com traceback no log de eventos.
