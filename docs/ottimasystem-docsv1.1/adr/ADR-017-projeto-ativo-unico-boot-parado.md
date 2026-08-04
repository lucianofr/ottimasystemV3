# ADR-017 — Vários projetos armazenados, um ativo; boot em estado parado

**Status:** Aceito · 2026-08-03 (fecha as pendências do ADR-012)

## Contexto
Era preciso decidir concorrência de projetos e comportamento pós-reboot de um sistema que escreve em planta.

## Decisão
- O banco guarda **N projetos**, mas **apenas um está ativo** por vez; ativar outro projeto encerra a execução do atual.
- **No boot do servidor, os flows sobem PARADOS**, aguardando novo **deploy** (comando explícito de início). Nenhuma escrita em planta ocorre sem ação humana pós-boot.

## Consequências
- (+) Seguro por padrão: reboot nunca reassume malhas sozinho (coerente com watchdog/ADR-009 — o PLC já assumiu).
- "Deploy" entra no vocabulário como o ato de colocar flow em execução (glossário).
- O estado desejado (rodando/parado) por flow é persistido para exibição, mas não é auto-aplicado no boot.
