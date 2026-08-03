# ADR-011 — Hot-swap de flows sem interrupção; sem versionamento

**Status:** Aceito · 2026-08-03

## Contexto
Parar um flow para editar significa devolver malhas ao PLC a cada ajuste de engenharia — inaceitável em operação.

## Decisão
Edições de um flow em execução **entram em vigor na próxima varredura, sem interrupção** da execução. **Não haverá versionamento** de flows.

## Consequências
- (+) Ajuste online, como num PLC.
- O runtime troca a definição do grafo **atomicamente entre varreduras** (nunca no meio de uma).
- Blocos não alterados **preservam estado** entre a versão antiga e a nova (MPC mantém histórico/estado do solver).
- Assunção a validar: se os parâmetros do próprio bloco MPC mudarem, o controlador é re-instanciado e re-inicializado de forma bumpless (partindo das MVs atuais).
- Sem versionamento: erro de edição não tem rollback automático — mitigação fica no export/import de projeto (ADR-012).
