# Plan 020: as contagens de entrada/saída do bloco Fuzzy param de divergir do FLL em silêncio

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado antes de passar ao próximo. Se qualquer condição da seção "Condições de
> PARADA" ocorrer, pare e relate — não improvise. Ao terminar, atualize a sua linha na tabela de
> status de `docs/reports/advisor/README.md`.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 453b80f..HEAD -- frontend/src/features/flows/config/ModalConfigBloco.tsx frontend/src/features/flows/graph.ts packages/ottima-core/src/ottima_core/flowgraph/validate.py services/api/src/ottima_api/routers/flows.py`
> Se qualquer arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; em caso de divergência, trate como
> condição de PARADA.

## Status

- **Prioridade**: P1 (fricção que já custou duas sessões de diagnóstico ao dono)
- **Esforço**: S na opção B (rota de introspecção + aviso no modal) · M na opção A (emenda de norma)
- **Risco**: LOW na B (aditivo, nenhuma mudança de contrato) · HIGH na A (muda o JSON de projeto)
- **Depende de**: nada. A decisão A/B é do dono (GATE).
- **Categoria**: bug de UX / contrato de config
- **Planejado em**: commit `453b80f`, 2026-09-28

## Por que isso importa

**Incidente real (2026-09-28), com prova em produção**: o dono desenhou um bloco `fuzzy` no flow
`ctrl-fuzzy-prime` (id 1296, projeto 806), ligou `PV → FUZZY.IN1` e `FUZZY.OUT1 → MV`. O `PUT
/api/flows/1296` foi **recusado** com:

```
nó 'fuzzy_0667fe23' (fuzzy): FLL declara 4 variável(is) de saída; a config espera n_outputs=1
```

(gerada em `flowgraph/validate.py:507-512`). Consequências observadas, todas confirmadas por
consulta ao banco da instalação viva:

1. O nó `fuzzy_0667fe23` **não existia em nenhum dos 10 flows** — o canvas era estado local do
   browser. O `PUT` é atômico: nada do grafo foi gravado.
2. O flow **continuava RODANDO o grafo antigo** (`opc_read → fuzzy_loop_47389637 → opc_write`,
   `desired_state=running`, watchdog vivo). O editor mostrava o bloco novo e o selo "RODANDO" —
   de um grafo que não é o que estava na tela.
3. `GET /api/operate/fuzzy` devolvia só o bloco do irmão `ctrl-fuzzy-omp` (1295); a página FUZZY
   não listava nada do prime. O dono leu isso como "a tela não mostra meu bloco" e gastou duas
   sessões nisso — a tela estava certa; o grafo nunca foi salvo.

A causa não é a validação (ela está certa e a mensagem é precisa): é **o modal permitir montar uma
config inválida sem nenhum aviso e só reagir depois do Salvar**, num formulário que mostra o FLL e
as contagens como se fossem campos independentes. Duas fontes de verdade para a mesma coisa
(quantas portas o bloco tem) e nenhum ponto de checagem antes do 422.

## Estado atual (verbatim, `453b80f`)

**A norma pede a escolha explícita do usuário** — `docs/PRD.md:188` (RF-541):

> Usuário cola o texto **FLL** (FuzzyLite Language) no modal do bloco **e seleciona a quantidade de
> entradas e saídas (1..8 cada)**; entradas viram portas numéricas **IN1..INn** e saídas
> **OUT1..OUTn**, mapeadas **posicionalmente** à ordem de declaração de
> `input_variables`/`output_variables` no FLL — não por nome.

Ou seja: o par (contagens, FLL) ser declarado pelo usuário é requisito, não descuido. O defeito é a
**ausência de feedback** entre os dois, não a existência das contagens.

**O contrato exige igualdade exata** — `packages/ottima-core/src/ottima_core/flowgraph/validate.py`:

```python
# :472  _check_fuzzy_nodes  → chama _valida_fuzzy para type == "fuzzy"
# :480  def _valida_fuzzy(node, errors)   # import lazy de fuzzylite
# :501  n_inputs = len(engine.input_variables);  != config.n_inputs  → erro
# :507  n_outputs = len(engine.output_variables); != config.n_outputs → erro
```

**A segunda camada** — `services/flow-runtime/src/ottima_flow_runtime/blocks/fuzzy.py:87-103` monta
`IN1..INn`/`OUT1..OUTn` a partir das contagens e **refaz a mesma checagem** na construção do
engine (deploy). O deploy já foi recusado no save antes, então na prática o runtime só confirma.

**O caminho do save** — `services/api/src/ottima_api/routers/flows.py:79` (`_validar_grafo`) roda
`parse_graph` + `validate_graph`; `:290-295` converte `resultado.errors` em 422. O JSON é gravado
**verbatim** (`:315-318`, "o editor é o dono do JSON").

**O caminho do import** — `services/api/src/ottima_api/routers/projects.py:88-99` (`_parse_e_validar`)
revalida o mesmo par por flow: um projeto exportado com a divergência é recusado no import
(ADR-012).

**O modal** — `frontend/src/features/flows/config/ModalConfigBloco.tsx`:

```tsx
// :169  function CamposFuzzy({ dados, nOutputs, aoMudarNOutputs })
// :196  <Select id="n_outputs" ... data-testid="config-n-outputs">       // 1..MAX_PORTAS_FUZZY
// :228  <Label htmlFor="fll">FLL (FuzzyLite Language)</Label>            // textarea, texto cru
// :346-360  submit: lê n_outputs/n_inputs dos campos do form junto com o fll
```

Nenhuma linha do modal consulta o servidor sobre o FLL. O FLL só é analisado no `PUT`.

**As portas do canvas vêm das contagens** — `frontend/src/features/flows/graph.ts:89`
(`default_counts`), `:498-520` (`portasScript("IN"/"OUT", n)`), `:1180-1195` (normalização do nó).
Consequência: enquanto as contagens e o FLL divergem, o canvas desenha portas que o FLL não declara
(ou omite as que declara) — a tela mente sobre a forma do bloco até alguém salvar.

**O default é coerente, e é isso que torna a armadilha sutil** — `frontend/src/features/flows/registro.ts:210-219`
usa `contratoFuzzy.default_counts` = `{n_inputs: 1, n_outputs: 4}`
(`packages/ottima-core/src/ottima_core/contracts_export.py:193`) com o FLL padrão de 4
`OutputVariable`. O bloco recém-arrastado **salva**. A divergência nasce quando o usuário mexe em
**um** dos dois lados — tipicamente reduz "Saídas" para casar com o número de fios do desenho.

## Decisão a tomar (GATE — é do dono)

**Opção B — aviso cedo, norma intacta (recomendada; executável agora).**
O modal passa a perguntar ao servidor quantas variáveis o FLL declara (rota nova de introspecção) e
mostra isso ao lado das contagens, com um botão de um clique para alinhar. As contagens continuam
sendo escolha do usuário (RF-541 preservado) e o 422 continua existindo para quem insistir.
Custo: uma rota REST + estado no modal. O JSON de projeto não muda; nenhum `graph_json` gravado
precisa de migração.

**Opção A — fonte única (exige emenda de norma).**
O servidor deriva `n_inputs`/`n_outputs` do FLL no save (e no import) e as contagens deixam de ser
campo do usuário. Elimina a classe inteira do defeito, mas: (1) contradiz RF-541 como escrito
("seleciona a quantidade"); (2) o JSON de projeto passa a ser reescrito pelo servidor, contra a
postura "gravado verbatim, o editor é o dono do JSON" (`flows.py:315-318`); (3) aresta apontando para
porta que deixou de existir precisa virar erro claro, senão o problema só muda de lugar.
**Não cabe num plano de UX**: exige o processo do item 4 do `CLAUDE.md` (emenda de RF-541 + nota na
ADR-029) e é decisão do dono, não do executor.

Este plano executa **B**. Se o dono escolher A, PARE: a emenda documental vem primeiro.

## Escopo da execução (opção B)

**Em escopo**:
- `packages/ottima-core/src/ottima_core/flowgraph/fll_ports.py` (**criar**): uma função,
  `portas_do_fll(fll) -> PortasDoFll` (nomes de `input_variables`/`output_variables` e as duas
  contagens), com import lazy de `fuzzylite` e as MESMAS checagens que `_valida_fuzzy` já faz
  (`FllImporter`, `is_ready`, teto de `resolution` do defuzzificador integral). `validate.py` passa
  a usá-la — **um só lugar analisa FLL no core**, sem segunda convenção.
- `services/api/src/ottima_api/routers/flows.py`: rota `POST /api/flows/fll/portas`,
  `require_admin` (superfície de engenharia, igual ao muro de mutação do editor), teto de tamanho
  igual ao de `FuzzyConfig.fll` (200 000 chars, FUZZY-SEC), parse em `asyncio.to_thread` (CPU-bound,
  TD-002), FLL inválido → **422** com a mensagem do parser.
- `frontend/src/features/flows/config/ModalConfigBloco.tsx`: em `CamposFuzzy`, consultar a rota
  quando o texto do FLL mudar (debounce), mostrar `o FLL declara 1 entrada / 4 saídas` ao lado dos
  dois `Select` e oferecer **"Alinhar contagens ao FLL"**. Divergência não bloqueia o Salvar (a
  decisão continua do usuário), mas fica **vermelha e visível antes** do 422.
- `packages/ottima-core/tests/test_fll_ports.py` e `services/api/tests/test_flows_fll_portas.py`
  (**criar**); `frontend/src/features/flows/config/modalFuzzy.check.ts` (**criar**, função pura de
  comparação com as portas do FLL).

**Fora de escopo** (NÃO toque):
- A regra de igualdade em `validate.py` e a do runtime (`blocks/fuzzy.py`): elas estão **certas**.
  Este plano não afrouxa validação — só antecipa o aviso.
- `graph.ts`, `registro.ts`, `contracts_export.py` e o JSON de projeto/export-import: nada de
  contrato muda na opção B.
- `fuzzy_loop` (`fll_contract.py`, ADR-039): o FLL dele é fechado por contrato, não tem contagens.
- Qualquer `docs/` normativo (PRD, ADR, GLOSSARY) — a opção A é a única que os toca, e ela não roda.

## Passos

### Passo 1: extrair a análise de FLL para uma função só (TDD)

Crie `flowgraph/fll_ports.py` com `portas_do_fll(fll)` e faça `_valida_fuzzy` usá-la
(`validate.py:480-512`), mantendo **as mensagens de erro idênticas** (os testes existentes e o
422 da API as citam). Teste primeiro (`test_fll_ports.py`, RED): FLL de 1 entrada/4 saídas devolve
`(1, 4)` e os nomes na ordem de declaração; FLL que não parseia levanta `ValueError` com o texto do
`FllImporter`; defuzzificador integral com `resolution` acima do teto é rejeitado.

**Verifique**: `uv run pytest packages/ottima-core/tests -q` verde, incluindo os testes que já
pinam as mensagens (`test_fll_contract.py`, testes de `validate`).

### Passo 2: rota de introspecção

`POST /api/flows/fll/portas` → `{n_inputs, n_outputs, inputs: [...], outputs: [...]}`. Teto de
tamanho antes do parse (`_excede_o_declarado` como padrão de `connections.py:88`), parse em
`asyncio.to_thread`, `require_admin`.

**Verifique**: `uv run pytest services/api/tests -q`. A rota responde 200 para o FLL padrão do
bloco com `n_inputs: 1, n_outputs: 4`; 422 com FLL quebrado; 413/422 acima do teto; 401 sem token.

### Passo 3: o modal avisa antes

Em `CamposFuzzy`, ao mudar o FLL (debounce ≥ 400 ms) chame a rota; mostre as contagens declaradas
e, quando divergirem das selecionadas, o aviso em tom de alarme + o botão "Alinhar contagens ao
FLL". Sem FLL válido, mostre o erro do parser no lugar do aviso. **Não** altere os `Select`
sozinho.

**Verifique**: `cd frontend && npm run test:unit` (a checagem pura nova verde) e
`npm run typecheck && npm run build`.

### Passo 4 (prova real, obrigatória antes de fechar)

No editor, com o stack no ar: abra o bloco `fuzzy` do `ctrl-fuzzy-prime`, cole um FLL de 4 saídas
com "Saídas" em 1 e confirme que o aviso aparece **antes** de clicar Salvar; clique "Alinhar
contagens ao FLL" e confirme que o Salvar passa. Registre o resultado no relato (o que apareceu na
tela, com `data-testid`).

**Verifique**: nenhum 422 depois do alinhamento; `GET /api/operate/fuzzy` lista o bloco.

## Plano de teste

- **Novo**: `packages/ottima-core/tests/test_fll_ports.py` — a análise única de FLL.
- **Novo**: `services/api/tests/test_flows_fll_portas.py` — rota (sucesso, FLL inválido, teto,
  autorização).
- **Novo**: `frontend/src/features/flows/config/modalFuzzy.check.ts` — comparação pura
  contagens × portas do FLL (o que liga o aviso e o botão).
- **Nenhum teste existente deve mudar**: se algum teste de save/validação precisar de ajuste, o
  executor tocou em validação — **volte atrás** e relate.

## Critérios de conclusão

- [ ] `flowgraph/fll_ports.py` existe e `_valida_fuzzy` o usa (nenhum segundo parse de FLL no core)
- [ ] `POST /api/flows/fll/portas` responde 200/422 conforme o FLL e exige admin
- [ ] O modal mostra as contagens declaradas pelo FLL e oferece o alinhamento
- [ ] Passo 4 executado com registro do que a tela mostrou
- [ ] `uv run pytest`, `npm run test:unit`, `npm run typecheck`, `npm run build` verdes
- [ ] Nenhum arquivo de `docs/` normativo tocado
- [ ] Linha de status atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- O dono escolher a **opção A**: emenda de RF-541/ADR-029 primeiro (processo do item 4 do `CLAUDE.md`).
- As mensagens de `validate.py` não puderem ser preservadas ao extrair `portas_do_fll`.
- `require_admin` na rota nova quebrar algum fluxo do editor (o modal é usado só por quem muta —
  confirme antes de relaxar para `require_operator`).
- Extrair a análise exigir importar `fuzzylite` fora do caminho lazy (a ADR-029 proíbe: o custo de
  import vaza para todo `import ottima_core`).
- Qualquer passo exigir mexer em `graph.ts`/JSON de projeto/export-import: isso é opção A disfarçada.

## Fluxo de git

- Branch: `advisor/020-contagens-fuzzy-vs-fll`.
- Um commit por passo lógico: core (Passo 1) · API (Passo 2) · frontend (Passo 3).
  Mensagens em Conventional Commits, pt-BR, ex.:
  `feat(core): analise de FLL em um lugar so (portas declaradas)` ·
  `feat(api): rota que diz quantas portas o FLL declara` ·
  `feat(frontend): modal do bloco Fuzzy avisa quando as contagens divergem do FLL`.
- Sem push, sem PR, a menos que o dono peça.
- Em worktree: caminho **ABSOLUTO** em todo `read`/`write`/`edit`, `cwd` explícito em todo shell,
  confirmação por shell depois de cada escrita (`CLAUDE.md`, "Subagente em worktree").

## Notas de manutenção

- **O que interage com isto**: qualquer mudança na forma do `FuzzyConfig` ou na validação do FLL.
  Se `portas_do_fll` passar a ser fonte única no save (opção A), este plano vira o pré-requisito
  dela — a função já estará no lugar.
- **O que um revisor deve olhar**: (1) zero mudança de comportamento do save (o 422 continua);
  (2) reuso do parse (nenhuma segunda convenção de FLL); (3) o modal **não** altera as contagens
  sozinho.
- **Relação com o incidente de 2026-09-28**: aquele flow foi corrigido por `PUT` direto (grafo do
  próprio canvas do dono, com um FLL de 1 entrada/1 saída na faixa da MV). Este plano é sobre o
  caminho que **permitiu** a divergência silenciosa, não sobre aquele bloco.
