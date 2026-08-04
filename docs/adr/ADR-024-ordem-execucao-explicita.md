# ADR-024 — Ordem de execução explícita por bloco (altera o ADR-007)

**Status:** Aceito · 2026-08-04 · **Altera o ADR-007** (a ordenação topológica deixa de ser a regra de execução)

## Contexto
O ADR-007 definia a avaliação dos blocos em **ordem topológica** derivada das arestas. Isso garante "leitura antes de cálculo antes de escrita" apenas quando as arestas expressam essa dependência — blocos sem conexão direta entre si (ex.: um OPC-Read e um OPC-Write independentes) ficam com ordem indefinida, e a ordem real de execução fica invisível para o usuário. A prática de FBD industrial (IEC 61131) usa ordem de execução explícita e visível por bloco.

## Decisão
- Cada bloco do flow possui um parâmetro **`exec_order`**: inteiro **de 1 até N** (N = total de blocos do flow), **único por bloco** dentro do flow.
- **O motor executa os blocos estritamente na ordem crescente de `exec_order`** a cada varredura. A ordenação topológica **não** é mais usada para execução.
- Finalidade declarada: garantir por construção que blocos de leitura executem antes de Script/MPC, e estes antes dos blocos de escrita — inclusive quando não há aresta ligando-os.
- Editor: **auto-numeração na inserção** (próximo inteiro livre), edição manual pelo usuário, **badge com o número visível no nó**, validação no salvamento (unicidade e sequência contígua 1..N) e **compactação automática** da numeração ao excluir blocos. *(defaults fixados — sujeitos a veto)*

## Consequências
- **Semântica de ordem invertida:** se uma aresta liga A→B mas `exec_order(B) < exec_order(A)`, B executa com o valor de A **da varredura anterior** (atraso de 1 scan) — semântica determinística e familiar do mundo PLC. O editor emite **aviso não-bloqueante** quando a ordem manual inverte o sentido de uma aresta, para capturar erro sem impedir uso intencional. *(default fixado — sujeito a veto)*
- **Ciclos continuam proibidos no editor (RF-302, inalterado).** Nota: com ordem explícita, laços de realimentação com atraso de 1 scan tornam-se tecnicamente executáveis; habilitá-los é decisão futura, fora desta alteração.
- A análise topológica é rebaixada a ferramenta de **validação/aviso** no editor (detecção de inversões e de ciclos), sem papel na execução.
- Hot-swap (ADR-011) inalterado: renumerar blocos é edição como outra qualquer — aplica na próxima varredura; estado preservado por id de bloco (o `exec_order` não participa da identidade do bloco).
- Multiplicador do MPC (ADR-014) inalterado: o bloco MPC ocupa sua posição na ordem; nas varreduras em que não executa, suas saídas mantêm o último valor.
- `exec_order` vive dentro do `config` do nó no `graph_json` — **sem mudança de schema de banco nem do JSON de projeto** (`schema_version` permanece 1; campo obrigatório a partir da F3, quando os primeiros flows passam a existir).
