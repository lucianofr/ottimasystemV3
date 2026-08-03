# ADR-015 — Papéis: admin e OPERADOR (rename de "visualizador")

**Status:** Aceito · 2026-08-03 (substitui a definição de papéis do ADR-001)

## Contexto
"Visualizador" somente-leitura deixava as ações de operação (modos, SP, MV em MAN) exclusivas do admin — engenheiro e operador de painel virariam a mesma pessoa.

## Decisão
Dois papéis:
- **admin:** engenharia (flows, conexões OPC, tags, projetos, usuários) + tudo do operador.
- **operador:** opera modos **LOCAL/REMOTO** e **MAN/AUTO**, **escreve setpoints** e **escreve MVs em MAN**; enxerga tudo; **não edita engenharia**.

## Consequências
- (+) Separação engenharia × operação alinhada à sala de controle real.
- Toda escrita de operação é auditável (quem, quando, o quê) no log de eventos.
- RBAC continua trivial: coluna `role` + dependências (`require_admin`, `require_operator`).
