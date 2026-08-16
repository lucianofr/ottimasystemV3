# ADR-034 — Espelho de contrato Python↔TS: forma gerada, regra travada por golden, default à mão

**Status:** Aceito · 2026-08-15

## Contexto

Três mecanismos diferentes mantêm o TypeScript de acordo com o Python, e eles foram construídos em
momentos distintos, sem nunca ter tido a fronteira entre si escrita:

1. **Geração de forma.** `ottima_core.contracts_export::build_contracts()` emite
   `model_json_schema()` de um conjunto de models; `frontend/scripts/generate-contracts.mjs`
   materializa isso em `frontend/src/lib/contracts.gen.ts`. Cobre hoje `PORT_CONTRACTS` (portas por
   bloco) e os payloads do WS. Em paralelo, `openapi-typescript` gera `api-types.ts` do
   `openapi.json` — mesma categoria, mecanismo distinto.
2. **Trava de regra por golden.** `ottima_core.mpc_golden_export` grava
   `frontend/src/features/flows/mpc/mpcLogic.golden.json` a partir da implementação real do
   backend; os dois lados comparam contra o mesmo arquivo. Mudar uma regra num lado só fica
   vermelho. Ex.: `"regra": "numbers_mv_max_rate_nao_positivo"`.
3. **Espelho manual de default.** Os leitores de `graph_json` em TS (`graphMpc.ts::ler*()`,
   `graph.ts`) escrevem os defaults do Pydantic como literais, justificados por comentário
   (`RF-609/613`, `TD-007`: "os mesmos defaults do `MvVar` do servidor").

A auditoria de arquitetura de 2026-08-15 (`docs/reports/arch/arch-review-20260815.md`) propôs
estender (1) em duas frentes: ARCH-06, gerar a **forma** dos configs de bloco; e ARCH-07, gerar uma
tabela de **defaults**. O aprofundamento do ARCH-07 mostrou que as duas propostas têm mérito muito
diferente, e que tratá-las como uma coisa só leva a conclusão errada nos dois sentidos — ou se gera
tudo, ou se descarta tudo. Esta ADR fixa a fronteira.

## Decisão

### Forma é gerada

Toda estrutura de dados que atravessa a fronteira Python→TS — nome e tipo de campo, portas de
bloco, envelope de mensagem do WS, corpo de requisição/resposta REST — é **gerada** a partir do
Pydantic, nunca reescrita à mão. Quando um consumidor TS precisa de um tipo que o Python já
declara, o caminho é acrescentar o model ao exportador, não redigitar a interface.

Consequência direta: ARCH-06 / TD-018 seguem **válidos e recomendados**. As interfaces hand-typed
de `graph.ts` para `MvVar`/`CvVar`/`ConstraintVar`/`DvVar`/`MpcConfig`/`ScriptConfig`/`FuzzyConfig`/
`TfsConfig`/`PidConfig` são débito legítimo, e o pipeline que já serve `PORT_CONTRACTS` e os
payloads do WS é o lugar certo para elas.

### Regra é travada por golden, não por geração

Regra de negócio espelhada no cliente para feedback instantâneo — teto por categoria, piso
numérico, precedência, dimensão de estado — é garantida por **golden JSON gerado da implementação
real do backend**, comparado pelos dois lados. Não se gera código de validação em TS a partir do
Python; gera-se a tabela-verdade e compara-se o comportamento.

Isso é o que torna o espelho manual seguro: o que importa não é o TS ter os mesmos literais que o
Python, é o TS chegar ao mesmo **veredito** que o Python. O golden prova o veredito.

Consequência direta: ARCH-22 (estender o mecanismo golden para as fórmulas de **Pendência** de
conexão, hoje escritas "da spec" independentemente nos dois lados, sem trava) é a direção correta
sob esta ADR, e continua recomendado.

### Default literal pode ser espelhado à mão

Um leitor TS pode escrever o default do Pydantic como literal, desde que a **consequência
observável** desse default esteja coberta pelo golden ou por teste próprio. Não se gera tabela de
defaults.

Razões:

- **Não há o que gerar para campo obrigatório.** `MvVar.max_rate` é required e não tem default. Uma
  tabela gerada de defaults simplesmente não teria linha para ele — e é justamente o campo que
  motivou a proposta.
- **O golden já cobre o que dói.** Um default divergente só machuca se mudar um veredito de
  validação ou um valor persistido; as duas coisas o golden e os testes de ida-e-volta pegam.
- **Custo/benefício negativo.** Gerar a tabela move os literais para dentro de um gerador e
  acrescenta um artefato gerado a mais no repositório, contra uma classe de divergência que produziu
  **zero defeitos observados** em `du_min`, `move_weight`, `zero`, `span`, `description`,
  `objective`, `fail_action`, `traj_tau_s`, `track_sp`, `fail_timeout_s`, `priority` e
  `operating_point`.

### Piso e teto numérico ficam fora do Pydantic quando a mensagem importa

`MvVar.max_rate` não leva `gt=0` de propósito (`flowgraph/mpc_config.py`): um constraint do Pydantic
trocaria o 422 legível em pt-BR pela localização de campo do Pydantic. O piso mora em
`validate._check_mpc_numbers`, espelhado no Resumo do editor e travado pelo golden. Este padrão —
**regra semântica em `validate.py`, forma em Pydantic** — é a norma, não a exceção, e não deve ser
lido por auditoria futura como validação faltando no model.

### Ausência de campo required é config incompleto, não config antigo

Um `graph_json` sem um campo required não é "versão antiga do contrato": é config inválido. O leitor
TS deve devolver um valor que a validação do editor **recuse** (sentinela), nunca um valor plausível
que o usuário não digitou. `graphMpc.ts` devolve `0` para `max_rate` ausente exatamente por isso — e
`0` é o valor de MV congelada do ADR-028, que o Resumo barra na cara. Fabricar uma taxa plausível
esconderia o config incompleto e poderia chegar à planta.

## Consequências

- (+) Fronteira escrita: auditoria futura sabe que "gerar tipos do Pydantic" é recomendado para
  **forma** e recusado para **tabela de defaults**, sem precisar re-litigar nenhum dos dois.
- (+) ARCH-06 / TD-018 (gerar a forma dos configs de bloco) sobrevive com escopo limpo, sem ser
  morto por associação com a metade descartada.
- (+) ARCH-22 (golden para Pendência) ganha respaldo explícito: é o mecanismo certo para regra
  espelhada, e hoje só o MPC o usa.
- (+) O padrão "piso em `validate.py`, não em `Field(gt=...)`" fica registrado como decisão, não como
  omissão — a mensagem pt-BR do 422 é o motivo.
- (−) Defaults continuam existindo em dois lugares (Pydantic e leitor TS), e a divergência continua
  possível em princípio. Aceito: a consequência observável é coberta, e o custo de fechar essa porta
  específica é maior que o risco que ela representa. Se aparecer um primeiro defeito real de default
  divergente, esta ADR deve ser revisitada — o defeito é a evidência que hoje falta.
- (−) Quem acrescentar um campo com default ao Pydantic precisa lembrar do leitor TS. Mitigação
  existente: o teste de ida-e-volta de `graph.check.ts` e, para regra, o golden.
